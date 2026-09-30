"""Rung 5: the per-source residential proxy (owner decision for ulta.ae). Fakes only, no network."""

import base64
import json
import logging
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from playwright.sync_api import Error as PlaywrightError
from pydantic import HttpUrl

from fetch_helpers import (
    PINNED,
    WEBKIT,
    FakeClock,
    ScriptedFactory,
    allow_all_robots,
    evidence_store,
    make_ctx,
    raw,
)
from pi_core import FetchMethod, LadderRung, Locale
from pi_fetch.ladder import (
    Fetcher,
    SourceStoppedError,
    default_proxy_transport,
    robots_key,
    robots_text_from_viewer,
)
from pi_fetch.pacing import HostPacer, RobotsRefusedError, RobotsTag, RobotsTagger
from pi_fetch.policy import (
    EgressProfile,
    Engine,
    FetchPlan,
    FetchPolicy,
    LadderPolicyError,
    permitted_rungs,
    plan,
)
from pi_fetch.proxy import (
    DEFAULT_BYTE_CAP,
    REDACTED,
    ProxyBudgetExceededError,
    ProxyConfigError,
    ProxyCredentials,
    ProxyMeter,
    ResidentialProxy,
    SecretManagerReader,
    gcloud_token,
    load_credentials,
    metadata_token,
    redact,
    registrable_domain,
    should_abort,
)
from pi_fetch.transports.base import RawResponse, Transport, TransportError
from pi_fetch.transports.browser import BrowserTransport, _collector
from pi_fetch.types import BlockKind, CapturedJson, FetchRequest, PayloadKind

RESOURCE = "projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/latest"
USER = "fake-proxy-user-3141"
PASSWORD = "fake-proxy-pass-2718"  # noqa: S105 - a fake, not a credential
SECRET_JSON = json.dumps(
    {
        "host": "gw.proxy.test",
        "port": 12321,
        "username": USER,
        "password": PASSWORD,
        "provider": "iproyal",
    }
).encode()
ULTA = ResidentialProxy(
    source_key="ulta_ae",
    owner_approval_ref="owner-decision-2026-09-30-iproyal",
    secret_resource=RESOURCE,
    egress_name="iproyal_ae",
    prior_bytes=0,
)
POLICY = FetchPolicy(browsers=PINNED, residential_proxy={3: ULTA}, page_interval_s={3: 5.0})
PDP = HttpUrl("https://www.ulta.ae/en/p/1")
VIEWER = (
    '<html><head><meta name="color-scheme" content="light dark"></head><body>'
    '<pre style="word-wrap: break-word; white-space: pre-wrap;">User-agent: *\n'
    "Disallow: /en/search?\nDisallow: /a&amp;b\n</pre></body></html>"
)


def pdp(url: HttpUrl = PDP, kind: PayloadKind = PayloadKind.HTML) -> FetchRequest:
    return FetchRequest(url=url, kind=kind, locale=Locale.EN, render=kind is PayloadKind.HTML)


def ctx(rung: LadderRung = LadderRung.PAID_PROXY) -> Any:
    return make_ctx(rung, max_allowed=LadderRung.PAID_PROXY)


class FakeReader:
    def __init__(self, payload: bytes = SECRET_JSON) -> None:
        self.payload = payload
        self.reads: list[str] = []

    def read(self, resource: str) -> bytes:
        self.reads.append(resource)
        return self.payload


class ProxyFactory:
    """A ``ProxyTransportFactory``: scripted responses, metered like the real browser."""

    def __init__(self, *responses: RawResponse) -> None:
        self.responses = list(responses)
        self.credentials: list[ProxyCredentials] = []
        self.meters: list[ProxyMeter] = []
        self.sent: list[tuple[FetchPlan, FetchRequest]] = []
        self.robots_checks: list[Callable[[str], bool]] = []

    def __call__(
        self,
        route: FetchPlan,
        policy: FetchPolicy,
        creds: ProxyCredentials,
        meter: ProxyMeter,
        robots_ok: Callable[[str], bool],
    ) -> Transport:
        self.robots_checks.append(robots_ok)
        self.credentials.append(creds)
        self.meters.append(meter)
        factory = self

        class _T:
            def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
                meter.check()
                factory.sent.append((route, request))
                response = factory.responses.pop(0)
                meter.add(200, len(response.body))
                return response

            def close(self) -> None:
                pass

        return _T()


class SpyPacer(HostPacer):
    def __init__(self) -> None:
        clock = FakeClock()
        super().__init__(clock=clock, sleep=clock.sleep)
        self.hosts: list[str] = []

    def wait(self, host: str, min_interval_s: float | None = None) -> float:
        self.hosts.append(host)
        return super().wait(host, min_interval_s)


def proxied_fetcher(
    tmp_path: Path,
    proxy_factory: ProxyFactory,
    direct: ScriptedFactory | None = None,
    **kw: Any,
) -> Fetcher:
    return Fetcher(
        policy=kw.pop("policy", POLICY),
        evidence=evidence_store(tmp_path),
        pacer=kw.pop("pacer", SpyPacer()),
        robots=kw.pop("robots", allow_all_robots("www.ulta.ae")),
        transport_factory=direct or ScriptedFactory(),
        proxy_transport_factory=proxy_factory,
        secret_reader=kw.pop("secret_reader", FakeReader()),
    )


# --- config -----------------------------------------------------------------------------------


def test_proxy_is_refused_for_any_source_but_ulta() -> None:
    with pytest.raises(ValueError, match="approved only for"):
        ResidentialProxy(
            source_key="sephora_me",
            owner_approval_ref="x",
            secret_resource=RESOURCE,
            egress_name="iproyal",
            prior_bytes=0,
        )


def test_secret_resource_must_be_latest() -> None:
    with pytest.raises(ValueError, match="versions/latest"):
        ULTA.model_copy(update={"secret_resource": RESOURCE.replace("latest", "3")}).model_validate(
            {**ULTA.model_dump(), "secret_resource": RESOURCE.replace("latest", "3")}
        )


def test_proxied_source_must_pace_at_least_5s() -> None:
    with pytest.raises(ValueError, match="page_interval_s >= 5"):
        FetchPolicy(browsers=PINNED, residential_proxy={3: ULTA})
    with pytest.raises(ValueError, match="page_interval_s >= 5"):
        FetchPolicy(browsers=PINNED, residential_proxy={3: ULTA}, page_interval_s={3: 2.0})


def test_defaults_are_the_owner_cap_and_price() -> None:
    assert ULTA.byte_cap == DEFAULT_BYTE_CAP == 1_800_000_000
    assert ULTA.usd_per_gb == Decimal("6.25")


def test_rung5_only_for_sources_with_a_proxy() -> None:
    assert LadderRung.PAID_PROXY in permitted_rungs(POLICY, ctx().source_context)
    assert LadderRung.PAID_PROXY not in permitted_rungs(
        FetchPolicy(browsers=PINNED), ctx().source_context
    )


def test_plan_routes_pages_through_the_pinned_browser_and_proxy() -> None:
    route = plan(pdp(), ctx(), POLICY)
    assert route.rung is LadderRung.PAID_PROXY
    assert route.method is FetchMethod.RESIDENTIAL_PROXY
    assert route.engine is Engine.BROWSER
    assert route.browser == WEBKIT
    assert route.egress.name == "iproyal_ae"
    assert route.proxy == ULTA
    json_route = plan(pdp(kind=PayloadKind.JSON), ctx(), POLICY)
    assert json_route.engine is Engine.BROWSER
    assert json_route.proxy == ULTA


def test_plan_never_proxies_images() -> None:
    image = pdp(HttpUrl("https://media.ulta-cdn.test/i/1.jpg"), PayloadKind.IMAGE)
    route = plan(image, ctx(), POLICY)
    assert route.rung is LadderRung.PLAIN_HTTP
    assert route.engine is Engine.HTTP
    assert route.egress.name == "direct"
    assert route.proxy is None


@pytest.mark.parametrize("host", ["www.ulta.ae", "ulta.ae", "WWW.ULTA.AE"])
def test_plan_skips_images_on_the_proxied_page_host(host: str) -> None:
    with pytest.raises(LadderPolicyError, match="skipped"):
        plan(pdp(HttpUrl(f"https://{host}/i/1.jpg"), PayloadKind.IMAGE), ctx(), POLICY)


def test_plan_refuses_proxying_another_site() -> None:
    with pytest.raises(LadderPolicyError, match=r"carries ulta\.ae only"):
        plan(pdp(HttpUrl("https://www.sephora.me/p/1")), ctx(), POLICY)


def test_registrable_domain() -> None:
    assert registrable_domain("www.ulta.ae") == "ulta.ae"
    assert registrable_domain("ULTA.AE.") == "ulta.ae"
    assert registrable_domain("a.b.co.uk") == "b.co.uk"


@pytest.mark.parametrize(
    ("resource_type", "host", "abort"),
    [
        ("image", "www.ulta.ae", True),
        ("media", "www.ulta.ae", True),
        ("font", "static.ulta.ae", True),
        ("ping", "www.ulta.ae", True),
        ("document", "www.ulta.ae", False),
        ("script", "static.ulta.ae", False),
        ("xhr", "ulta.ae", False),
        ("fetch", "www.ulta.ae", False),
        ("script", "www.googletagmanager.com", True),
        ("xhr", "analytics.tracker.test", True),
        ("script", "cdn.allowed.test", False),
    ],
)
def test_should_abort(resource_type: str, host: str, abort: bool) -> None:
    allow = frozenset({"cdn.allowed.test"})
    assert should_abort(resource_type, host, "www.ulta.ae", allow) is abort


# --- credentials and redaction ----------------------------------------------------------------


def test_credentials_never_appear_in_repr_str_or_dump() -> None:
    creds = load_credentials(FakeReader(), RESOURCE)
    for text in (repr(creds), str(creds), creds.model_dump_json(), str(creds.model_dump())):
        assert USER not in text
        assert PASSWORD not in text
    assert creds.server == "http://gw.proxy.test:12321"
    assert creds.playwright_proxy()["password"] == PASSWORD


def test_redact() -> None:
    assert redact(f"auth {USER}:{PASSWORD} failed", (USER, PASSWORD, "")) == (
        f"auth {REDACTED}:{REDACTED} failed"
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"not json " + PASSWORD.encode(),
        json.dumps({"host": "h", "port": 0, "username": USER, "password": PASSWORD}).encode(),
    ],
)
def test_bad_secret_errors_carry_no_secret(payload: bytes) -> None:
    with pytest.raises(ProxyConfigError) as err:
        load_credentials(FakeReader(payload), RESOURCE)
    assert PASSWORD not in str(err.value)
    assert USER not in str(err.value)
    assert err.value.__cause__ is None


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_secret_manager_reader_reads_latest_in_memory() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        data = base64.b64encode(SECRET_JSON).decode()
        return httpx.Response(200, json={"payload": {"data": data}})

    reader = SecretManagerReader(token=lambda: "tok", client=_mock_client(handler))
    assert load_credentials(reader, RESOURCE).provider == "iproyal"
    assert seen[0].url.path.endswith("/versions/latest:access")
    assert seen[0].headers["Authorization"] == "Bearer tok"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(403, json={"error": "denied"}), httpx.Response(200, json={"nope": 1})],
)
def test_secret_manager_reader_errors(response: httpx.Response) -> None:
    reader = SecretManagerReader(token=lambda: "tok", client=_mock_client(lambda _: response))
    with pytest.raises(ProxyConfigError, match="pi-proxy-iproyal-ae"):
        reader.read(RESOURCE)


def test_metadata_token() -> None:
    ok = _mock_client(lambda _: httpx.Response(200, json={"access_token": "abc"}))
    assert metadata_token(ok) == "abc"
    bad = _mock_client(lambda _: httpx.Response(404))
    with pytest.raises(ProxyConfigError, match="metadata server"):
        metadata_token(bad)


def test_gcloud_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def ok(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout="tok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", ok)
    assert gcloud_token() == "tok"

    def fail(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, "gcloud")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ProxyConfigError, match="gcloud"):
        gcloud_token()


# --- meter ------------------------------------------------------------------------------------


def test_meter_counts_costs_and_reports_for_the_manifest() -> None:
    meter = ProxyMeter("iproyal_ae", 1_800_000_000)
    meter.add(800_000_000, 1_000_000_000)
    usage = meter.usage()
    assert usage.total == 1_800_000_000
    assert usage.usd == Decimal("11.25")
    assert usage.manifest()["bytes_via_proxy"] == 1_800_000_000
    assert usage.manifest()["usd"] == "11.25"
    assert usage.stopped
    with pytest.raises(ProxyBudgetExceededError, match="cap of 1800000000"):
        meter.check()


def test_meter_never_starts_a_request_that_could_cross_the_cap() -> None:
    meter = ProxyMeter("p", 100, page_reserve=30, request_reserve=10)
    meter.add(60, 0)
    meter.check()  # 60 + 30 <= 100
    assert meter.allows_subrequest()
    meter.add(0, 15)  # 75 + 30 > 100: no new page, sub-requests still fit
    with pytest.raises(ProxyBudgetExceededError):
        meter.check()
    assert meter.allows_subrequest()
    meter.add(0, 16)  # 91 + 10 > 100
    assert not meter.allows_subrequest()
    meter.add(-5, -5)  # negative sizes (unknown) are ignored
    assert meter.usage().total == 91


# --- fetcher ----------------------------------------------------------------------------------


def test_proxied_fetch_uses_the_secret_and_meters_it(tmp_path: Path) -> None:
    proxy = ProxyFactory(raw(body=b"<html>pdp</html>"))
    reader = FakeReader()
    f = proxied_fetcher(tmp_path, proxy, secret_reader=reader)
    result = f.fetch(pdp(), ctx())
    assert result.ok
    assert result.fetch_method is FetchMethod.RESIDENTIAL_PROXY
    assert result.egress == "iproyal_ae"
    assert reader.reads == [RESOURCE]
    assert proxy.credentials[0].password.get_secret_value() == PASSWORD
    (usage,) = f.proxy_usage()
    assert usage.total == 200 + len(b"<html>pdp</html>")


def test_robots_goes_through_the_same_proxied_browser(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    viewer = raw(body=VIEWER.encode(), headers=(("content-type", "text/plain"),))
    proxy = ProxyFactory(viewer, raw())
    direct = ScriptedFactory()
    f = proxied_fetcher(tmp_path, proxy, direct, robots=RobotsTagger())
    with caplog.at_level(logging.INFO, logger="pi_fetch.audit"):
        f.fetch(pdp(), ctx())
        with pytest.raises(RobotsRefusedError):
            f.fetch(pdp(HttpUrl("https://www.ulta.ae/en/search?q=x")), ctx())
    assert direct.sends == []  # never httpx, never direct
    (robots_route, robots_req), (page_route, _) = proxy.sent
    assert robots_req.url.path == "/robots.txt"
    assert robots_route == page_route
    loaded = next(r for r in caplog.records if getattr(r, "event", "") == "robots_loaded")
    assert loaded.__dict__["transport"] == "playwright"
    assert loaded.__dict__["engine"] == "webkit"
    assert loaded.__dict__["egress"] == "iproyal_ae"


@pytest.mark.parametrize(
    "robots_response",
    [
        raw(body=b"<html><body>Home</body></html>", headers=(("content-type", "text/html"),)),
        raw(
            body=b"<html><head></head><body><pre>x</pre><div/></body></html>",
            headers=(("content-type", "text/plain"),),
        ),
        raw(500, b"err"),
    ],
)
def test_unreadable_robots_via_proxy_refuses(tmp_path: Path, robots_response: RawResponse) -> None:
    proxy = ProxyFactory(robots_response)
    f = proxied_fetcher(tmp_path, proxy, robots=RobotsTagger())
    with pytest.raises(RobotsRefusedError):
        f.fetch(pdp(), ctx())
    assert len(proxy.sent) == 1


def test_robots_challenge_stops_the_source(tmp_path: Path) -> None:
    challenge = raw(403, b"<html>cf-chl-bypass</html>", (("content-type", "text/html"),))
    proxy = ProxyFactory(challenge)
    f = proxied_fetcher(tmp_path, proxy, robots=RobotsTagger())
    with pytest.raises(SourceStoppedError, match="challenge"):
        f.fetch(pdp(), ctx())
    with pytest.raises(SourceStoppedError):
        f.fetch(pdp(), ctx())
    assert len(proxy.sent) == 1
    assert "challenge" in f.stopped_sources()[3]


@pytest.mark.parametrize(
    ("status", "body", "headers"),
    [
        (403, b"denied", ()),
        (401, b"login", ()),
        (503, b"<div id='px-captcha'></div>", ()),
        (429, b"<script src='/cdn-cgi/challenge-platform/x'></script>", ()),
        (200, b"<html>ok</html>", (("cf-mitigated", "challenge"),)),
    ],
)
def test_first_block_or_challenge_stops_the_run(
    tmp_path: Path, status: int, body: bytes, headers: tuple[tuple[str, str], ...]
) -> None:
    proxy = ProxyFactory(raw(status, body, (("content-type", "text/html"), *headers)), raw())
    direct = ScriptedFactory(raw())
    f = proxied_fetcher(tmp_path, proxy, direct)
    result = f.fetch(pdp(), ctx())
    assert result.block is not None
    assert result.block.kind in {BlockKind.CHALLENGE, BlockKind.BLOCKED}
    with pytest.raises(SourceStoppedError):
        f.fetch(pdp(), ctx())
    assert len(proxy.sent) == 1  # no retry
    assert direct.sends == []  # no fallback to another engine or egress


def test_two_consecutive_429s_stop_the_run(tmp_path: Path) -> None:
    proxy = ProxyFactory(raw(429, b"slow down"), raw(), raw(429, b"x"), raw(429, b"x"))
    f = proxied_fetcher(tmp_path, proxy)
    assert f.fetch(pdp(), ctx()).rate_limited
    assert f.fetch(pdp(), ctx()).ok  # a success resets the count
    assert f.fetch(pdp(), ctx()).rate_limited
    assert f.stopped_sources() == {}
    f.fetch(pdp(), ctx())
    assert f.stopped_sources() == {3: "2 consecutive 429s"}
    with pytest.raises(SourceStoppedError):
        f.fetch(pdp(), ctx())


def test_sources_without_a_proxy_are_not_stopped(tmp_path: Path) -> None:
    direct = ScriptedFactory(raw(403, b"denied"), raw())
    f = Fetcher(
        policy=FetchPolicy(browsers=PINNED),
        evidence=evidence_store(tmp_path),
        pacer=SpyPacer(),
        robots=allow_all_robots(),
        transport_factory=direct,
    )
    url = FetchRequest(
        url=HttpUrl("https://shop.example/p/1"), kind=PayloadKind.HTML, locale=Locale.EN
    )
    assert f.fetch(url, make_ctx()).block is not None
    assert f.fetch(url, make_ctx()).ok


def test_byte_cap_stops_the_run_before_crossing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    small = ULTA.model_copy(update={"byte_cap": 5_000, "page_reserve_bytes": 1_000})
    policy = POLICY.model_copy(update={"residential_proxy": {3: small}})
    proxy = ProxyFactory(raw(body=b"x" * 3_900), raw())
    f = proxied_fetcher(tmp_path, proxy, policy=policy)
    assert f.fetch(pdp(), ctx()).ok  # 4100 used; another page (reserve 1000) could cross
    assert f.stopped_sources() == {3: "proxy_byte_cap"}
    with pytest.raises(SourceStoppedError, match="proxy_byte_cap"):
        f.fetch(pdp(), ctx())
    assert len(proxy.sent) == 1
    with caplog.at_level(logging.INFO, logger="pi_fetch.audit"):
        f.close()
    (event,) = [r for r in caplog.records if getattr(r, "event", "") == "proxy_usage"]
    assert event.__dict__["byte_cap"] == 5_000


def test_budget_error_from_the_transport_stops_the_source(tmp_path: Path) -> None:
    proxy = ProxyFactory(raw())
    f = proxied_fetcher(tmp_path, proxy)
    f.fetch(pdp(), ctx())
    proxy.meters[0].add(0, DEFAULT_BYTE_CAP)
    f._stopped.clear()  # simulate a meter filled by another page's sub-requests
    with pytest.raises(ProxyBudgetExceededError):
        f.fetch(pdp(), ctx())
    assert f.stopped_sources() == {3: "proxy_byte_cap"}


def test_images_go_direct_with_the_cdn_robots_and_pacing(tmp_path: Path) -> None:
    direct = ScriptedFactory(
        raw(200, b"User-agent: *\nDisallow: /private/", (("content-type", "text/plain"),)),
        raw(body=b"\x89PNG"),
    )
    proxy = ProxyFactory()
    pacer = SpyPacer()
    f = proxied_fetcher(tmp_path, proxy, direct, pacer=pacer)
    image = pdp(HttpUrl("https://media.ulta-cdn.test/i/1.png"), PayloadKind.IMAGE)
    result = f.fetch(image, ctx())
    assert result.egress == "direct"
    assert result.ladder_rung_used is LadderRung.PLAIN_HTTP
    assert proxy.sent == []
    robots_route, robots_req, _ = direct.sends[0]
    assert robots_req.url.host == "media.ulta-cdn.test"
    assert robots_route.engine is Engine.HTTP
    assert pacer.hosts == ["media.ulta-cdn.test", "media.ulta-cdn.test"]
    with pytest.raises(RobotsRefusedError):
        f.fetch(pdp(HttpUrl("https://media.ulta-cdn.test/private/2.png"), PayloadKind.IMAGE), ctx())


def test_no_secret_in_logs_or_errors(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    proxy = ProxyFactory(raw(403, b"denied"))
    with caplog.at_level(logging.DEBUG):
        f = proxied_fetcher(tmp_path, proxy)
        f.fetch(pdp(), ctx())
        with pytest.raises(SourceStoppedError) as err:
            f.fetch(pdp(), ctx())
        f.close()
    texts = [caplog.text, str(err.value), repr(f), *(str(r.__dict__) for r in caplog.records)]
    for text in texts:
        assert PASSWORD not in text
        assert USER not in text


# --- robots viewer extraction ------------------------------------------------------------------


def test_viewer_extraction_is_strict() -> None:
    assert robots_text_from_viewer(VIEWER) == (
        "User-agent: *\nDisallow: /en/search?\nDisallow: /a&b\n"
    )
    webkit = "<html><head></head><body><pre>User-agent: *</pre></body></html>"
    assert robots_text_from_viewer(webkit) == "User-agent: *"
    assert robots_text_from_viewer("<html><body>Just a moment...</body></html>") is None
    assert (
        robots_text_from_viewer(
            "<html><head><script>x()</script></head><body><pre>a</pre></body></html>"
        )
        is None
    )
    assert (
        robots_text_from_viewer("<html><head></head><body><pre>a<b>c</b></pre></body></html>")
        is None
    )
    assert (
        robots_text_from_viewer("<html><head></head><body><pre>a</pre><pre>b</pre></body></html>")
        is None
    )


# --- browser transport pieces -------------------------------------------------------------------


def _creds() -> ProxyCredentials:
    return load_credentials(FakeReader(), RESOURCE)


def _yes(_url: str) -> bool:
    return True


def test_browser_transport_proxy_settings_and_repr() -> None:
    creds = _creds()
    t = BrowserTransport(
        profile=WEBKIT, credentials=creds, meter=ProxyMeter("p", 10), subrequest_allowed=_yes
    )
    settings = t._proxy_settings()
    assert settings == {
        "server": "http://gw.proxy.test:12321",
        "username": USER,
        "password": PASSWORD,
    }
    assert PASSWORD not in repr(t)
    assert "residential" in repr(t)
    assert BrowserTransport(profile=WEBKIT, proxy="http://gulf:1")._proxy_settings() == {
        "server": "http://gulf:1"
    }
    assert BrowserTransport(profile=WEBKIT)._proxy_settings() is None
    with pytest.raises(ValueError, match="byte meter"):
        BrowserTransport(profile=WEBKIT, credentials=creds)
    with pytest.raises(ValueError, match="robots check"):
        BrowserTransport(profile=WEBKIT, credentials=creds, meter=ProxyMeter("p", 10))


def test_browser_errors_are_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    t = BrowserTransport(
        profile=WEBKIT, credentials=_creds(), meter=ProxyMeter("p", 10**6), subrequest_allowed=_yes
    )

    def boom(_: str) -> None:
        raise PlaywrightError(f"proxy auth failed for {USER}:{PASSWORD}")

    monkeypatch.setattr(t, "_new_context", boom)
    with pytest.raises(Exception, match=REDACTED) as err:
        t.send(pdp(), {})
    assert PASSWORD not in str(err.value)
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__


def test_browser_refuses_a_page_over_the_cap() -> None:
    meter = ProxyMeter("p", 10, page_reserve=5)
    meter.add(6, 0)
    t = BrowserTransport(profile=WEBKIT, credentials=_creds(), meter=meter, subrequest_allowed=_yes)
    with pytest.raises(ProxyBudgetExceededError):
        t.send(pdp(), {})


class _FakeRequest:
    def __init__(
        self,
        url: str,
        resource_type: str,
        sizes: dict[str, int] | None = None,
        *,
        navigation: bool = False,
    ) -> None:
        self.url = url
        self.resource_type = resource_type
        self._sizes = sizes
        self._navigation = navigation

    def is_navigation_request(self) -> bool:
        return self._navigation

    def sizes(self) -> dict[str, int]:
        if self._sizes is None:
            raise PlaywrightError("no sizes")
        return self._sizes


class _FakeRoute:
    def __init__(self) -> None:
        self.outcome = ""

    def abort(self, _: str) -> None:
        self.outcome = "abort"

    def continue_(self) -> None:
        self.outcome = "continue"


class _FakeContext:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., None]] = {}

    def route(self, _: str, handler: Callable[..., None]) -> None:
        self.handlers["route"] = handler

    def on(self, event: str, handler: Callable[..., None]) -> None:
        self.handlers[event] = handler

    def route_web_socket(self, _: str, handler: Callable[..., None]) -> None:
        self.handlers["websocket"] = handler


class _FakeWebSocket:
    closed = False

    def close(self) -> None:
        self.closed = True


def _guarded(
    robots_ok: Callable[[str], bool], meter: ProxyMeter | None = None
) -> tuple[_FakeContext, Callable[..., str], Counter[str]]:
    meter = meter or ProxyMeter("p", 10**9)
    t = BrowserTransport(
        profile=WEBKIT, credentials=_creds(), meter=meter, subrequest_allowed=robots_ok
    )
    context = _FakeContext()
    aborted: Counter[str] = Counter()
    t._guard(context, "www.ulta.ae", meter, aborted)  # type: ignore[arg-type]

    def outcome(url: str, resource_type: str, *, navigation: bool = False) -> str:
        route = _FakeRoute()
        context.handlers["route"](route, _FakeRequest(url, resource_type, navigation=navigation))
        return route.outcome

    return context, outcome, aborted


def test_browser_guard_aborts_heavy_and_third_party_and_meters() -> None:
    meter = ProxyMeter("p", 10_000, request_reserve=1_000)
    context, outcome, aborted = _guarded(_yes, meter)
    assert outcome("https://www.ulta.ae/en/p/1", "document", navigation=True) == "continue"
    assert outcome("https://www.ulta.ae/api/graphql", "fetch") == "continue"
    assert outcome("https://www.ulta.ae/i/1.jpg", "image") == "abort"
    assert outcome("https://www.google-analytics.com/collect", "xhr") == "abort"
    finished = context.handlers["requestfinished"]
    finished(
        _FakeRequest(
            "u",
            "xhr",
            {
                "requestHeadersSize": 100,
                "requestBodySize": 0,
                "responseHeadersSize": 200,
                "responseBodySize": 8_800,
            },
        )
    )
    finished(_FakeRequest("u", "xhr", None))  # sizes unavailable: skipped
    assert meter.usage().total == 9_100
    assert outcome("https://www.ulta.ae/api/graphql", "fetch") == "abort"  # would cross the cap
    assert aborted == {"asset": 2, "cap": 1}


ULTA_ROBOTS = (Path(__file__).parent / "fixtures" / "robots" / "ulta_ae.txt").read_text()


def _ulta_rules(*, available: bool = True) -> Callable[[str], bool]:
    tagger = RobotsTagger()
    if available:
        tagger.add("www.ulta.ae", ULTA_ROBOTS)
    else:
        tagger.mark_unavailable("www.ulta.ae")

    def allowed(url: str) -> bool:
        return tagger.tag(urlsplit(url).hostname or "", url) is RobotsTag.ALLOWED

    return allowed


def test_guard_applies_robots_to_every_subrequest() -> None:
    _, outcome, aborted = _guarded(_ulta_rules())
    # The page itself was robots-checked by the fetcher; only the first navigation is exempt.
    assert outcome("https://www.ulta.ae/en/p/1", "document", navigation=True) == "continue"
    assert outcome("https://www.ulta.ae/graphql?query=%7Bproduct%7D", "fetch") == "abort"
    assert outcome("https://www.ulta.ae/graphql", "fetch") == "continue"  # POST, no query
    assert outcome("https://www.ulta.ae/en/fragments/header", "xhr") == "abort"
    assert outcome("https://www.ulta.ae/en/p/2?x=1", "document", navigation=True) == "abort"
    assert aborted == {"robots": 3}


def test_guard_aborts_every_subrequest_when_robots_is_unavailable() -> None:
    _, outcome, aborted = _guarded(_ulta_rules(available=False))
    assert outcome("https://www.ulta.ae/robots.txt", "document", navigation=True) == "continue"
    assert outcome("https://www.ulta.ae/graphql", "fetch") == "abort"
    assert outcome("https://www.ulta.ae/static/app.js", "script") == "abort"
    assert aborted == {"robots": 2}


def test_guard_closes_websockets() -> None:
    context, _, _ = _guarded(_yes)
    ws = _FakeWebSocket()
    context.handlers["websocket"](ws)
    assert ws.closed


class _Resp:
    def __init__(self, url: str) -> None:
        self.url = url
        self.status = 200
        self.request = _FakeRequest(url, "fetch")

    def header_value(self, _: str) -> str:
        return "application/json"

    def body(self) -> bytes:
        return b"{}"


def test_capture_never_keeps_json_from_a_disallowed_url() -> None:
    sink: list[CapturedJson] = []
    on_response = _collector(sink, _ulta_rules())
    on_response(_Resp("https://www.ulta.ae/graphql?query=%7Bproduct%7D"))  # type: ignore[arg-type]
    on_response(_Resp("https://www.ulta.ae/graphql"))  # type: ignore[arg-type]
    assert [str(c.url) for c in sink] == ["https://www.ulta.ae/graphql"]


class _FakeBrowser:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def new_context(self, **kwargs: Any) -> str:
        self.kwargs = kwargs
        return "context"


def test_proxied_context_blocks_service_workers() -> None:
    t = BrowserTransport(
        profile=WEBKIT, credentials=_creds(), meter=ProxyMeter("p", 10), subrequest_allowed=_yes
    )
    browser = _FakeBrowser()
    t._browser = browser  # type: ignore[assignment]
    t._new_context("en")
    assert browser.kwargs["service_workers"] == "block"
    direct = BrowserTransport(profile=WEBKIT)
    direct._browser = browser  # type: ignore[assignment]
    direct._new_context("en")
    assert browser.kwargs["service_workers"] == "allow"


def test_page_bytes_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    t = BrowserTransport(
        profile=WEBKIT, credentials=_creds(), meter=ProxyMeter("p", 10), subrequest_allowed=_yes
    )
    with caplog.at_level(logging.INFO, logger="pi_fetch.audit"):
        t._log_page(pdp(), 1234, Counter({"robots": 2}))
    (record,) = [r for r in caplog.records if getattr(r, "event", "") == "proxy_page_bytes"]
    assert record.bytes == 1234  # type: ignore[attr-defined]
    assert record.aborted == {"robots": 2}  # type: ignore[attr-defined]


def test_fetcher_robots_check_uses_the_route_key(tmp_path: Path) -> None:
    factory = ProxyFactory(raw())
    robots = RobotsTagger()
    f = proxied_fetcher(tmp_path, factory, robots=robots)
    route = plan(pdp(), ctx(), POLICY)
    assert route.browser is not None
    robots.add(
        robots_key("www.ulta.ae", route.browser.engine.value, route.egress.name), ULTA_ROBOTS
    )
    f.fetch(pdp(), ctx())
    (check,) = factory.robots_checks
    assert check("https://www.ulta.ae/graphql")
    assert not check("https://www.ulta.ae/graphql?query=x")
    assert not check("https://cdn.ulta.ae/x.js")  # robots never read for that host: abort


def test_default_proxy_transport() -> None:
    route = plan(pdp(), ctx(), POLICY)
    transport = default_proxy_transport(route, POLICY, _creds(), ProxyMeter("p", 10), _yes)
    assert isinstance(transport, BrowserTransport)
    http_route = FetchPlan(
        rung=LadderRung.PLAIN_HTTP,
        method=FetchMethod.PLAIN_HTTP,
        engine=Engine.HTTP,
        egress=EgressProfile(name="direct"),
    )
    with pytest.raises(ValueError, match="pinned browser"):
        default_proxy_transport(http_route, POLICY, _creds(), ProxyMeter("p", 10), _yes)


class _FailingProxy:
    def __init__(self) -> None:
        self.sends = 0

    def __call__(
        self,
        route: FetchPlan,
        policy: FetchPolicy,
        creds: ProxyCredentials,
        meter: ProxyMeter,
        robots_ok: Callable[[str], bool],
    ) -> Transport:
        return self

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        self.sends += 1
        msg = f"browser fetch failed: net::ERR_PROXY_CONNECTION_FAILED ({REDACTED})"
        raise TransportError(msg)

    def close(self) -> None:
        pass


def test_proxy_connect_error_stops_the_run_without_fallback(tmp_path: Path) -> None:
    failing = _FailingProxy()
    direct = ScriptedFactory(raw())
    f = Fetcher(
        policy=POLICY,
        evidence=evidence_store(tmp_path),
        pacer=SpyPacer(),
        robots=allow_all_robots("www.ulta.ae"),
        transport_factory=direct,
        proxy_transport_factory=failing,
        secret_reader=FakeReader(),
    )
    with pytest.raises(TransportError, match="ERR_PROXY_CONNECTION_FAILED") as err:
        f.fetch(pdp(), ctx())
    assert PASSWORD not in str(err.value)
    with pytest.raises(SourceStoppedError, match="proxy error") as stopped:
        f.fetch(pdp(), ctx())
    assert PASSWORD not in str(stopped.value)
    assert USER not in str(stopped.value)
    assert failing.sends == 1
    assert direct.sends == []


def test_proxy_auth_407_stops_the_run(tmp_path: Path) -> None:
    proxy = ProxyFactory(raw(407, b"Proxy Authentication Required"), raw())
    f = proxied_fetcher(tmp_path, proxy)
    assert not f.fetch(pdp(), ctx()).ok
    assert f.stopped_sources() == {3: "http 407"}


def test_unreadable_secret_stops_the_run(tmp_path: Path) -> None:
    proxy = ProxyFactory(raw())
    f = proxied_fetcher(tmp_path, proxy, secret_reader=FakeReader(b"{" + PASSWORD.encode()))
    with pytest.raises(ProxyConfigError) as err:
        f.fetch(pdp(), ctx())
    assert PASSWORD not in str(err.value)
    assert "proxy error" in f.stopped_sources()[3]
    with pytest.raises(SourceStoppedError):
        f.fetch(pdp(), ctx())
    assert proxy.sent == []


def test_meter_is_seeded_with_prior_runs_bytes() -> None:
    config = ULTA.model_copy(
        update={"byte_cap": 1_000, "prior_bytes": 600, "page_reserve_bytes": 300}
    )
    meter = ProxyMeter.for_config(config)
    before = meter.exhausted
    assert not before
    meter.add(50, 60)  # 600 + 110 + 300 > 1000: no further page
    assert meter.exhausted
    usage = meter.usage()
    assert (usage.total, usage.allowance_used) == (110, 710)
    manifest = usage.manifest()
    assert (manifest["bytes_via_proxy"], manifest["prior_bytes"]) == (110, 600)
    assert manifest["allowance_used"] == 710
    assert meter.run_bytes == 110


def test_prior_bytes_is_required() -> None:
    fields = ULTA.model_dump()
    del fields["prior_bytes"]
    with pytest.raises(ValueError, match="prior_bytes"):
        ResidentialProxy.model_validate(fields)


def test_proxied_browser_fetch_keeps_allowed_captured_json(tmp_path: Path) -> None:
    # Regression (after #26): a rung-5 result with page-loaded JSON failed validation.
    captured = CapturedJson(url=HttpUrl("https://www.ulta.ae/graphql"), status=200, body=b"{}")
    page = raw(url=str(PDP)).model_copy(update={"captured_json": (captured,)})
    f = proxied_fetcher(tmp_path, ProxyFactory(page))
    request = pdp().model_copy(update={"capture_json": True})
    result = f.fetch(request, ctx())
    assert result.ladder_rung_used is LadderRung.PAID_PROXY
    assert result.captured_json == (captured,)
