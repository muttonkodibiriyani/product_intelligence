import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import HttpUrl

from fetch_helpers import make_ctx, make_source_context
from pi_core import FetchMethod, LadderRung, Locale
from pi_fetch.policy import (
    DIRECT_EGRESS,
    EgressProfile,
    Engine,
    FetchPolicy,
    LadderPolicyError,
    PaidProxyConfig,
    next_rung,
    permitted_rungs,
    plan,
)
from pi_fetch.types import FetchRequest, PayloadKind

GULF = EgressProfile(name="gulf-me-central1", proxy_url_env="PI_TEST_GULF_PROXY")
PAID = PaidProxyConfig(
    egress=EgressProfile(name="resi-ae", proxy_url_env="PI_TEST_RESI_PROXY"),
    owner_approval_ref="owner-decision-2026-10-01",
)
PERMITTED = [r for r in LadderRung if r.is_permitted]


def req(kind: PayloadKind = PayloadKind.HTML, *, render: bool = False) -> FetchRequest:
    return FetchRequest(
        url=HttpUrl("https://shop.example/p"), kind=kind, locale=Locale.EN, render=render
    )


def test_default_policy_allows_rungs_0_1_2_only() -> None:
    rungs = permitted_rungs(FetchPolicy(), make_source_context(LadderRung.PAID_PROXY))
    assert rungs == (LadderRung.SITE_DATA, LadderRung.PLAIN_HTTP, LadderRung.BROWSER)


def test_egress_variation_needs_runtime_profile() -> None:
    policy = FetchPolicy(egress_variation=GULF)
    rungs = permitted_rungs(policy, make_source_context(LadderRung.EGRESS_VARIATION))
    assert rungs[-1] is LadderRung.EGRESS_VARIATION
    assert LadderRung.STEALTH_BROWSER not in rungs


def test_paid_proxy_needs_both_owner_gates() -> None:
    with_cap = make_source_context(LadderRung.PAID_PROXY)
    without_cap = make_source_context(LadderRung.EGRESS_VARIATION)
    approved = FetchPolicy(egress_variation=GULF, paid_proxy=PAID)
    assert LadderRung.PAID_PROXY in permitted_rungs(approved, with_cap)
    assert LadderRung.PAID_PROXY not in permitted_rungs(approved, without_cap)
    assert LadderRung.PAID_PROXY not in permitted_rungs(FetchPolicy(), with_cap)


def test_escalation_path_skips_rung_3_and_stops() -> None:
    policy = FetchPolicy(egress_variation=GULF)
    sc = make_source_context(LadderRung.PAID_PROXY)
    path = [LadderRung.SITE_DATA]
    while (nxt := next_rung(path[-1], policy, sc)) is not None:
        path.append(nxt)
    assert path == [0, 1, 2, 4]


@given(
    max_allowed=st.sampled_from(PERMITTED),
    egress=st.booleans(),
    paid=st.booleans(),
    start=st.sampled_from(list(LadderRung)),
)
def test_ladder_never_offers_rung_3(
    max_allowed: LadderRung, egress: bool, paid: bool, start: LadderRung
) -> None:
    policy = FetchPolicy(
        egress_variation=GULF if egress else None, paid_proxy=PAID if paid else None
    )
    sc = make_source_context(max_allowed)
    rungs = permitted_rungs(policy, sc)
    assert LadderRung.STEALTH_BROWSER not in rungs
    assert all(r <= max_allowed for r in rungs)
    assert (LadderRung.PAID_PROXY in rungs) == (paid and max_allowed is LadderRung.PAID_PROXY)
    nxt = next_rung(start, policy, sc)
    assert nxt is None or (nxt.is_permitted and nxt > start)


@given(
    rung=st.sampled_from(PERMITTED),
    kind=st.sampled_from(list(PayloadKind)),
    render=st.booleans(),
    egress=st.booleans(),
    paid=st.booleans(),
)
def test_plan_never_resolves_rung_3(
    rung: LadderRung, kind: PayloadKind, render: bool, egress: bool, paid: bool
) -> None:
    policy = FetchPolicy(
        egress_variation=GULF if egress else None, paid_proxy=PAID if paid else None
    )
    ctx = make_ctx(rung, max_allowed=rung)
    try:
        route = plan(req(kind, render=render), ctx, policy)
    except LadderPolicyError:
        return
    assert route.rung is not LadderRung.STEALTH_BROWSER
    assert route.rung.is_permitted
    assert route.method.rung is route.rung
    assert route.rung >= rung
    if route.rung is LadderRung.PAID_PROXY:
        assert paid


@pytest.mark.parametrize(
    ("kind", "method"),
    [
        (PayloadKind.XML, FetchMethod.SITEMAP),
        (PayloadKind.JSON, FetchMethod.SITE_API),
        (PayloadKind.HTML, FetchMethod.EMBEDDED_JSON),
    ],
)
def test_rung_0_method_by_kind(kind: PayloadKind, method: FetchMethod) -> None:
    route = plan(req(kind), make_ctx(LadderRung.SITE_DATA), FetchPolicy())
    assert (route.rung, route.method, route.engine) == (LadderRung.SITE_DATA, method, Engine.HTTP)
    assert route.egress.name == DIRECT_EGRESS


def test_image_at_rung_0_goes_plain_http() -> None:
    route = plan(req(PayloadKind.IMAGE), make_ctx(LadderRung.SITE_DATA), FetchPolicy())
    assert route.method is FetchMethod.PLAIN_HTTP


def test_render_starts_at_browser() -> None:
    route = plan(req(render=True), make_ctx(LadderRung.PLAIN_HTTP), FetchPolicy())
    assert (route.rung, route.method, route.engine) == (
        LadderRung.BROWSER,
        FetchMethod.PLAYWRIGHT,
        Engine.BROWSER,
    )


def test_render_refused_when_cap_below_browser() -> None:
    ctx = make_ctx(LadderRung.PLAIN_HTTP, max_allowed=LadderRung.PLAIN_HTTP)
    with pytest.raises(LadderPolicyError, match="BROWSER"):
        plan(req(render=True), ctx, FetchPolicy())


def test_rung_4_uses_egress_profile_and_engine_by_render() -> None:
    policy = FetchPolicy(egress_variation=GULF)
    ctx = make_ctx(LadderRung.EGRESS_VARIATION)
    http = plan(req(), ctx, policy)
    browser = plan(req(render=True), ctx, policy)
    assert (http.engine, browser.engine) == (Engine.HTTP, Engine.BROWSER)
    assert http.egress == GULF
    assert http.method is FetchMethod.EGRESS_VARIATION


def test_rung_4_refused_without_profile() -> None:
    with pytest.raises(LadderPolicyError):
        plan(req(), make_ctx(LadderRung.EGRESS_VARIATION), FetchPolicy())


def test_rung_5_json_only_and_owner_gated() -> None:
    ctx = make_ctx(LadderRung.PAID_PROXY, max_allowed=LadderRung.PAID_PROXY)
    with pytest.raises(LadderPolicyError):
        plan(req(PayloadKind.JSON), ctx, FetchPolicy())
    policy = FetchPolicy(paid_proxy=PAID)
    route = plan(req(PayloadKind.JSON), ctx, policy)
    assert route.method is FetchMethod.RESIDENTIAL_PROXY
    assert route.egress == PAID.egress
    with pytest.raises(LadderPolicyError, match="JSON/API"):
        plan(req(PayloadKind.HTML), ctx, policy)


def test_egress_proxy_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert EgressProfile(name="direct").proxy_url() is None
    monkeypatch.delenv("PI_TEST_GULF_PROXY", raising=False)
    with pytest.raises(LadderPolicyError, match="not set"):
        GULF.proxy_url()
    monkeypatch.setenv("PI_TEST_GULF_PROXY", "http://127.0.0.1:3128")
    assert GULF.proxy_url() == "http://127.0.0.1:3128"
