from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_core.enums import QualityStatus
from pi_core.quality import (
    GATE_VERSION,
    Check,
    GateContext,
    Issue,
    ListingFacts,
    ObservationFacts,
    RunFacts,
    Severity,
    check_listing,
    check_observation,
    check_run,
    duplicate_issue,
    duplicate_keys,
    verdict,
)

CTX = GateContext(market_currency="AED", image_hosts=frozenset({"img.example.com"}))
IMG = "https://img.example.com/p/1.jpg"
T0 = datetime(2026, 10, 1, tzinfo=UTC)
WARN, QUAR = QualityStatus.WARNING, QualityStatus.QUARANTINED


def obs(**kw: Any) -> ObservationFacts:
    fields: dict[str, Any] = {"price_current": Decimal(100), "currency": "AED"}
    fields.update(kw)
    return ObservationFacts.model_validate(fields)


def listing(**kw: Any) -> ListingFacts:
    fields: dict[str, Any] = {
        "name": "Hydrating Serum",
        "brand": "Brand",
        "size_label": "30 ml",
        "size_value": Decimal(30),
        "variant_kind": "size",
        "image_urls": (IMG,),
        "gtin": "3614273069540",
        "has_price_observation": True,
    }
    fields.update(kw)
    return ListingFacts.model_validate(fields)


def checks(result: Any) -> set[Check]:
    return {issue.check for issue in result.issues}


def test_clean_records_are_accepted() -> None:
    assert check_observation(obs(), CTX).status is QualityStatus.ACCEPTED
    assert check_observation(obs(), CTX).issues == ()
    assert check_listing(listing(), CTX).status is QualityStatus.ACCEPTED
    assert check_observation(obs(), CTX).gate_version == GATE_VERSION


def test_stock_only_row_with_a_null_reason_is_accepted() -> None:
    row = obs(price_current=None, currency=None, field_state={"price_current": "unknown"})
    assert check_observation(row, CTX).status is QualityStatus.ACCEPTED


@pytest.mark.parametrize(
    ("kw", "check"),
    [
        ({"price_current": Decimal(0)}, Check.PRICE_NONPOSITIVE),
        ({"price_promo": Decimal(-1)}, Check.PRICE_NONPOSITIVE),
        ({"price_current": Decimal("0.5")}, Check.PRICE_IMPLAUSIBLE),
        ({"currency": None}, Check.PRICE_WITHOUT_CURRENCY),
        ({"currency": "USD"}, Check.CURRENCY_NOT_MARKET),
        ({"price_current": None}, Check.PRICE_NULL_WITHOUT_REASON),
        ({"price_regular_stated": Decimal(90)}, Check.REGULAR_BELOW_CURRENT),
        ({"price_current": Decimal(9), "price_regular_stated": Decimal(100)}, Check.DISCOUNT_GT_90),
        ({"last_accepted_price": Decimal(10)}, Check.PRICE_IMPLAUSIBLE),  # 100 vs 10: x10
        ({"last_accepted_price": Decimal(1000)}, Check.PRICE_IMPLAUSIBLE),  # /10
    ],
)
def test_observation_quarantine_rules(kw: dict[str, Any], check: Check) -> None:
    result = check_observation(obs(**kw), CTX)
    assert result.status is QualityStatus.QUARANTINED
    assert check in checks(result)


def test_discount_of_exactly_90_percent_passes() -> None:
    row = obs(price_current=Decimal(10), price_regular_stated=Decimal(100))
    assert check_observation(row, CTX).status is QualityStatus.ACCEPTED


def test_price_jump_just_inside_x10_passes() -> None:
    assert check_observation(obs(last_accepted_price=Decimal("10.01")), CTX).issues == ()


def test_peer_sigma_needs_enough_peers() -> None:
    peers = tuple(Decimal(p) for p in (100, 101, 99, 100, 102, 98))
    far = obs(price_current=Decimal(500), peer_prices=peers)
    assert Check.PRICE_IMPLAUSIBLE in checks(check_observation(far, CTX))
    few = obs(price_current=Decimal(500), peer_prices=peers[:4])
    assert check_observation(few, CTX).issues == ()
    flat = obs(price_current=Decimal(500), peer_prices=(Decimal(100),) * 6)  # sigma 0: no rule
    assert check_observation(flat, CTX).issues == ()


def test_was_price_is_a_warning_where_it_is_never_displayed() -> None:
    ctx = GateContext(market_currency="AED", was_price_displayed=False)
    row = obs(price_regular_stated=Decimal(120))
    assert check_observation(row, CTX).status is QualityStatus.ACCEPTED
    result = check_observation(row, ctx)
    assert result.status is QualityStatus.WARNING
    assert checks(result) == {Check.WAS_PRICE_PRESENT}


@pytest.mark.parametrize(
    ("kw", "check", "status"),
    [
        ({"has_price_observation": False}, Check.PRICE_MISSING, WARN),
        ({"size_value": None}, Check.SIZE_UNPARSED, WARN),
        ({"size_label": None, "size_value": None}, Check.SIZE_MISSING, WARN),
        ({"image_urls": ("",)}, Check.IMAGE_URL_BAD, WARN),
        (
            {"image_urls": ("http://img.example.com/1.jpg",)},
            Check.IMAGE_URL_BAD,
            WARN,
        ),
        (
            {"image_urls": ("https://other.example/1.jpg",)},
            Check.IMAGE_URL_BAD,
            WARN,
        ),
        (
            {"image_urls": ("https://img.example.com/1",)},
            Check.IMAGE_URL_BAD,
            WARN,
        ),
        ({"name": "Serum Ã©clat"}, Check.TEXT_JUNK, WARN),
        ({"brand": "Brand\x07"}, Check.TEXT_JUNK, WARN),
        ({"name": "Serum <b>new</b>"}, Check.TEXT_HTML, QUAR),
        ({"brand": "A &amp; B"}, Check.TEXT_HTML, QUAR),
        ({"gtin": None}, Check.GTIN_MISSING, QualityStatus.ACCEPTED),  # INFO only
    ],
)
def test_listing_rules(kw: dict[str, Any], check: Check, status: QualityStatus) -> None:
    result = check_listing(listing(**kw), CTX)
    assert check in checks(result)
    assert result.status is status


def test_shade_variant_without_size_is_expected() -> None:
    row = listing(size_label=None, size_value=None, variant_kind="shade")
    assert check_listing(row, CTX).issues == ()


def test_unknown_price_presence_is_not_a_missing_price() -> None:
    assert check_listing(listing(has_price_observation=None), CTX).issues == ()


def test_any_https_image_host_when_none_expected() -> None:
    ctx = GateContext(market_currency="AED")
    assert check_listing(listing(image_urls=("https://cdn.example.org/a.webp",)), ctx).issues == ()


def test_image_issue_counts_bad_urls() -> None:
    result = check_listing(listing(image_urls=(IMG, "", "ftp://x/1.png")), CTX)
    assert result.issues[0].detail == {"bad": "2"}


@given(st.text(max_size=40))
def test_issue_detail_holds_counts_only(text: str) -> None:
    row = listing(name=text, brand=text, size_label=text, size_value=None, image_urls=(text,))
    for issue in check_listing(row, CTX).issues:
        assert all(value.isdigit() for value in issue.detail.values())


@given(st.lists(st.sampled_from(list(Severity)), max_size=6))
def test_status_is_the_worst_severity(severities: list[Severity]) -> None:
    result = verdict(Issue(check=Check.STALE, severity=s) for s in severities)
    if Severity.QUARANTINE in severities:
        assert result.status is QualityStatus.QUARANTINED
    elif Severity.WARNING in severities:
        assert result.status is QualityStatus.WARNING
    else:
        assert result.status is QualityStatus.ACCEPTED


def test_duplicate_keys_ignore_identical_refetches() -> None:
    rows = [("a", "h1"), ("a", "h1"), ("b", "h1"), ("b", "h2"), ("c", "h3")]
    assert duplicate_keys(rows) == frozenset({"b"})
    assert duplicate_issue(2).severity is Severity.QUARANTINE


def test_run_count_drop_marks_partial() -> None:
    run = RunFacts(listings=79, last_good_listings=100, newest_observed_at=T0)
    result = check_run(run, as_of=T0, max_age=timedelta(days=1))
    assert result.partial
    assert checks(result) == {Check.COUNT_DROP}
    ok = RunFacts(listings=80, last_good_listings=100, newest_observed_at=T0)  # exactly 20%
    assert not check_run(ok, as_of=T0, max_age=timedelta(days=1)).partial
    first = RunFacts(listings=5, newest_observed_at=T0)
    assert check_run(first, as_of=T0, max_age=timedelta(days=1)).issues == ()


def test_run_empty_context_and_staleness() -> None:
    run = RunFacts(
        listings=10,
        fetched_by_context={"ctx-a": 10, "ctx-b": 0},
        newest_observed_at=T0 - timedelta(days=3),
    )
    result = check_run(run, as_of=T0, max_age=timedelta(days=2))
    assert not result.partial
    assert checks(result) == {Check.CONTEXT_EMPTY, Check.STALE}
    assert result.issues[0].detail == {"context": "ctx-b"}
    assert Check.STALE in checks(check_run(RunFacts(listings=0), as_of=T0, max_age=timedelta(1)))
