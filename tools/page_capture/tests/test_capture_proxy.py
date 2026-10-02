"""Proxy routing: named page hosts only, pictures never, metered against the owner's cap."""

from __future__ import annotations

import base64
import json
import pathlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from page_capture import proxy, run
from page_capture import store as store_mod
from page_capture.plan import Item, Plan
from page_capture.store import Store

T0 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)


def _clock() -> str:
    return T0.isoformat()


ROBOTS = "User-agent: *\nAllow: /\n"
PAGE = "<html><body>" + "x" * 70_000 + "</body></html>"
VERSION = "projects/p/secrets/s/versions/1"  # a resource name, not a credential
HOST = "www.nysaa.com"


def _ledger(tmp_path: object, cap: int = proxy.DEFAULT_BYTE_CAP, used: int = 0) -> str:
    path = f"{tmp_path}/ledger.json"
    with open(path, "w") as fh:
        json.dump({"provider": "test", "cap_bytes": cap, "used_bytes": used, "runs": {}}, fh)
    return path


def _ledger_doc(path: str) -> dict[str, object]:
    with open(path) as fh:
        doc: dict[str, object] = json.load(fh)
    return doc


class _Resp:
    def __init__(self, status: int, text: str, ct: str = "text/html", url: str = ""):
        self.status_code = status
        self._text = text
        self._ct = ct
        self._url = url
        self.location = ""
        self.num_bytes_downloaded = 5_000  # compressed on the wire, smaller than the body

    @property
    def content(self) -> bytes:
        return self._text.encode()

    @property
    def text(self) -> str:
        return self._text

    @property
    def headers(self) -> Mapping[str, str]:
        return {"content-type": self._ct, "location": self.location}

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
        self.redirects: dict[str, str] = {}

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> _Resp:
        self.calls.append(url)
        if url in self.redirects:
            r = _Resp(302, "", "text/html", url)
            r.location = self.redirects[url]
            return r
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


def _proxy_env(**extra: str) -> dict[str, str]:
    base = {"PROXY_HOSTS": HOST, "PROXY_SECRET": VERSION, "PROXY_LEDGER": "gs://b/ledger.json"}
    return _env(**{**base, **extra})


def test_config_requires_hosts_secret_and_ledger_together() -> None:
    with pytest.raises(ValueError, match="needs PROXY_SECRET"):
        run.config_from_env(_env(PROXY_HOSTS=HOST))
    with pytest.raises(ValueError, match="without PROXY_HOSTS"):
        run.config_from_env(_env(PROXY_SECRET=VERSION))
    with pytest.raises(ValueError, match="needs PROXY_LEDGER"):
        run.config_from_env(_env(PROXY_HOSTS=HOST, PROXY_SECRET=VERSION))
    with pytest.raises(ValueError, match="owner cap"):
        run.config_from_env(_proxy_env(PROXY_BYTE_CAP=str(proxy.DEFAULT_BYTE_CAP + 1)))
    cfg = run.config_from_env(_proxy_env(PROXY_HOSTS=" www.Nysaa.com, www.amazon.ae"))
    assert cfg.proxy_hosts == ("www.nysaa.com", "www.amazon.ae")
    assert cfg.proxy_byte_cap == proxy.DEFAULT_BYTE_CAP
    assert cfg.proxy_ledger == "gs://b/ledger.json"
    assert run.config_from_env(_env()).proxy_hosts == ()


def test_config_refuses_hosts_outside_scope_and_sharded_jobs() -> None:
    with pytest.raises(ValueError, match="outside the owner's scope"):
        run.config_from_env(_proxy_env(PROXY_HOSTS="www.ulta.ae"))
    with pytest.raises(ValueError, match="outside the owner's scope"):
        run.config_from_env(_proxy_env(PROXY_HOSTS=f"{HOST},shop.example"))
    with pytest.raises(ValueError, match="sharded job"):
        run.config_from_env(_proxy_env(CLOUD_RUN_TASK_INDEX="0", CLOUD_RUN_TASK_COUNT="2"))
    # a sharded run without a proxy is fine
    cfg = run.config_from_env(_env(CLOUD_RUN_TASK_INDEX="1", CLOUD_RUN_TASK_COUNT="2"))
    assert cfg.task_count == 2


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


def _job(
    tmp_path: str, cap: int, ledger: str | None = None, prefix: str = "r"
) -> tuple[run.Job, _Client, _Client]:
    cfg = run.config_from_env(
        {
            **_proxy_env(PROXY_LEDGER=ledger or _ledger(tmp_path)),
            "BUCKET": f"file:{tmp_path}",
            "PREFIX": prefix,
            "PROXY_BYTE_CAP": str(cap),
        }
    )
    direct, via = _Client(), _Client()
    job = run.Job(
        cfg,
        client=direct,
        proxy_client=via,
        store=Store(cfg.bucket, prefix),
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
        "ledger": job.cfg.proxy_ledger,
        "run_cap": job.cfg.proxy_byte_cap,
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


def test_ledger_is_shared_across_runs_and_caps_the_next_one(tmp_path: object) -> None:
    ledger = _ledger(tmp_path, cap=3 * (5_000 + proxy.REQUEST_ALLOWANCE), used=0)
    first, _, via = _job(str(tmp_path), cap=proxy.DEFAULT_BYTE_CAP, ledger=ledger, prefix="run1")
    first.one(Item("n-1", f"https://{HOST}/x/p/1", "en-AE", "html", {}))
    assert len(via.calls) == 2  # robots + page, both charged to the ledger
    doc = _ledger_doc(ledger)
    assert doc["used_bytes"] == 2 * (5_000 + proxy.REQUEST_ALLOWANCE)
    assert doc["runs"] == {"run1": 2 * (5_000 + proxy.REQUEST_ALLOWANCE)}
    assert doc["updated"] == T0.isoformat()
    # the second run only gets what is left, whatever its own PROXY_BYTE_CAP says
    second, _, via2 = _job(str(tmp_path), cap=proxy.DEFAULT_BYTE_CAP, ledger=ledger, prefix="run2")
    assert second.meter.cap == 5_000 + proxy.REQUEST_ALLOWANCE
    second.one(Item("n-1", f"https://{HOST}/x/p/1", "en-AE", "html", {}))
    second.one(Item("n-2", f"https://{HOST}/x/p/2", "en-AE", "html", {}))
    assert via2.calls == [f"https://{HOST}/robots.txt"]  # robots spent the share; page refused
    assert second.counts["pages_proxy_cap"] == 1
    assert _ledger_doc(ledger)["used_bytes"] == 3 * (5_000 + proxy.REQUEST_ALLOWANCE)
    second.finish()
    status = json.loads((tmp_path / "run2" / "status.json").read_text())  # type: ignore[operator]
    assert status["proxy_run_cap"] == 5_000 + proxy.REQUEST_ALLOWANCE
    assert status["proxy_ledger_remaining"] == 0
    # and a third run cannot start at all
    with pytest.raises(proxy.LedgerError, match="exhausted"):
        _job(str(tmp_path), cap=proxy.DEFAULT_BYTE_CAP, ledger=ledger, prefix="run3")


def test_two_runs_started_together_cannot_overspend_the_ledger(tmp_path: object) -> None:
    """The Reviewer's probe: ledger nearly spent, two runs start before either fetches."""
    unit = 5_000 + proxy.REQUEST_ALLOWANCE
    ledger = _ledger(tmp_path, cap=10 * unit, used=8 * unit)  # 2 units left for everyone
    a, _, via_a = _job(str(tmp_path), cap=proxy.DEFAULT_BYTE_CAP, ledger=ledger, prefix="a")
    b, _, via_b = _job(str(tmp_path), cap=proxy.DEFAULT_BYTE_CAP, ledger=ledger, prefix="b")
    assert a.meter.cap == b.meter.cap == 2 * unit  # each run alone could spend what is left
    a.one(Item("n-1", f"https://{HOST}/x/p/1", "en-AE", "html", {}))
    assert len(via_a.calls) == 2  # robots + page: run a spends the whole remainder
    assert _ledger_doc(ledger)["used_bytes"] == 10 * unit
    # run b has spent nothing itself, but the shared balance is gone: nothing goes out
    assert b.meter.used == 0
    b.one(Item("n-1", f"https://{HOST}/x/p/1", "en-AE", "html", {}))
    assert via_b.calls == []  # not even robots.txt goes through the proxy
    assert str(b.hosts[HOST].stopped).startswith("proxy byte cap")
    assert b.counts["hosts_stopped"] == 1
    assert _ledger_doc(ledger)["used_bytes"] == 10 * unit  # not a byte over the cap
    b.finish()
    status = json.loads((tmp_path / "b" / "status.json").read_text())  # type: ignore[operator]
    assert status["proxy_ledger_remaining"] == 0
    assert status["proxy_ledger_fault"] is None


def test_meter_fails_closed_when_the_ledger_cannot_be_reread(tmp_path: object) -> None:
    path = _ledger(tmp_path, cap=1_000_000, used=0)
    meter = proxy.Meter(
        cap=1_000_000, ledger=proxy.Ledger(store_mod.FileLedgerStore(path), "r", _clock)
    )
    states = [meter.exhausted]
    pathlib.Path(path).write_text("{not json")
    states.append(meter.exhausted)
    assert states == [False, True]
    assert meter.ledger_fault == "proxy ledger is not JSON"


class _FaultyStore:
    """A store whose transport fails: load or save raises what a GCS client would."""

    def __init__(self, doc: dict[str, object], *, load_fault: Exception | None = None) -> None:
        self.data = json.dumps(doc).encode()
        self.load_fault = load_fault
        self.save_fault: Exception | None = None

    def load(self) -> tuple[bytes, object] | None:
        if self.load_fault is not None:
            raise self.load_fault
        return self.data, 1

    def save(self, data: bytes, token: object) -> bool:
        if self.save_fault is not None:
            raise self.save_fault
        self.data = data
        return True


@pytest.mark.parametrize(
    "fault",
    [
        ConnectionResetError(104, "Connection reset by peer"),
        TimeoutError("read timed out"),
        PermissionError(13, "forbidden"),
        RuntimeError("503 Service Unavailable"),
    ],
)
def test_meter_fails_closed_when_the_ledger_transport_fails(fault: Exception) -> None:
    store = _FaultyStore({"cap_bytes": 1_000_000, "used_bytes": 0})
    meter = proxy.Meter(cap=1_000_000, ledger=proxy.Ledger(store, "r", _clock))
    states = [meter.exhausted]
    store.load_fault = fault
    states.append(meter.exhausted)
    fault_seen = meter.ledger_fault
    # once the bucket answers again the run may continue; the fault is a state, not a verdict
    store.load_fault = None
    states.append(meter.exhausted)
    assert states == [False, True, False]
    assert fault_seen is not None
    assert fault_seen.startswith("proxy ledger could not be read: ")
    assert repr(fault) in fault_seen


def test_ledger_reports_a_save_transport_fault_as_a_ledger_error() -> None:
    store = _FaultyStore({"cap_bytes": 1_000_000, "used_bytes": 0})
    ledger = proxy.Ledger(store, "r", _clock)
    store.save_fault = ConnectionResetError(104, "Connection reset by peer")
    with pytest.raises(proxy.LedgerError, match=r"could not be saved: ConnectionReset") as info:
        ledger.charge(10)
    assert isinstance(info.value.__cause__, ConnectionResetError)


def test_ledger_rejects_bool_counts_and_malformed_runs(tmp_path: object) -> None:
    bad = f"{tmp_path}/bad.json"
    for doc in (
        {"cap_bytes": True, "used_bytes": 0},
        {"cap_bytes": 10, "used_bytes": False},
        {"cap_bytes": 10, "used_bytes": 0, "runs": []},
        {"cap_bytes": 10, "used_bytes": 0, "runs": {"r": "5"}},
        {"cap_bytes": 10, "used_bytes": 0, "runs": {"r": -1}},
        {"cap_bytes": 10, "used_bytes": 0, "runs": {"r": True}},
    ):
        pathlib.Path(bad).write_text(json.dumps(doc))
        with pytest.raises(proxy.LedgerError, match=r"integer cap_bytes|runs must map"):
            proxy.Ledger(store_mod.FileLedgerStore(bad), "r", _clock)


def test_ledger_must_exist_and_be_well_formed(tmp_path: object) -> None:
    with pytest.raises(proxy.LedgerError, match="does not exist"):
        _job(str(tmp_path), cap=10, ledger=f"{tmp_path}/missing.json")
    bad = f"{tmp_path}/bad.json"
    for body, msg in (
        ("not json", "not JSON"),
        ('{"cap_bytes": "x", "used_bytes": 0}', "integer"),
        ('{"cap_bytes": 10, "used_bytes": -1}', "integer"),
        (json.dumps({"cap_bytes": proxy.DEFAULT_BYTE_CAP + 1, "used_bytes": 0}), "owner cap"),
    ):
        with open(bad, "w") as fh:
            fh.write(body)
        with pytest.raises(proxy.LedgerError, match=msg):
            _job(str(tmp_path), cap=10, ledger=bad)


class _RacyStore:
    """A ledger store whose first save loses the race to another writer."""

    def __init__(self, fail_saves: int) -> None:
        self.doc = {"cap_bytes": 100_000, "used_bytes": 0, "runs": {}}
        self.version = 0
        self.fail_saves = fail_saves
        self.saves = 0

    def load(self) -> tuple[bytes, object] | None:
        return json.dumps(self.doc).encode(), self.version

    def save(self, data: bytes, token: object) -> bool:
        self.saves += 1
        if self.fail_saves:
            self.fail_saves -= 1
            self.doc["used_bytes"] = int(self.doc["used_bytes"]) + 7  # type: ignore[call-overload]
            self.version += 1  # somebody else wrote first
            return False
        assert token == self.version
        self.doc = json.loads(data)
        self.version += 1
        return True


def test_ledger_retries_a_lost_race_from_the_other_writers_figures() -> None:
    store = _RacyStore(fail_saves=1)
    ledger = proxy.Ledger(store, "run", lambda: "now")
    ledger.charge(10)
    assert store.saves == 2
    assert store.doc["used_bytes"] == 17  # the other writer's 7 plus our 10, not 10 twice
    assert store.doc["runs"] == {"run": 10}
    assert ledger.remaining == 100_000 - 17
    hopeless = _RacyStore(fail_saves=proxy.SAVE_ATTEMPTS)
    with pytest.raises(proxy.LedgerError, match="could not be saved"):
        proxy.Ledger(hopeless, "run", lambda: "now").charge(1)


def test_proxied_redirect_to_another_host_leaves_the_proxy(tmp_path: object) -> None:
    job, direct, via = _job(str(tmp_path), cap=proxy.DEFAULT_BYTE_CAP)
    target = "https://www.faces.ae/en/p/x.html"
    via.redirects = {f"https://{HOST}/x/p/1": target}
    job.one(Item("n-1", f"https://{HOST}/x/p/1", "en-AE", "html", {}))
    assert via.calls == [f"https://{HOST}/robots.txt", f"https://{HOST}/x/p/1"]
    assert direct.calls == ["https://www.faces.ae/robots.txt", target]
    assert job.counts["pages_ok"] == 1
    assert job.counts["redirects"] == 1
