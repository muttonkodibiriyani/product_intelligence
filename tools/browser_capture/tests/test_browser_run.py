"""The browser job against a fake session: states, stop rules, evidence, outputs.

No real retailer page is ever used here; every body is synthetic.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from browser_capture import policy, run
from browser_capture.session import Answer, Engine, Hop, TransportError, Visit
from page_capture.store import Store

SHOP = "https://www.shop.example"
ROBOTS = "User-agent: *\nDisallow: /private/\nCrawl-delay: 2\n"
T0 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
CUTOFF = T0 + timedelta(hours=1)
ENGINE = Engine(
    "chromium", "140.0.0.0", "1.63.0", "Mozilla/5.0 (X11; Linux x86_64) Test", (1280, 720)
)
PAGE = "<html><head><title>Lip Pencil</title></head><body><h1>Lip Pencil</h1>" + "x" * 70_000
CHALLENGE = "<html><title>Robot Check</title><body>validateCaptcha</body></html>"


def answer(status: int, body: str, ct: str = "text/plain", location: str = "") -> Answer:
    headers = {"content-type": ct}
    if location:
        headers["location"] = location
    return Answer(status, headers, body.encode(), "")


def visit(  # noqa: PLR0913
    url: str,
    *,
    status: int | None = 200,
    server: str = PAGE,
    rendered: str | None = None,
    hops: tuple[Hop, ...] = (),
    final_url: str | None = None,
    shot: bytes | None = b"\x89PNG",
    idle_timeout: bool = False,
    navigated_away: bool = False,
) -> Visit:
    return Visit(
        status=status,
        final_url=final_url or url,
        headers={"content-type": "text/html"},
        server_body=server.encode(),
        rendered=rendered if rendered is not None else server,
        title="Lip Pencil",
        hops=hops,
        screenshot=shot,
        idle_timeout=idle_timeout,
        nav_ms=120,
        settle_ms=800,
        document_url=final_url or url,
        documents=(Hop(final_url or url, status or 0),),
        navigated_away=navigated_away,
        gate_counts={"documents": 1 + len(hops), "render_script": 3, "third_party": 2},
        hosts_seen={"www.shop.example": 1, "cdn.vendor.test": 2},
    )


class FakeSession:
    """Scripted answers and visits keyed by URL; records every call in order."""

    def __init__(
        self,
        answers: Mapping[str, Answer | Exception],
        visits: Mapping[str, Visit | Exception | Callable[[policy.Gate], Visit | Exception]],
        engine: Engine = ENGINE,
    ) -> None:
        self.answers = answers
        self.visits = visits
        self._engine = engine
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    @property
    def engine(self) -> Engine:
        return self._engine

    def answer(self, url: str, *, timeout_s: float) -> Answer:
        self.calls.append(("answer", url))
        got = self.answers.get(url)
        if got is None:
            raise TransportError(f"unscripted {url}")
        if isinstance(got, Exception):
            raise got
        return got

    def visit(  # noqa: PLR0913
        self,
        url: str,
        gate: policy.Gate,
        *,
        nav_timeout_s: float,
        idle_timeout_s: float,
        screenshot: bool,
        pace: Callable[[str], None],
    ) -> Visit:
        self.calls.append(("visit", url))
        self.pace = pace
        got = self.visits.get(url)
        if callable(got):
            got = got(gate)
        if got is None:
            raise TransportError(f"unscripted {url}")
        if isinstance(got, Exception):
            raise got
        return got

    def close(self) -> None:
        self.closed = True


def plan_file(tmp_path: Path, urls: list[str], retailer: str = "shop") -> str:
    items = [
        {
            "id": f"{retailer}-{i}",
            "url": u,
            "locale": "en-AE",
            "kind": "html",
            "ref": {"retailer": retailer, "source": f"{retailer}_ae"},
            "images": [],
        }
        for i, u in enumerate(urls)
    ]
    doc = {"source": f"{retailer}_ae", "retailer": retailer, "version": 1, "items": items}
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(doc))
    return str(path)


def make_job(  # noqa: PLR0913
    tmp_path: Path,
    session: FakeSession,
    urls: list[str],
    *,
    hosts: tuple[str, ...] = (),
    sub: str = policy.RECORD,
    sub_hosts: tuple[str, ...] = (),
    clock_steps: float = 0.0,
) -> tuple[run.Job, list[float]]:
    cfg = run.Config(
        bucket=f"file:{tmp_path / 'out'}",
        prefix="shop/browser-r1",
        plan_uri=plan_file(tmp_path, urls),
        cutoff=CUTOFF,
        hosts=hosts,
        subresources=sub,
        subresource_hosts=sub_hosts,
        git_sha="abc123",
    )
    ticks = {"n": 0}

    def clock() -> datetime:
        ticks["n"] += 1
        return T0 + timedelta(seconds=clock_steps * ticks["n"])

    sleeps: list[float] = []
    mono = {"t": 1000.0}

    def now() -> float:
        return mono["t"]

    def sleep(s: float) -> None:
        sleeps.append(s)
        mono["t"] += s

    job = run.Job(cfg, session, clock=clock, sleep=sleep, rand=lambda: 0.5, now=now)
    return job, sleeps


def read_parts(tmp_path: Path, stream: str) -> list[dict[str, Any]]:
    base = tmp_path / "out" / "shop" / "browser-r1" / stream
    rows: list[dict[str, Any]] = []
    for part in sorted(base.glob("part-*.jsonl.gz")) if base.exists() else []:
        rows += [
            json.loads(line) for line in gzip.decompress(part.read_bytes()).decode().splitlines()
        ]
    return rows


def read_json(tmp_path: Path, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((tmp_path / "out" / "shop" / "browser-r1" / name).read_text())
    return data


# ------------------------------------------------------------------------- config


def test_config_from_env_reads_every_knob_and_refuses_bad_values() -> None:
    env = {
        "BUCKET": "b",
        "PREFIX": "p",
        "PLAN": "gs://b/plan.json",
        "CUTOFF": "2026-10-02T09:00:00+00:00",
        "HOSTS": "www.shop.example, Cdn.Shop.Example",
        "SUBRESOURCES": "cdn.vendor.test,api.vendor.test",
        "SCREENSHOT": "0",
        "NAV_TIMEOUT": "12",
        "IDLE_TIMEOUT": "7",
        "JITTER": "0.25",
        "LIMIT": "3",
    }
    cfg = run.config_from_env(env)
    assert cfg.hosts == ("www.shop.example", "cdn.shop.example")
    assert cfg.subresources == policy.ENFORCE_HOSTS
    assert cfg.subresource_hosts == ("cdn.vendor.test", "api.vendor.test")
    assert (cfg.screenshot, cfg.nav_timeout_s, cfg.idle_timeout_s) == (False, 12.0, 7.0)
    assert (cfg.jitter_s, cfg.limit, cfg.pace_s) == (0.25, 3, 1.0)
    assert run.config_from_env({**env, "SUBRESOURCES": "record"}).subresources == policy.RECORD
    for bad, msg in [
        ({"PACE": "0.5"}, "PACE"),
        ({"JITTER": "-1"}, "JITTER"),
        ({"CUTOFF": "2026-10-02T09:00:00"}, "timezone"),
        ({"SUBRESOURCES": " , "}, "SUBRESOURCES"),
        ({"CLOUD_RUN_TASK_INDEX": "2", "CLOUD_RUN_TASK_COUNT": "2"}, "task index"),
    ]:
        with pytest.raises(ValueError, match=msg):
            run.config_from_env({**env, **bad})


# ----------------------------------------------------------------------- happy path


def test_the_manifest_webrtc_line_follows_the_init_script_the_engine_installs(
    tmp_path: Path,
) -> None:
    url = f"{SHOP}/p/lip-pencil"
    shut = replace(ENGINE, init_script=policy.NO_WEBRTC)
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: visit(url)}, shut)
    job, _ = make_job(tmp_path, session, [url])
    job.run()
    job.finish()
    browser = read_json(tmp_path, "manifest.json")["browser"]
    assert browser["init_script"] == policy.NO_WEBRTC
    assert browser["webrtc"] == "removed from every frame by the init script"
    # a script that leaves one constructor behind is recorded as such, naming it
    partial = replace(ENGINE, init_script="delete window.RTCPeerConnection;")
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: visit(url)}, partial)
    job, _ = make_job(tmp_path / "partial", session, [url])
    job.run()
    job.finish()
    browser = read_json(tmp_path / "partial", "manifest.json")["browser"]
    assert browser["webrtc"] == (
        "left in place: init script does not delete webkitRTCPeerConnection, RTCDataChannel"
    )


def test_an_allowed_page_is_visited_once_with_its_evidence_stored(tmp_path: Path) -> None:
    url = f"{SHOP}/p/lip-pencil"
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: visit(url)})
    job, sleeps = make_job(tmp_path, session, [url])
    job.run()
    job.finish()
    assert session.calls == [("answer", f"{SHOP}/robots.txt"), ("visit", url)]
    rows = read_parts(tmp_path, "pages")
    assert len(rows) == 1
    rec = rows[0]
    assert rec["state"] == "ok"
    assert rec["status"] == 200
    assert rec["final_url"] == url
    assert rec["redirects"] == 0
    assert rec["title"] == "Lip Pencil"
    assert rec["requests"] == {"documents": 1, "render_script": 3, "third_party": 2}
    assert rec["hosts_seen"] == {"www.shop.example": 1, "cdn.vendor.test": 2}
    out = tmp_path / "out" / "shop" / "browser-r1"
    assert gzip.decompress((out / rec["raw_server"]).read_bytes()).decode() == PAGE
    assert gzip.decompress((out / rec["raw_rendered"]).read_bytes()).decode() == PAGE
    assert (out / rec["shot"]).read_bytes() == b"\x89PNG"
    assert rec["raw_server"].endswith(".server.html.gz")
    assert rec["shot"].startswith("shots/")
    assert rec["shot"].endswith(".png")
    status = read_json(tmp_path, "status.json")
    assert status["outcome"] == "complete"
    assert status["hosts_blocked"] == {}
    assert status["counts"]["pages_ok"] == 1
    assert status["counts"]["robots_ok"] == 1
    manifest = read_json(tmp_path, "manifest.json")
    assert manifest["browser"] == {
        "engine": "chromium",
        "version": "140.0.0.0",
        "playwright": "1.63.0",
        "user_agent": ENGINE.user_agent,
        "viewport": [1280, 720],
        "headless": True,
        "stealth": False,
        "proxy": None,
        "launch_args": [],
        "policy_args": [],
        "init_script": "",
        "webrtc": (
            "left in place: init script does not delete "
            "RTCPeerConnection, webkitRTCPeerConnection, RTCDataChannel"
        ),
        "fresh_browser_per_page": True,
        "service_workers": "block",
        "websockets": "refused",
        "popups": "refused and closed",
        "documents": "fetched with redirects not followed; each hop is a new navigation",
    }
    assert manifest["hosts"] == ["www.shop.example"]  # derived from the plan
    assert manifest["subresources"] == {"policy": "record", "hosts": []}
    robots_log = read_json(tmp_path, "robots.json")["www.shop.example"]
    assert (robots_log["state"], robots_log["crawl_delay"], robots_log["rules"]) == ("ok", 2.0, 1)
    # robots.txt then the page on the same host: paced by max(pace, Crawl-delay) + jitter
    assert sleeps == [2.25]


def test_pacing_waits_between_navigations_on_one_host_with_jitter(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/{i}" for i in range(3)]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, "User-agent: *\nAllow: /\n")},
        {u: visit(u) for u in urls},
    )
    job, sleeps = make_job(tmp_path, session, urls)
    job.run()
    assert sleeps == [1.25, 1.25, 1.25]  # pace 1.0 + 0.5 * jitter 0.5, three gaps


# ------------------------------------------------------------------------ robots


def test_a_wall_on_robots_txt_stops_the_host_before_any_page_is_opened(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/1", f"{SHOP}/p/2"]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(403, "<html><body>Access Denied</body></html>", "text/html")},
        {u: visit(u) for u in urls},
    )
    job, _ = make_job(tmp_path, session, urls)
    job.run()
    job.finish()
    assert session.calls == [("answer", f"{SHOP}/robots.txt")]
    rows = read_parts(tmp_path, "pages")
    # robots are read for every host before the first page, so the wall stops the host up front
    assert [r["state"] for r in rows] == ["skipped_host_stopped", "skipped_host_stopped"]
    assert "challenge on robots.txt" in rows[0]["reason"]
    status = read_json(tmp_path, "status.json")
    assert status["hosts_blocked"] == {"www.shop.example": rows[0]["reason"]}
    assert status["counts"]["robots_unavailable"] == 1
    assert status["counts"]["block_challenge"] == 1
    assert status["counts"]["hosts_stopped"] == 1


def test_robots_disallow_and_missing_robots_are_told_apart(tmp_path: Path) -> None:
    urls = [f"{SHOP}/private/1", f"{SHOP}/p/1"]
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {urls[1]: visit(urls[1])})
    job, _ = make_job(tmp_path, session, urls)
    job.run()
    rows = read_parts(tmp_path, "pages") + list(job.parts.buf.get("pages", []))
    assert [r["state"] for r in rows] == ["robots_disallowed", "ok"]
    assert ("visit", urls[0]) not in session.calls

    other = "https://www.other.example"
    session2 = FakeSession(
        {f"{other}/robots.txt": answer(404, "")}, {f"{other}/p": visit(f"{other}/p")}
    )
    job2, _ = make_job(tmp_path / "b", session2, [f"{other}/p"])
    job2.run()
    assert [r["state"] for r in job2.parts.buf["pages"]] == ["ok"]
    assert job2.robots_log["www.other.example"]["state"] == "allow_all"

    session3 = FakeSession({f"{other}/robots.txt": TransportError("dns")}, {})
    job3, _ = make_job(tmp_path / "c", session3, [f"{other}/p"])
    job3.run()
    assert [r["state"] for r in job3.parts.buf["pages"]] == ["robots_unavailable"]
    assert job3.parts.buf["pages"][0]["reason"] == "transport error"


@pytest.mark.parametrize(
    ("location", "allowed"),
    [
        ("https://www.shop.example/robots-v2.txt", True),
        ("http://www.shop.example/robots.txt", False),
        ("https://10.0.0.1/robots.txt", False),
        ("https://cdn.shop.example/robots.txt", False),
        ("https://www.shop.example:444/robots.txt", False),
    ],
)
def test_robots_hops_stay_on_their_own_https_host_or_fail_closed(
    tmp_path: Path, location: str, allowed: bool
) -> None:
    url = f"{SHOP}/p/1"
    answers = {
        f"{SHOP}/robots.txt": answer(301, "", location=location),
        location: answer(200, "User-agent: *\nAllow: /\n"),
    }
    session = FakeSession(answers, {url: visit(url)})
    job, _ = make_job(tmp_path, session, [url])
    job.run()
    states = [r["state"] for r in job.parts.buf["pages"]]
    answered = [u for kind, u in session.calls if kind == "answer"]
    if allowed:
        assert answered == [f"{SHOP}/robots.txt", location]
        assert states == ["ok"]
    else:
        assert answered == [f"{SHOP}/robots.txt"]  # the off-host target is never requested
        assert states == ["robots_unavailable"]
        assert "robots.txt redirect to" in job.parts.buf["pages"][0]["reason"]
    assert job.robots_log["www.shop.example"]["redirects"] == 1


# -------------------------------------------------------------------- host gating


def test_a_plan_url_off_the_storefront_is_never_opened(tmp_path: Path) -> None:
    urls = ["http://www.shop.example/p/1", "https://evil.test/p/2", f"{SHOP}/p/3"]
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {urls[2]: visit(urls[2])})
    job, _ = make_job(tmp_path, session, urls, hosts=("www.shop.example",))
    job.run()
    assert session.calls == [("answer", f"{SHOP}/robots.txt"), ("visit", urls[2])]
    rows = job.parts.buf["pages"]
    assert [r["state"] for r in rows] == ["hop_host_refused", "hop_host_refused", "ok"]
    assert "not https" in rows[0]["reason"]
    assert "not in the allowed set" in rows[1]["reason"]


def test_a_document_redirect_off_the_storefront_is_aborted_by_the_gate_and_stops_the_host(
    tmp_path: Path,
) -> None:
    urls = [f"{SHOP}/p/1", f"{SHOP}/p/2"]

    def redirected(gate: policy.Gate) -> Exception:
        # what the adapter does: the browser asks for the hop, the gate refuses, goto fails
        assert gate.decide(urls[0], "document", True).allow
        assert not gate.decide("http://169.254.169.254/latest/meta-data/", "document", True).allow
        return TransportError("net::ERR_BLOCKED_BY_CLIENT")

    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {urls[0]: redirected})
    job, _ = make_job(tmp_path, session, urls)
    job.run()
    job.finish()
    rows = read_parts(tmp_path, "pages")
    assert [r["state"] for r in rows] == ["hop_host_refused", "skipped_host_stopped"]
    assert rows[0]["final_url"] == "http://169.254.169.254/latest/meta-data/"
    assert rows[0]["requests"] == {"documents": 1, "refused_document": 1}
    assert "raw_server" not in rows[0]
    status = read_json(tmp_path, "status.json")
    assert status["counts"]["hop_host_refused"] == 1
    assert "redirect off the storefront" in status["hosts_blocked"]["www.shop.example"]


def test_a_hop_the_gate_missed_is_still_refused_after_the_fact_and_nothing_is_kept(
    tmp_path: Path,
) -> None:
    url = f"{SHOP}/p/1"
    got = visit(
        url,
        hops=(Hop(url, 302), Hop("https://cdn.shop.example/p/1", 301)),
        final_url="https://www.shop.example/p/1-final",
    )
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: got})
    job, _ = make_job(tmp_path, session, [url])
    job.run()
    rec = job.parts.buf["pages"][0]
    assert rec["state"] == "hop_host_refused"
    assert rec["reason"].startswith("https://cdn.shop.example/p/1: host")
    assert rec["hops"] == [
        {"url": url, "status": 302},
        {"url": "https://cdn.shop.example/p/1", "status": 301},
    ]
    assert "raw_server" not in rec
    assert "shot" not in rec
    raw = tmp_path / "out" / "shop" / "browser-r1" / "raw"
    assert [p.name for p in raw.iterdir() if ".html" in p.name or ".png" in p.name] == []
    assert job.hosts["www.shop.example"].stopped is not None


def test_a_redirect_that_stays_on_the_storefront_is_kept_with_its_chain(tmp_path: Path) -> None:
    url = f"{SHOP}/p/old"
    got = visit(url, hops=(Hop(url, 301),), final_url=f"{SHOP}/p/new")
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: got})
    job, _ = make_job(tmp_path, session, [url])
    job.run()
    rec = job.parts.buf["pages"][0]
    assert (rec["state"], rec["redirects"], rec["final_url"]) == ("ok", 1, f"{SHOP}/p/new")


def test_robots_are_read_for_every_allowed_host_before_the_first_page(tmp_path: Path) -> None:
    url = f"{SHOP}/p/1"
    session = FakeSession(
        {
            f"{SHOP}/robots.txt": answer(200, ROBOTS),
            "https://m.shop.example/robots.txt": answer(404, ""),
        },
        {url: visit(url)},
    )
    job, _ = make_job(tmp_path, session, [url], hosts=("www.shop.example", "m.shop.example"))
    job.run()
    reads = [u for kind, u in session.calls if kind == "answer"]
    assert reads == ["https://m.shop.example/robots.txt", f"{SHOP}/robots.txt"]
    assert session.calls.index(("visit", url)) > 1
    assert job.document_check("https://m.shop.example/p/9") is None  # 404 robots: allow all
    assert job.document_check(f"{SHOP}/private/x") == "robots disallowed"
    assert job.document_check(f"{SHOP}/p/2") is None


def test_the_document_check_refuses_a_stopped_or_unread_host(tmp_path: Path) -> None:
    url = f"{SHOP}/p/1"
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: visit(url)})
    job, _ = make_job(tmp_path, session, [url])
    assert job.document_check(url) == "robots.txt not read for this host"  # before load()
    job.load()
    assert job.document_check(url) is None
    job.stop_host(job.hosts["www.shop.example"], "test", url)
    assert job.document_check(url) == "host stopped: test"


def test_a_redirect_the_robots_rules_refuse_is_an_explicit_state_and_keeps_the_host(
    tmp_path: Path,
) -> None:
    urls = [f"{SHOP}/p/1", f"{SHOP}/p/2"]

    def redirected(gate: policy.Gate) -> Exception:
        assert gate.decide(urls[0], "document", True).allow
        assert not gate.decide(f"{SHOP}/private/x", "document", True).allow
        return TransportError("document refused")

    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {urls[0]: redirected, urls[1]: visit(urls[1])}
    )
    job, _ = make_job(tmp_path, session, urls)
    job.run()
    rows = job.parts.buf["pages"]
    assert [r["state"] for r in rows] == ["robots_disallowed", "ok"]
    assert rows[0]["reason"] == f"{SHOP}/private/x: robots disallowed"
    assert rows[0]["final_url"] == f"{SHOP}/private/x"
    assert job.hosts["www.shop.example"].stopped is None


def test_a_script_navigation_is_kept_but_flagged_as_another_document(tmp_path: Path) -> None:
    url = f"{SHOP}/p/1"
    got = visit(url, final_url=f"{SHOP}/p/1?moved", navigated_away=True)
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: got})
    job, _ = make_job(tmp_path, session, [url])
    job.run()
    rec = job.parts.buf["pages"][0]
    assert rec["state"] == "navigated_away"
    assert rec["reason"] == f"script moved to {SHOP}/p/1?moved"
    assert rec["navigated_away"] is True
    assert rec["document_url"] == f"{SHOP}/p/1?moved"
    assert rec["documents"] == [{"url": f"{SHOP}/p/1?moved", "status": 200}]
    assert "raw_server" in rec  # the evidence is kept, the state says what it is


def test_the_adapter_paces_hops_through_the_job(tmp_path: Path) -> None:
    url = f"{SHOP}/p/1"
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: visit(url)})
    job, sleeps = make_job(tmp_path, session, [url])
    job.run()
    before = len(sleeps)
    session.pace(f"{SHOP}/p/hop")  # what pw.py calls before re-navigating to a hop
    assert len(sleeps) == before + 1


# ------------------------------------------------------------------- blocks, errors


def test_a_challenge_page_is_recorded_with_evidence_and_stops_the_host(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/1", f"{SHOP}/p/2"]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, ROBOTS)},
        {urls[0]: visit(urls[0], status=200, server=CHALLENGE)},
    )
    job, _ = make_job(tmp_path, session, urls)
    job.run()
    job.finish()
    rows = read_parts(tmp_path, "pages")
    assert [r["state"] for r in rows] == ["blocked", "skipped_host_stopped"]
    assert "validateCaptcha" in rows[0]["reason"]
    assert rows[0]["raw_server"]  # the evidence is kept
    assert rows[0]["shot"]
    errors = read_parts(tmp_path, "errors")
    assert errors[0]["block"] == "challenge"
    assert errors[0]["title"] == "Lip Pencil"
    assert "validateCaptcha" in errors[0]["head"]
    status = read_json(tmp_path, "status.json")
    assert status["counts"]["block_challenge"] == 1
    assert status["hosts_blocked"]["www.shop.example"].startswith("challenge:")
    assert ("visit", urls[1]) not in session.calls


def test_a_challenge_that_only_shows_in_the_rendered_dom_still_counts(tmp_path: Path) -> None:
    url = f"{SHOP}/p/1"
    got = visit(url, server="<html><body>loading</body></html>", rendered=CHALLENGE)
    session = FakeSession({f"{SHOP}/robots.txt": answer(200, ROBOTS)}, {url: got})
    job, _ = make_job(tmp_path, session, [url])
    job.run()
    assert job.parts.buf["pages"][0]["state"] == "blocked"


def test_two_429s_in_a_row_stop_the_host_after_one_backoff(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/{i}" for i in range(3)]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, "User-agent: *\nAllow: /\n")},
        {u: visit(u, status=429, server="slow down") for u in urls},
    )
    job, sleeps = make_job(tmp_path, session, urls)
    job.run()
    states = [r["state"] for r in job.parts.buf["pages"]]
    assert states == ["rate_limited", "rate_limited", "skipped_host_stopped"]
    assert run.BACKOFF_S in sleeps
    assert job.hosts["www.shop.example"].stopped == "2 consecutive 429"


def test_transport_errors_are_recorded_and_the_fifth_in_a_row_stops_the_host(
    tmp_path: Path,
) -> None:
    urls = [f"{SHOP}/p/{i}" for i in range(7)]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, "User-agent: *\nAllow: /\n")},
        {u: TransportError("net::ERR_CONNECTION_RESET") for u in urls},
    )
    job, _ = make_job(tmp_path, session, urls)
    job.run()
    states = [r["state"] for r in job.parts.buf["pages"]]
    assert states == ["transport_error"] * 5 + ["skipped_host_stopped"] * 2
    assert job.parts.buf["pages"][0]["reason"] == "net::ERR_CONNECTION_RESET"
    assert job.counts["transport_error"] == 5


def test_http_errors_and_missing_responses_are_explicit(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/gone", f"{SHOP}/p/none", f"{SHOP}/p/ok"]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, "User-agent: *\nAllow: /\n")},
        {
            urls[0]: visit(urls[0], status=404, server="<html>not found</html>"),
            urls[1]: visit(urls[1], status=None, server="", shot=None),
            urls[2]: visit(urls[2], idle_timeout=True),
        },
    )
    job, _ = make_job(tmp_path, session, urls)
    job.run()
    rows = job.parts.buf["pages"]
    assert [r["state"] for r in rows] == ["http_error", "http_error", "ok"]
    assert rows[1]["reason"] == "no document response"
    assert rows[1]["raw_server"] is None
    assert rows[1]["shot"] is None
    assert rows[2]["idle_timeout"] is True
    assert job.counts["http_404"] == 1


# -------------------------------------------------------------------- cutoff, misc


def test_items_after_the_cutoff_are_skipped_and_the_outcome_says_so(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/{i}" for i in range(3)]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, "User-agent: *\nAllow: /\n")},
        {u: visit(u) for u in urls},
    )
    job, _ = make_job(tmp_path, session, urls, clock_steps=1500.0)  # each tick 25 min
    job.run()
    job.finish()
    rows = read_parts(tmp_path, "pages")
    assert rows[-1]["state"] == "skipped_cutoff"
    assert read_json(tmp_path, "status.json")["outcome"] == "cutoff"


def test_only_html_items_are_opened_and_a_limit_is_honoured(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/{i}" for i in range(4)]
    path = plan_file(tmp_path, urls)
    doc = json.loads(Path(path).read_text())
    doc["items"][1]["kind"] = "images"
    Path(path).write_text(json.dumps(doc))
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, "User-agent: *\nAllow: /\n")},
        {u: visit(u) for u in urls},
    )
    cfg = run.Config(
        bucket=f"file:{tmp_path / 'out'}",
        prefix="shop/browser-r1",
        plan_uri=path,
        cutoff=CUTOFF,
        limit=3,
    )
    job = run.Job(cfg, session, clock=lambda: T0, sleep=lambda s: None, rand=lambda: 0.0)
    job.run()
    assert [u for kind, u in session.calls if kind == "visit"] == [urls[0], urls[2]]


def test_sharded_tasks_name_their_outputs_apart(tmp_path: Path) -> None:
    urls = [f"{SHOP}/p/{i}" for i in range(4)]
    session = FakeSession(
        {f"{SHOP}/robots.txt": answer(200, "User-agent: *\nAllow: /\n")},
        {u: visit(u) for u in urls},
    )
    cfg = run.Config(
        bucket=f"file:{tmp_path / 'out'}",
        prefix="shop/browser-r1",
        plan_uri=plan_file(tmp_path, urls),
        cutoff=CUTOFF,
        task_index=1,
        task_count=2,
    )
    job = run.Job(cfg, session, clock=lambda: T0, sleep=lambda s: None, rand=lambda: 0.0)
    job.run()
    job.finish()
    out = tmp_path / "out" / "shop" / "browser-r1"
    assert (out / "status.t1.json").exists()
    assert (out / "manifest.t1.json").exists()
    assert sorted(p.name for p in (out / "pages").iterdir()) == ["part-t1-0000.jsonl.gz"]
    assert len(job.items) == 2


def test_store_is_the_shared_page_capture_store(tmp_path: Path) -> None:
    store = Store(f"file:{tmp_path}", "x")
    assert store.put("a.txt", b"hi", gz=False) == "a.txt"
    assert (tmp_path / "x" / "a.txt").read_bytes() == b"hi"


@pytest.mark.parametrize(
    ("why", "state"),
    [
        ("robots disallowed", "robots_disallowed"),
        ("robots unavailable: http 500 reading robots.txt", "robots_unavailable"),
        ("robots.txt not read for this host", "robots_unavailable"),
        ("host 'evil.test' is not in the allowed set", "hop_host_refused"),
        ("host stopped: 2 consecutive 429", "hop_host_refused"),
    ],
)
def test_a_refused_document_gets_the_state_its_reason_names(why: str, state: str) -> None:
    assert run.refused_state(why) == state
