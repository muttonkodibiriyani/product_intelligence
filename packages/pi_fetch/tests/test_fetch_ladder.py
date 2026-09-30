import logging
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import HttpUrl

from fetch_helpers import (
    FakeClock,
    ScriptedFactory,
    evidence_store,
    fake_pacer,
    local_server,
    make_ctx,
    raw,
)
from pi_core import FetchMethod, LadderRung, Locale, Market
from pi_fetch.cache import MemoryValidatorCache
from pi_fetch.ladder import Fetcher, accept_language, default_transport
from pi_fetch.pacing import RobotsTagger
from pi_fetch.policy import EgressProfile, Engine, FetchPlan, FetchPolicy, LadderPolicyError
from pi_fetch.transports.browser import BrowserTransport
from pi_fetch.transports.http import HttpTransport
from pi_fetch.types import BlockVendor, FetchRequest, PayloadKind

URL = HttpUrl("https://shop.example/p/1")
GULF = EgressProfile(name="gulf", proxy_url_env="PI_TEST_GULF_PROXY")


def req(
    kind: PayloadKind = PayloadKind.HTML, *, render: bool = False, capture_json: bool = False
) -> FetchRequest:
    return FetchRequest(
        url=URL, kind=kind, locale=Locale.EN, render=render, capture_json=capture_json
    )


def fetcher(tmp_path: Path, factory: ScriptedFactory, **kw: object) -> Fetcher:
    return Fetcher(
        policy=kw.pop("policy", FetchPolicy()),  # type: ignore[arg-type]
        evidence=evidence_store(tmp_path),
        pacer=fake_pacer(FakeClock()),
        transport_factory=factory,
        **kw,  # type: ignore[arg-type]
    )


def test_ok_fetch_records_audit_fields(tmp_path: Path) -> None:
    factory = ScriptedFactory(
        raw(headers=(("Content-Type", "text/html"), ("Set-Cookie", "sid=secret")))
    )
    with fetcher(tmp_path, factory) as f:
        result = f.fetch(req(), make_ctx(LadderRung.PLAIN_HTTP))
    assert result.ok
    assert (result.ladder_rung_used, result.fetch_method) == (
        LadderRung.PLAIN_HTTP,
        FetchMethod.PLAIN_HTTP,
    )
    assert result.egress == "direct"
    assert "set-cookie" not in result.headers
    assert result.evidence_uri.startswith("file://")
    assert Path(result.evidence_uri.removeprefix("file://")).read_bytes() == result.body
    assert factory.transports[0].closed


def test_sends_normal_headers(tmp_path: Path) -> None:
    factory = ScriptedFactory(raw())
    policy = FetchPolicy()
    f = fetcher(tmp_path, factory, policy=policy)
    f.fetch(
        FetchRequest(url=URL, kind=PayloadKind.JSON, locale=Locale.AR, headers={"X-A": "1"}),
        make_ctx(LadderRung.PLAIN_HTTP),
    )
    _, _, headers = factory.sends[0]
    assert headers["User-Agent"] == policy.user_agent
    assert headers["Accept"].startswith("application/json")
    assert headers["Accept-Language"] == "ar-AE,ar;q=0.9,en;q=0.8"
    assert headers["X-A"] == "1"


def test_accept_language() -> None:
    assert accept_language(Locale.EN, Market.KSA) == "en-SA,en;q=0.9"


def test_block_is_returned_once_without_retry_or_escalation(tmp_path: Path) -> None:
    factory = ScriptedFactory(
        raw(403, b"<div id='px-captcha'></div>"), raw(200, b"<html>never used</html>")
    )
    result = fetcher(tmp_path, factory).fetch(req(), make_ctx(LadderRung.PLAIN_HTTP))
    assert not result.ok
    assert result.block is not None
    assert result.block.vendor is BlockVendor.PERIMETERX
    assert len(factory.sends) == 1
    assert result.ladder_rung_used is LadderRung.PLAIN_HTTP
    assert result.evidence_uri  # blocked payloads are kept as evidence too


def test_non_2xx_is_not_ok(tmp_path: Path) -> None:
    result = fetcher(tmp_path, ScriptedFactory(raw(404, b"nf"))).fetch(
        req(), make_ctx(LadderRung.PLAIN_HTTP)
    )
    assert not result.ok
    assert result.block is None


def test_retry_after_defers_host_but_does_not_retry(tmp_path: Path) -> None:
    clock = FakeClock()
    factory = ScriptedFactory(raw(429, b"slow", (("Retry-After", "30"),)), raw())
    f = Fetcher(
        policy=FetchPolicy(),
        evidence=evidence_store(tmp_path),
        pacer=fake_pacer(clock),
        transport_factory=factory,
    )
    ctx = make_ctx(LadderRung.PLAIN_HTTP)
    first = f.fetch(req(), ctx)
    assert first.block is not None
    assert len(factory.sends) == 1
    f.fetch(req(), ctx)
    assert clock.slept == [30]


def test_render_request_uses_browser_route(tmp_path: Path) -> None:
    factory = ScriptedFactory(raw())
    result = fetcher(tmp_path, factory).fetch(req(render=True), make_ctx(LadderRung.PLAIN_HTTP))
    assert result.fetch_method is FetchMethod.PLAYWRIGHT
    assert factory.sends[0][0].engine is Engine.BROWSER


def test_policy_violation_raises_before_any_send(tmp_path: Path) -> None:
    factory = ScriptedFactory(raw())
    ctx = make_ctx(LadderRung.EGRESS_VARIATION)
    with pytest.raises(LadderPolicyError):
        fetcher(tmp_path, factory).fetch(req(), ctx)
    assert factory.sends == []


def test_transports_are_reused_per_route(tmp_path: Path) -> None:
    factory = ScriptedFactory(raw(), raw(), raw())
    f = fetcher(tmp_path, factory, policy=FetchPolicy(egress_variation=GULF))
    f.fetch(req(), make_ctx(LadderRung.PLAIN_HTTP))
    f.fetch(req(), make_ctx(LadderRung.PLAIN_HTTP))
    result = f.fetch(req(), make_ctx(LadderRung.EGRESS_VARIATION))
    assert len(factory.transports) == 2
    assert result.egress == "gulf"
    assert result.fetch_method is FetchMethod.EGRESS_VARIATION


def test_etag_revalidation_reuses_stored_payload(tmp_path: Path) -> None:
    body = b"<html>v1</html>"
    factory = ScriptedFactory(
        raw(200, body, (("Content-Type", "text/html"), ("ETag", '"v1"'))),
        raw(304, b"", (("ETag", '"v1"'),)),
    )
    f = fetcher(tmp_path, factory, cache=MemoryValidatorCache())
    ctx = make_ctx(LadderRung.PLAIN_HTTP)
    first = f.fetch(req(), ctx)
    second = f.fetch(req(), ctx)
    assert factory.sends[1][2]["If-None-Match"] == '"v1"'
    assert second.ok
    assert second.from_cache
    assert second.body == body
    assert second.evidence_uri == first.evidence_uri


def test_audit_log_records_every_fetch(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    robots = RobotsTagger()
    robots.add("shop.example", "User-agent: *\nDisallow: /p/\n")
    factory = ScriptedFactory(raw(403, b"denied", (("Server", "AkamaiGHost"),)))
    with caplog.at_level(logging.INFO, logger="pi_fetch.audit"):
        fetcher(tmp_path, factory, robots=robots).fetch(req(), make_ctx(LadderRung.PLAIN_HTTP))
    (record,) = caplog.records
    assert record.__dict__["block_vendor"] == "akamai"
    assert record.__dict__["robots"] == "disallowed"
    assert record.__dict__["ladder_rung_used"] == 1


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=40)
@given(
    rung=st.sampled_from([r for r in LadderRung if r.is_permitted]),
    kind=st.sampled_from(list(PayloadKind)),
    render=st.booleans(),
    egress=st.booleans(),
)
def test_fetcher_never_sends_on_rung_3(
    tmp_path: Path, rung: LadderRung, kind: PayloadKind, render: bool, egress: bool
) -> None:
    factory = ScriptedFactory(raw())
    policy = FetchPolicy(egress_variation=GULF if egress else None)
    f = fetcher(tmp_path, factory, policy=policy)
    try:
        result = f.fetch(req(kind, render=render), make_ctx(rung, max_allowed=rung))
    except LadderPolicyError:
        assert factory.sends == []
        return
    assert result.ladder_rung_used is not LadderRung.STEALTH_BROWSER
    assert [route.rung for route, _, _ in factory.sends] == [result.ladder_rung_used]
    assert result.ladder_rung_used is not LadderRung.PAID_PROXY


def test_default_transport_picks_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_TEST_GULF_PROXY", "http://127.0.0.1:9")
    policy = FetchPolicy()
    http = default_transport(
        FetchPlan(
            rung=LadderRung.PLAIN_HTTP,
            method=FetchMethod.PLAIN_HTTP,
            engine=Engine.HTTP,
            egress=GULF,
        ),
        policy,
    )
    browser = default_transport(
        FetchPlan(
            rung=LadderRung.BROWSER,
            method=FetchMethod.PLAYWRIGHT,
            engine=Engine.BROWSER,
            egress=GULF,
        ),
        policy,
    )
    assert isinstance(http, HttpTransport)
    assert isinstance(browser, BrowserTransport)
    http.close()
    browser.close()


def test_end_to_end_against_local_server(tmp_path: Path) -> None:
    with local_server() as srv:
        srv.static("/p/1", b"<html>product</html>", "text/html", ("ETag", '"e1"'))
        srv.routes["/blocked"] = lambda _h: (
            403,
            [("Content-Type", "text/html"), ("Set-Cookie", "_abck=zzz")],
            b"Access Denied",
        )
        f = Fetcher(
            policy=FetchPolicy(timeout_s=5),
            evidence=evidence_store(tmp_path),
            pacer=fake_pacer(FakeClock()),
            cache=MemoryValidatorCache(),
        )
        ctx = make_ctx(LadderRung.PLAIN_HTTP)
        with f:
            ok = f.fetch(
                FetchRequest(
                    url=HttpUrl(f"{srv.base}/p/1"), kind=PayloadKind.HTML, locale=Locale.EN
                ),
                ctx,
            )
            blocked = f.fetch(
                FetchRequest(
                    url=HttpUrl(f"{srv.base}/blocked"), kind=PayloadKind.HTML, locale=Locale.EN
                ),
                ctx,
            )
    assert ok.ok
    assert ok.body == b"<html>product</html>"
    assert blocked.block is not None
    assert blocked.block.vendor is BlockVendor.AKAMAI
    assert "set-cookie" not in blocked.headers
    _path, headers, version = srv.requests[0]
    assert version == "HTTP/1.1"
    assert headers["User-Agent"] == FetchPolicy().user_agent
    assert headers["Accept-Language"] == "en-AE,en;q=0.9"
    assert "Cookie" not in headers
