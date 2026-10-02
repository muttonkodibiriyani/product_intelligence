"""Proxy routing: named page hosts only, pictures never, metered against the owner's cap."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from page_capture import proxy, run
from page_capture.plan import Item, Plan
from page_capture.store import Store

T0 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
ROBOTS = "User-agent: *\nAllow: /\n"
PAGE = "<html><body>" + "x" * 70_000 + "</body></html>"
VERSION = "projects/p/secrets/s/versions/1"  # a resource name, not a credential


class _Resp:
    def __init__(self, status: int, text: str, ct: str = "text/html", url: str = ""):
        self.status_code = status
        self._text = text
        self._ct = ct
        self._url = url
        self.num_bytes_downloaded = 5_000  # compressed on the wire, smaller than the body

    @property
    def content(self) -> bytes:
        return self._text.encode()

    @property
    def text(self) -> str:
        return self._text

    @property
    def headers(self) -> Mapping[str, str]:
        return {"content-type": self._ct}

    @property
    def url(self) -> str:
        return self._url


class _Cookies:
    def clear(self) -> None:
        return None


class _Client:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.cookies = _Cookies()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> _Resp:
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return _Resp(200, ROBOTS, "text/plain", url)
        if "/img/" in url:
            return _Resp(200, "jpegbytes", "image/jpeg", url)
        return _Resp(200, PAGE, "text/html", url)


def _env(**extra: str) -> dict[str, str]:
    return {
        "BUCKET": "file:/tmp/x",
        "PREFIX": "p",
        "PLAN": "plan.json",
        "CUTOFF": (T0 + timedelta(hours=1)).isoformat(),
        **extra,
    }


def test_config_requires_hosts_and_secret_together() -> None:
    with pytest.raises(ValueError, match="needs PROXY_SECRET"):
        run.config_from_env(_env(PROXY_HOSTS="www.nysaa.com"))
    with pytest.raises(ValueError, match="without PROXY_HOSTS"):
        run.config_from_env(_env(PROXY_SECRET=VERSION))
    with pytest.raises(ValueError, match="owner cap"):
        run.config_from_env(
            _env(
                PROXY_HOSTS="www.nysaa.com",
                PROXY_SECRET=VERSION,
                PROXY_BYTE_CAP=str(proxy.DEFAULT_BYTE_CAP + 1),
            )
        )
    cfg = run.config_from_env(
        _env(PROXY_HOSTS=" www.Nysaa.com, www.amazon.ae", PROXY_SECRET=VERSION)
    )
    assert cfg.proxy_hosts == ("www.nysaa.com", "www.amazon.ae")
    assert cfg.proxy_byte_cap == proxy.DEFAULT_BYTE_CAP
    assert run.config_from_env(_env()).proxy_hosts == ()


def test_endpoint_parsing_and_repr_hide_the_credential() -> None:
    payload = json.dumps(
        {"host": "geo.example", "port": "12321", "username": "u", "password": "p", "provider": "x"}
    )
    ep = proxy.parse_endpoint(payload)
    assert ep.url == "http://u:p@geo.example:12321"
    shown = repr(ep)
    assert shown == "ProxyEndpoint(host='geo.example', port=12321, provider='x')"
    assert "u:p@" not in shown
    with pytest.raises(ValueError, match="missing port, password"):
        proxy.parse_endpoint(json.dumps({"host": "h", "username": "u"}))
    with pytest.raises(ValueError, match="not JSON"):
        proxy.parse_endpoint("nope")
    with pytest.raises(ValueError, match="JSON object"):
        proxy.parse_endpoint("[1]")


def test_access_secret_decodes_the_payload() -> None:
    data = base64.b64encode(b'{"host":"h"}').decode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        assert request.url.path.endswith("/versions/3:access")
        return httpx.Response(200, json={"payload": {"data": data}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert proxy.access_secret("projects/p/secrets/s/versions/3", "tok", client) == '{"host":"h"}'
    denied = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(403)))
    with pytest.raises(RuntimeError, match="http 403"):
        proxy.access_secret("projects/p/secrets/s/versions/3", "tok", denied)


def test_meter_and_wire_bytes() -> None:
    m = proxy.Meter(cap=12_000)
    m.charge(5_000)
    before = m.exhausted
    m.charge(5_000)
    after = m.exhausted
    assert m.used == 2 * (5_000 + proxy.REQUEST_ALLOWANCE)
    assert (before, after) == (False, True)
    assert proxy.wire_bytes(_Resp(200, "abc")) == 5_000
    r = _Resp(200, "abc")
    r.num_bytes_downloaded = 0
    assert proxy.wire_bytes(r) == 3


def _job(tmp_path: str, cap: int) -> tuple[run.Job, _Client, _Client]:
    cfg = run.config_from_env(
        {
            **_env(PROXY_HOSTS="www.nysaa.com", PROXY_SECRET=VERSION),
            "BUCKET": f"file:{tmp_path}",
            "PROXY_BYTE_CAP": str(cap),
        }
    )
    direct, via = _Client(), _Client()
    job = run.Job(
        cfg,
        client=direct,
        proxy_client=via,
        store=Store(cfg.bucket, "r"),
        clock=lambda: T0,
        sleep=lambda _s: None,
    )
    job.plan = Plan("nysaa_ae", "nysaa", ())
    return job, direct, via


def test_named_host_pages_go_via_proxy_pictures_and_other_hosts_direct(tmp_path: object) -> None:
    job, direct, via = _job(str(tmp_path), cap=proxy.DEFAULT_BYTE_CAP)
    item = Item(
        "n-1",
        "https://www.nysaa.com/x/p/1",
        "en-AE",
        "html",
        {},
        ("https://www.nysaa.com/img/1.jpg", "https://cdn.other/img/2.jpg"),
    )
    other = Item("f-1", "https://www.faces.ae/en/p/x.html", "en-AE", "html", {})
    job.one(item)
    for url in item.images:
        job.image(item, url)
    job.one(other)
    assert via.calls == ["https://www.nysaa.com/robots.txt", "https://www.nysaa.com/x/p/1"]
    assert "https://www.nysaa.com/img/1.jpg" in direct.calls
    assert "https://cdn.other/img/2.jpg" in direct.calls
    assert "https://www.faces.ae/en/p/x.html" in direct.calls
    assert job.counts["proxy_requests"] == 2
    assert job.meter.used == 2 * (5_000 + proxy.REQUEST_ALLOWANCE)
    job.finish()
    status = json.loads((tmp_path / "r" / "status.json").read_text())  # type: ignore[operator]
    assert status["proxy_bytes"] == job.meter.used
    assert status["proxy_byte_cap"] == proxy.DEFAULT_BYTE_CAP


def test_cap_stops_the_proxied_host_and_nothing_else(tmp_path: object) -> None:
    job, direct, via = _job(str(tmp_path), cap=2 * (5_000 + proxy.REQUEST_ALLOWANCE))
    items = [
        Item(f"n-{i}", f"https://www.nysaa.com/x/p/{i}", "en-AE", "html", {}) for i in range(3)
    ]
    for it in items:
        job.one(it)
    # robots + first page spend the cap; the second page is recorded proxy_cap, the third skipped
    assert len(via.calls) == 2
    assert job.counts["pages_ok"] == 1
    assert job.counts["pages_proxy_cap"] == 1
    assert job.counts["pages_skipped_host_stopped"] == 1
    assert job.hosts["www.nysaa.com"].stopped is not None
    assert "proxy byte cap" in str(job.hosts["www.nysaa.com"].stopped)
    job.one(Item("f-1", "https://www.faces.ae/en/p/x.html", "en-AE", "html", {}))
    assert job.counts["pages_ok"] == 2
    assert direct.calls[-1] == "https://www.faces.ae/en/p/x.html"
    job.load = lambda: None  # type: ignore[method-assign]
    job.manifest("sha", 3)
    manifest = json.loads((tmp_path / "r" / "manifest.json").read_text())  # type: ignore[operator]
    assert manifest["proxy"] == {
        "hosts": ["www.nysaa.com"],
        "secret": VERSION,
        "byte_cap": job.cfg.proxy_byte_cap,
    }


def test_without_proxy_hosts_no_proxy_client_is_built(tmp_path: object) -> None:
    cfg = run.config_from_env({**_env(), "BUCKET": f"file:{tmp_path}"})
    job = run.Job(cfg, client=_Client(), store=Store(cfg.bucket, "r"), clock=lambda: T0)
    assert job.proxy_client is None
    assert job.client_for(job.host_for("https://www.nysaa.com/"), "html") is job.client


def test_sharded_tasks_write_distinct_names(tmp_path: object) -> None:
    """Two tasks of one run must never overwrite each other's parts or summaries."""
    written: dict[int, set[str]] = {}
    for index in range(2):
        env = {
            **_env(),
            "BUCKET": f"file:{tmp_path}",
            "CLOUD_RUN_TASK_INDEX": str(index),
            "CLOUD_RUN_TASK_COUNT": "2",
        }
        job = run.Job(
            run.config_from_env(env),
            client=_Client(),
            store=Store(f"file:{tmp_path}", "r"),
            clock=lambda: T0,
            sleep=lambda _s: None,
        )
        job.plan = Plan("faces_ae", "faces", ())
        job.one(Item(f"f-{index}", f"https://www.faces.ae/en/p/{index}.html", "en-AE", "html", {}))
        job.finish()
        root = tmp_path / "r"  # type: ignore[operator]
        written[index] = {str(f.relative_to(root)) for f in root.rglob("*") if f.is_file()}
    only_second = written[1] - written[0]
    assert "pages/part-t1-0000.jsonl.gz" in only_second
    assert {"progress.t1.json", "status.t1.json", "robots.t1.json"} <= only_second
    assert "pages/part-t0-0000.jsonl.gz" in written[0]
    assert "progress.json" not in written[1]


def test_images_kind_fetches_pictures_only(tmp_path: object) -> None:
    """A pictures-only pass never asks for the page again."""
    plan = {
        "source": "faces_ae",
        "retailer": "faces",
        "version": 1,
        "items": [
            {
                "id": "f-1",
                "url": "https://www.faces.ae/en/p/x.html",
                "locale": "en-AE",
                "kind": "images",
                "ref": {},
                "images": ["https://www.faces.ae/img/1.jpg"],
            }
        ],
    }
    plan_path = tmp_path / "plan.json"  # type: ignore[operator]
    plan_path.write_text(json.dumps(plan))
    cfg = run.config_from_env({**_env(), "BUCKET": f"file:{tmp_path}", "PLAN": str(plan_path)})
    client = _Client()
    job = run.Job(
        cfg, client=client, store=Store(cfg.bucket, "r"), clock=lambda: T0, sleep=lambda _s: None
    )
    job.run()
    assert client.calls == ["https://www.faces.ae/robots.txt", "https://www.faces.ae/img/1.jpg"]
    assert job.counts.get("pages_ok", 0) == 0
    assert job.counts["images_ok"] == 1
