"""The capture job against a stubbed HTTP client: states, stop rules, outputs."""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from page_capture import robots, run
from page_capture.plan import Item
from page_capture.store import Store

ROBOTS = "User-agent: *\nDisallow: /private/\nCrawl-delay: 2\n"
T0 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
CUTOFF = T0 + timedelta(hours=1)


class _Resp:
    def __init__(
        self,
        status: int,
        text: str,
        ct: str = "text/html; charset=utf-8",
        url: str = "",
        location: str = "",
    ):
        self.status_code = status
        self._text = text
        self._ct = ct
        self._url = url
        self._location = location

    @property
    def content(self) -> bytes:
        return self._text.encode()

    @property
    def text(self) -> str:
        return self._text

    @property
    def headers(self) -> Mapping[str, str]:
        h = {"content-type": self._ct}
        if self._location:
            h["location"] = self._location
        return h

    @property
    def url(self) -> str:
        return self._url


class _Cookies:
    def __init__(self) -> None:
        self.cleared = 0

    def clear(self) -> None:
        self.cleared += 1


Route = _Resp | Exception | Callable[[], _Resp]


class _Client:
    def __init__(self, routes: dict[str, Route | list[Route]]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.cookies = _Cookies()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> _Resp:
        self.calls.append((url, dict(headers or {})))
        if url not in self.routes:
            if url.endswith("/robots.txt"):
                return _Resp(200, ROBOTS, "text/plain", url)
            return _Resp(404, "nope", "text/html", url)
        route = self.routes[url]
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        if callable(route):
            return route()
        return route


def _plan(tmp_path: Path, items: list[dict[str, Any]], **extra: Any) -> str:
    doc = {"source": "t", "retailer": "shop", "version": 1, "items": items, **extra}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(doc))
    return str(path)


def _cfg(tmp_path: Path, plan_uri: str, **kw: Any) -> run.Config:
    return run.Config(
        bucket=f"file:{tmp_path / 'out'}", prefix="r", plan_uri=plan_uri, cutoff=CUTOFF, **kw
    )


def _records(tmp_path: Path, stream: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d = tmp_path / "out" / "r" / stream
    for part in sorted(d.glob("part-*.jsonl.gz")) if d.exists() else []:
        out += [json.loads(ln) for ln in gzip.decompress(part.read_bytes()).decode().splitlines()]
    return out


def _json(tmp_path: Path, name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((tmp_path / "out" / "r" / name).read_text())
    return doc


def _job(tmp_path: Path, cfg: run.Config, client: _Client, clock: Any = None) -> run.Job:
    job = run.Job(
        cfg,
        client=client,
        store=Store(cfg.bucket, cfg.prefix),
        clock=clock or (lambda: T0),
        sleep=lambda s: None,
    )
    return job


def _item(i: str, url: str, **kw: Any) -> dict[str, Any]:
    return {"id": i, "url": url, "locale": "en-AE", **kw}


def test_ok_page_and_image_are_stored(tmp_path: Path) -> None:
    page = "<html>" + "p" * 100 + "</html>"
    client = _Client(
        {
            "https://shop.example/en/p/a": _Resp(200, page, url="https://shop.example/en/p/a?x"),
            "https://img.example/a.jpg": _Resp(
                200, "JPEGDATA", "image/jpeg", "https://img.example/a.jpg"
            ),
            "https://img.example/robots.txt": _Resp(404, "", "text/html"),
        }
    )
    plan = _plan(
        tmp_path,
        [_item("a", "https://shop.example/en/p/a", images=["https://img.example/a.jpg"])],
        default_headers={"X-Plan": "1"},
    )
    job = _job(tmp_path, _cfg(tmp_path, plan, egress="test"), client)
    job.run()
    job.finish()
    pages = _records(tmp_path, "pages")
    assert len(pages) == 1
    rec = pages[0]
    assert rec["state"] == "ok"
    assert rec["status"] == 200
    assert rec["final_url"] == "https://shop.example/en/p/a?x"
    assert rec["raw"] == f"raw/{rec['sha256']}.html.gz"
    assert gzip.decompress((tmp_path / "out" / "r" / rec["raw"]).read_bytes()).decode() == page
    assert rec["bytes"] == len(page)
    images = _records(tmp_path, "images")
    assert images[0]["state"] == "ok"
    assert images[0]["object"] == f"images/{images[0]['sha256']}.jpg"
    assert (tmp_path / "out" / "r" / images[0]["object"]).read_bytes() == b"JPEGDATA"
    # robots was read first on each host, through the same client, with our UA
    urls = [u for u, _ in client.calls]
    assert urls == [
        "https://shop.example/robots.txt",
        "https://shop.example/en/p/a",
        "https://img.example/robots.txt",
        "https://img.example/a.jpg",
    ]
    page_headers = client.calls[1][1]
    assert page_headers["User-Agent"] == run.USER_AGENT
    assert page_headers["X-Plan"] == "1"
    assert page_headers["Accept-Language"].startswith("en-AE,en;q=0.9")
    assert client.calls[3][1]["Accept"].startswith("image/")
    assert client.cookies.cleared == 4
    manifest = _json(tmp_path, "manifest.json")
    assert manifest["items_total"] == 1
    assert manifest["egress"] == "test"
    assert manifest["httpx"] == httpx.__version__
    status = _json(tmp_path, "status.json")
    assert status["state"] == "finished"
    assert status["outcome"] == "complete"
    assert status["counts"]["pages_ok"] == 1
    assert status["counts"]["images_ok"] == 1
    assert status["hosts"]["shop.example"]["stopped"] is None
    robots_log = _json(tmp_path, "robots.json")
    assert robots_log["shop.example"]["state"] == "ok"
    assert robots_log["shop.example"]["crawl_delay"] == 2
    assert robots_log["img.example"]["state"] == "allow_all"
    assert _json(tmp_path, "progress.json")["counts"]["pages_ok"] == 1


def test_robots_disallowed_is_not_fetched(tmp_path: Path) -> None:
    client = _Client({})
    plan = _plan(tmp_path, [_item("a", "https://shop.example/private/a")])
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    assert _records(tmp_path, "pages")[0]["state"] == "robots_disallowed"
    assert [u for u, _ in client.calls] == ["https://shop.example/robots.txt"]


def test_robots_unavailable_refuses_the_host_but_not_others(tmp_path: Path) -> None:
    client = _Client(
        {
            "https://bad.example/robots.txt": _Resp(503, "later", "text/plain"),
            "https://html.example/robots.txt": _Resp(200, "<html>wall</html>", "text/plain"),
            "https://ok.example/p": _Resp(200, "<html>x</html>"),
        }
    )
    plan = _plan(
        tmp_path,
        [
            _item("a", "https://bad.example/p1"),
            _item("b", "https://bad.example/p2"),
            _item("c", "https://html.example/p"),
            _item("d", "https://ok.example/p"),
        ],
    )
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    states = [r["state"] for r in _records(tmp_path, "pages")]
    assert states == ["robots_unavailable", "robots_unavailable", "robots_unavailable", "ok"]
    assert len([u for u, _ in client.calls if u.startswith("https://bad.example")]) == 1
    assert _json(tmp_path, "status.json")["counts"]["robots_unavailable"] == 2


def test_403_stops_the_host_and_keeps_evidence(tmp_path: Path) -> None:
    client = _Client({"https://shop.example/a": _Resp(403, "Access Denied " + "y" * 3000)})
    plan = _plan(
        tmp_path,
        [
            _item("a", "https://shop.example/a"),
            _item("b", "https://shop.example/b"),
            _item("c", "https://other.example/c"),
        ],
    )
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    pages = _records(tmp_path, "pages")
    assert [r["state"] for r in pages] == ["blocked", "skipped_host_stopped", "http_error"]
    assert pages[0]["raw"] is not None  # the blocked body is kept
    assert "challenge" in pages[1]["reason"]
    errors = _records(tmp_path, "errors")
    assert errors[0]["url"] == "https://shop.example/a"
    assert len(errors[0]["head"]) == run.HEAD_CHARS
    status = _json(tmp_path, "status.json")
    assert status["hosts"]["shop.example"]["stopped_url"] == "https://shop.example/a"
    assert status["outcome"] == "complete"
    assert "https://shop.example/b" not in [u for u, _ in client.calls]


def test_401_without_marker_is_blocked(tmp_path: Path) -> None:
    client = _Client({"https://shop.example/a": _Resp(401, "auth")})
    plan = _plan(tmp_path, [_item("a", "https://shop.example/a")])
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    assert job.hosts["shop.example"].stopped == "blocked: http 401"


def test_two_429_stop_the_host_after_one_backoff(tmp_path: Path) -> None:
    sleeps: list[float] = []
    client = _Client(
        {
            "https://shop.example/a": _Resp(429, "slow"),
            "https://shop.example/b": _Resp(429, "slow"),
        }
    )
    plan = _plan(
        tmp_path,
        [_item(i, f"https://shop.example/{i}") for i in ("a", "b", "c")],
    )
    cfg = _cfg(tmp_path, plan)
    job = run.Job(
        cfg,
        client=client,
        store=Store(cfg.bucket, cfg.prefix),
        clock=lambda: T0,
        sleep=sleeps.append,
    )
    job.run()
    job.finish()
    assert [r["state"] for r in _records(tmp_path, "pages")] == [
        "rate_limited",
        "rate_limited",
        "skipped_host_stopped",
    ]
    assert run.BACKOFF_S in sleeps
    assert job.hosts["shop.example"].stopped == "2 consecutive 429"


def test_429_streak_resets_on_success(tmp_path: Path) -> None:
    client = _Client(
        {
            "https://shop.example/a": _Resp(429, "slow"),
            "https://shop.example/b": _Resp(200, "<html>ok</html>"),
            "https://shop.example/c": _Resp(429, "slow"),
        }
    )
    plan = _plan(tmp_path, [_item(i, f"https://shop.example/{i}") for i in ("a", "b", "c")])
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    assert job.hosts["shop.example"].stopped is None


def test_ten_transport_errors_stop_the_host(tmp_path: Path) -> None:
    routes: dict[str, Any] = {
        f"https://shop.example/{i}": httpx.ConnectTimeout("timed out") for i in range(10)
    }
    client = _Client(routes)
    plan = _plan(tmp_path, [_item(str(i), f"https://shop.example/{i}") for i in range(12)])
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    states = [r["state"] for r in _records(tmp_path, "pages")]
    assert states == ["transport_error"] * 10 + ["skipped_host_stopped"] * 2
    assert job.counts["transport_error"] == 10
    assert "10 consecutive transport errors" in str(job.hosts["shop.example"].stopped)


def test_cutoff_skips_the_rest(tmp_path: Path) -> None:
    ticks = iter([T0, T0, T0, T0, CUTOFF, CUTOFF, CUTOFF, CUTOFF, CUTOFF, CUTOFF])
    client = _Client({"https://shop.example/a": _Resp(200, "<html>a</html>")})
    plan = _plan(
        tmp_path,
        [
            _item("a", "https://shop.example/a", images=["https://shop.example/i.jpg"]),
            _item("b", "https://shop.example/b", images=["https://shop.example/j.jpg"]),
        ],
    )
    job = _job(tmp_path, _cfg(tmp_path, plan), client, clock=lambda: next(ticks))
    job.run()
    job.finish()
    assert [r["state"] for r in _records(tmp_path, "pages")] == ["ok", "skipped_cutoff"]
    images = _records(tmp_path, "images")
    assert images[-1]["state"] == "skipped_cutoff"
    assert _json(tmp_path, "status.json")["outcome"] == "cutoff"


def test_shard_limit_and_images_off(tmp_path: Path) -> None:
    client = _Client({f"https://shop.example/{i}": _Resp(200, "<html>x</html>") for i in range(6)})
    plan = _plan(
        tmp_path,
        [
            _item(str(i), f"https://shop.example/{i}", images=["https://shop.example/i.jpg"])
            for i in range(6)
        ],
    )
    cfg = run.config_from_env(
        {
            "BUCKET": f"file:{tmp_path / 'out'}",
            "PREFIX": "r",
            "PLAN": plan,
            "CUTOFF": CUTOFF.isoformat(),
            "CLOUD_RUN_TASK_INDEX": "1",
            "CLOUD_RUN_TASK_COUNT": "2",
            "LIMIT": "2",
            "IMAGES": "0",
            "PACE": "2",
            "IMAGE_PACE": "0.5",
            "EGRESS": "cloud-run",
            "GIT_SHA": "abc",
        }
    )
    assert cfg.pace_s == 2.0
    assert cfg.git_sha == "abc"
    job = _job(tmp_path, cfg, client)
    job.run()
    job.finish()
    assert [r["id"] for r in _records(tmp_path, "pages")] == ["1", "3"]
    assert _records(tmp_path, "images") == []
    manifest = _json(tmp_path, "manifest.t1.json")  # task 1 of 2 writes its own summaries
    assert manifest["shard"] == {"index": 1, "count": 2}
    assert manifest["items_shard"] == 2


def test_image_dedupe_and_failed_image_bodies(tmp_path: Path) -> None:
    client = _Client(
        {
            "https://shop.example/a": _Resp(200, "<html>a</html>"),
            "https://shop.example/b": _Resp(200, "<html>b</html>"),
            "https://shop.example/i.webp": _Resp(200, "WEBP", "image/webp"),
            "https://shop.example/gone.png": _Resp(404, "missing", "text/html"),
            "https://shop.example/empty.png": _Resp(500, "", "text/plain"),
        }
    )
    plan = _plan(
        tmp_path,
        [
            _item(
                "a",
                "https://shop.example/a",
                images=["https://shop.example/i.webp", "https://shop.example/gone.png"],
            ),
            _item(
                "b",
                "https://shop.example/b",
                images=["https://shop.example/i.webp", "https://shop.example/empty.png"],
            ),
        ],
    )
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    images = _records(tmp_path, "images")
    assert [r["state"] for r in images] == ["ok", "http_error", "duplicate", "http_error"]
    assert images[0]["object"].endswith(".webp")
    assert images[1]["object"].startswith("raw/")
    assert images[2]["object"] == images[0]["object"]
    assert images[3]["object"] is None
    assert [u for u, _ in client.calls].count("https://shop.example/i.webp") == 1


def test_xml_200_is_not_marker_scanned_but_500_is_http_error(tmp_path: Path) -> None:
    client = _Client(
        {
            "https://shop.example/s.xml": _Resp(200, "<urlset>captcha</urlset>", "application/xml"),
            "https://shop.example/j": _Resp(500, '{"error":"x"}', "application/json"),
        }
    )
    plan = _plan(
        tmp_path,
        [
            _item("x", "https://shop.example/s.xml", kind="xml"),
            _item("j", "https://shop.example/j", kind="json"),
        ],
    )
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    pages = _records(tmp_path, "pages")
    assert pages[0]["state"] == "ok"
    assert pages[0]["raw"].endswith(".xml.gz")
    assert pages[1]["state"] == "http_error"
    assert pages[1]["raw"].endswith(".json.gz")


def test_blocked_robots_fetch_makes_robots_unavailable(tmp_path: Path) -> None:
    client = _Client({"https://shop.example/robots.txt": _Resp(403, "Access Denied", "text/plain")})
    plan = _plan(tmp_path, [_item("a", "https://shop.example/a")])
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    rec = _records(tmp_path, "pages")[0]
    assert rec["state"] == "robots_unavailable"
    assert "blocked" in rec["reason"]
    assert _json(tmp_path, "robots.json")["shop.example"]["state"] == "unavailable"


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("PACE", "0.5", "PACE"),
        ("IMAGE_PACE", "0.1", "IMAGE_PACE"),
        ("CUTOFF", "2026-10-02T10:00:00", "timezone"),
        ("CLOUD_RUN_TASK_INDEX", "3", "task index"),
        ("CLOUD_RUN_TASK_COUNT", "0", "task index"),
    ],
)
def test_config_validation(key: str, value: str, match: str) -> None:
    env = {"BUCKET": "b", "PREFIX": "p", "PLAN": "gs://b/plan.json", "CUTOFF": CUTOFF.isoformat()}
    env[key] = value
    with pytest.raises(ValueError, match=match):
        run.config_from_env(env)


def test_headers_and_extensions() -> None:
    h = run.headers("UA", "ar-SA", "html", {"X": "1"})
    assert h["Accept-Language"] == "ar-SA,ar;q=0.9,en;q=0.8"
    assert h["X"] == "1"
    assert run.headers("UA", "en-AE", "json", {})["Accept"].startswith("application/json")
    assert run.raw_ext("html", "application/json") == "json"
    assert run.raw_ext("html", "text/xml") == "xml"
    assert run.raw_ext("json", "text/html") == "html"
    assert run.raw_ext("json", "") == "json"
    assert run.raw_ext("robots", "text/plain") == "txt"
    assert run.image_ext("image/jpeg; charset=binary") == "jpg"
    assert run.image_ext("application/octet-stream") == "bin"


def test_pace_waits_for_the_larger_of_pace_and_crawl_delay(tmp_path: Path) -> None:
    sleeps: list[float] = []
    cfg = _cfg(tmp_path, "plan.json", pace_s=1.0)
    job = run.Job(cfg, client=_Client({}), store=Store(cfg.bucket, "r"), sleep=sleeps.append)
    host = job.host_for("https://shop.example/x")
    host.last = time.monotonic()
    host.robots = robots.Robots(robots.OK, (), crawl_delay=5.0)
    job.pace(host, 1.0)
    assert 5.0 <= sleeps[0] <= 8.0


def test_main_sigterm_and_error_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(tmp_path, [_item("a", "https://shop.example/a")])
    env = {
        "BUCKET": f"file:{tmp_path / 'out'}",
        "PREFIX": "r",
        "PLAN": plan,
        "CUTOFF": CUTOFF.isoformat(),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(run.Job, "run", lambda self: (_ for _ in ()).throw(run.Stop("sigterm")))
    assert run.main() == 0
    assert _json(tmp_path, "status.json")["outcome"] == "cutoff"
    assert _json(tmp_path, "status.json")["stopped"] == "sigterm"

    def boom(self: run.Job) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(run.Job, "run", boom)
    assert run.main() == 1
    status = _json(tmp_path, "status.json")
    assert status["outcome"] == "error"
    assert "disk full" in status["stopped"]
    with pytest.raises(run.Stop):
        run._sigterm(15, None)


def _redirect(to: str) -> _Resp:
    return _Resp(302, "", "text/html", location=to)


def test_redirect_to_a_host_whose_robots_forbids_is_not_fetched(tmp_path: Path) -> None:
    """Reviewer's reproduction: a 302 to a host with ``Disallow: /`` must not be followed."""
    src, dst = "https://a.example/p/1", "https://b.example/p/1"
    client = _Client(
        {
            src: _redirect(dst),
            "https://b.example/robots.txt": _Resp(
                200, "User-agent: *\nDisallow: /\n", "text/plain"
            ),
            dst: _Resp(200, "<html>should never be seen</html>", url=dst),
        }
    )
    job = _job(tmp_path, _cfg(tmp_path, _plan(tmp_path, [_item("1", src)])), client)
    job.run()
    job.finish()
    urls = [u for u, _ in client.calls]
    assert urls == ["https://a.example/robots.txt", src, "https://b.example/robots.txt"]
    (rec,) = _records(tmp_path, "pages")
    assert rec["state"] == run.ROBOTS_DISALLOWED
    assert rec["final_url"] == dst
    assert rec["redirects"] == 1
    assert "redirect target" in rec["reason"]
    assert job.counts["redirects"] == 1
    assert job.counts["http_302"] == 1
    assert "pages_ok" not in job.counts


def test_redirect_to_unreadable_robots_or_stopped_host_is_refused(tmp_path: Path) -> None:
    src1, src2 = "https://a.example/p/1", "https://a.example/p/2"
    dst = "https://c.example/p/1"
    client = _Client(
        {
            src1: _redirect(dst),
            src2: _redirect(dst),
            "https://c.example/robots.txt": _Resp(500, "boom", "text/plain"),
            dst: _Resp(200, "<html>never</html>", url=dst),
        }
    )
    job = _job(
        tmp_path, _cfg(tmp_path, _plan(tmp_path, [_item("1", src1), _item("2", src2)])), client
    )
    job.run()
    job.finish()
    one, two = sorted(_records(tmp_path, "pages"), key=lambda r: str(r["id"]))
    assert one["state"] == run.ROBOTS_UNAVAILABLE
    assert two["state"] == run.ROBOTS_UNAVAILABLE  # robots read once; still refused
    assert dst not in [u for u, _ in client.calls]
    # a redirect to a host already stopped is skipped without a request
    job.hosts["c.example"].stopped = "blocked: challenge"
    job.one(Item("3", src1, "en-AE", "html", {}, (), {}))
    rec = job.parts.buf["pages"][-1]
    assert rec["state"] == run.SKIPPED_HOST_STOPPED
    assert "stopped host c.example" in rec["reason"]


def test_same_host_redirect_is_followed_and_robots_checked_on_the_new_path(tmp_path: Path) -> None:
    src, dst, private = (
        "https://a.example/p/1",
        "https://a.example/p/1-final",
        "https://a.example/private/x",
    )
    client = _Client(
        {
            src: _redirect("/p/1-final"),  # relative Location
            dst: _Resp(200, "<html>final</html>", url=dst),
            "https://a.example/p/2": _redirect(private),
            private: _Resp(200, "<html>never</html>", url=private),
        }
    )
    plan = _plan(tmp_path, [_item("1", src), _item("2", "https://a.example/p/2")])
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    one, two = sorted(_records(tmp_path, "pages"), key=lambda r: str(r["id"]))
    assert one["state"] == run.OK
    assert one["final_url"] == dst
    assert one["redirects"] == 1
    assert two["state"] == run.ROBOTS_DISALLOWED  # ROBOTS has Disallow: /private/
    assert private not in [u for u, _ in client.calls]


def test_redirect_limit_is_pinned() -> None:
    """Five hops is the RFC 9309 floor for robots.txt and the ceiling for pages; keep it there."""
    assert run.MAX_REDIRECTS == 5


def test_redirect_loop_and_missing_location_are_http_errors(tmp_path: Path) -> None:
    loop_a, loop_b = "https://a.example/l/a", "https://a.example/l/b"
    bare = "https://a.example/bare"
    client = _Client({loop_a: _redirect(loop_b), loop_b: _redirect(loop_a), bare: _Resp(301, "")})
    plan = _plan(tmp_path, [_item("1", loop_a), _item("2", bare)])
    job = _job(tmp_path, _cfg(tmp_path, plan), client)
    job.run()
    job.finish()
    one, two = sorted(_records(tmp_path, "pages"), key=lambda r: str(r["id"]))
    assert one["state"] == run.HTTP_ERROR
    assert one["redirects"] == run.MAX_REDIRECTS + 1
    assert "redirects" in one["reason"]
    assert two["state"] == run.HTTP_ERROR
    assert two["reason"] == "redirect without Location"
    assert two["status"] == 301


def test_robots_txt_redirect_is_followed(tmp_path: Path) -> None:
    client = _Client(
        {
            "https://a.example/robots.txt": _redirect("https://static.a.example/robots.txt"),
            "https://static.a.example/robots.txt": _Resp(
                200, "User-agent: *\nDisallow: /p/\n", "text/plain"
            ),
        }
    )
    job = _job(
        tmp_path, _cfg(tmp_path, _plan(tmp_path, [_item("1", "https://a.example/p/1")])), client
    )
    job.run()
    job.finish()
    (rec,) = _records(tmp_path, "pages")
    assert rec["state"] == run.ROBOTS_DISALLOWED
    assert "https://a.example/p/1" not in [u for u, _ in client.calls]
