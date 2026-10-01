"""Rule-based price position and suggestions (docs/design/price-suggestions.md)."""

from __future__ import annotations

import statistics
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from metrics_fixture import A, B, metrics_dataset
from pi_metrics import Reason, Status, UnknownInput
from pi_metrics.gated import Gated
from pi_metrics.pricing import (
    RULE_LABEL,
    Aim,
    Band,
    BandStats,
    Basis,
    Ending,
    Guardrails,
    Outcome,
    PeerScope,
    PricePosition,
    PriceSuggestion,
    band_of,
    band_stats,
    percentile,
    price_position,
    price_suggestion,
    suggest_price,
)

STATS = BandStats(n=9, p25=Decimal(100), median=Decimal(120), p75=Decimal(140))
RAILS = Guardrails()
#: Words no pricing or gated output may use as a field name: no demand claim (ANL-16, UAT-31).
DEMAND_WORDS = (
    "demand",
    "elastic",
    "uplift",
    "volume",
    "revenue",
    "sales",
    "units_sold",
    "forecast",
    "predict",
    "margin",
    "profit",
)


def _ends_ok(price: Decimal, endings: tuple[Ending, ...]) -> bool:
    fraction = price % 1
    return (
        (Ending.WHOLE in endings and fraction == 0)
        or (Ending.HALF in endings and fraction == Decimal("0.5"))
        or (Ending.NINE in endings and fraction == 0 and price % 10 == 9)
    )


# ---- pure rules ----------------------------------------------------------------------------


@given(st.lists(st.integers(min_value=1, max_value=10_000_000), min_size=2, max_size=40))
def test_percentile_is_type_7(minors: list[int]) -> None:
    values = sorted(Decimal(m).scaleb(-2) for m in minors)
    q1, q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    assert percentile(values, Decimal("0.25")) == q1
    assert percentile(values, Decimal("0.5")) == q2
    assert percentile(values, Decimal("0.75")) == q3


def test_band_stats_needs_min_cohort() -> None:
    assert band_stats([Decimal(1)] * 4) is None
    stats = band_stats([Decimal(v) for v in (10, 20, 30, 40, 50)])
    assert stats == BandStats(n=5, p25=Decimal(20), median=Decimal(30), p75=Decimal(40))


@pytest.mark.parametrize(
    ("value", "band"),
    [("99.99", Band.ENTRY), ("100", Band.MID), ("140", Band.MID), ("140.01", Band.PREMIUM)],
)
def test_mid_is_inclusive(value: str, band: Band) -> None:
    assert band_of(Decimal(value), STATS) is band


@pytest.mark.parametrize(
    ("current", "target", "rails", "outcome", "price", "reaches"),
    [
        # In band already: nothing to do.
        ("120.00", Band.MID, RAILS, Outcome.ALREADY_IN_BAND, None, True),
        # Entry -> mid: 10 % of 95 allows 104.50; 100.00 is the first mid price.
        ("95.00", Band.MID, RAILS, Outcome.SUGGESTED, "100.00", True),
        # Entry -> mid, too far: 10 % of 90 stops at 99.00, short of p25 = 100.
        ("90.00", Band.MID, RAILS, Outcome.SUGGESTED, "99.00", False),
        # Mid -> premium: strictly above p75 = 140, so 140.50.
        ("135.00", Band.PREMIUM, RAILS, Outcome.SUGGESTED, "140.50", True),
        # Mid -> entry: strictly below p25 = 100, so 99.50.
        ("105.00", Band.ENTRY, RAILS, Outcome.SUGGESTED, "99.50", True),
        # Only x9 endings: 99.00.
        (
            "105.00",
            Band.ENTRY,
            Guardrails(endings=(Ending.NINE,)),
            Outcome.SUGGESTED,
            "99.00",
            True,
        ),
        # Premium -> mid: the nearest mid price is p75 itself (mid is inclusive).
        ("150.00", Band.MID, RAILS, Outcome.SUGGESTED, "140.00", True),
        # 99.50 is the first entry price: a 0.9 % change, under the 1 % minimum.
        ("100.40", Band.ENTRY, RAILS, Outcome.BELOW_MIN_CHANGE, None, False),
        # No x9 price within 2 % of 105.
        (
            "105.00",
            Band.ENTRY,
            Guardrails(max_change_pct=Decimal(2), endings=(Ending.NINE,)),
            Outcome.NO_ALLOWED_PRICE,
            None,
            False,
        ),
    ],
)
def test_suggest_table(
    current: str,
    target: Band,
    rails: Guardrails,
    outcome: Outcome,
    price: str | None,
    reaches: bool,
) -> None:
    got, chosen, landed, steps = suggest_price(
        Decimal(current), stats=STATS, target=target, guardrails=rails
    )
    assert (got, chosen, landed) == (outcome, None if price is None else Decimal(price), reaches)
    assert steps[0].params == {"band": band_of(Decimal(current), STATS).value}


def test_median_aim() -> None:
    _, chosen, landed, _ = suggest_price(
        Decimal("150.00"), stats=STATS, target=Band.MID, guardrails=RAILS, aim=Aim.MEDIAN
    )
    # The median (120) is out of reach: 135.00 is the 10 % floor and lands in mid.
    assert (chosen, landed) == (Decimal("135.00"), True)


bounds = st.integers(min_value=100, max_value=1_000_000).map(lambda m: Decimal(m).scaleb(-2))


@st.composite
def cases(draw: st.DrawFn) -> tuple[Decimal, BandStats, Band, Guardrails]:
    a, b, c = sorted(draw(bounds) for _ in range(3))
    stats = BandStats(n=5, p25=a, median=b, p75=c)
    current = draw(bounds)
    endings = draw(st.lists(st.sampled_from(list(Ending)), min_size=1, unique=True))
    rails = Guardrails(
        max_change_pct=Decimal(draw(st.integers(min_value=1, max_value=50))),
        min_change_pct=Decimal(draw(st.integers(min_value=0, max_value=5))),
        endings=tuple(endings),
    )
    return current, stats, draw(st.sampled_from(list(Band))), rails


@given(cases())
def test_suggestion_guardrails_hold(case: tuple[Decimal, BandStats, Band, Guardrails]) -> None:
    current, stats, target, rails = case
    outcome, chosen, reaches, _ = suggest_price(
        current, stats=stats, target=target, guardrails=rails
    )
    if outcome is not Outcome.SUGGESTED:
        assert chosen is None
        return
    assert chosen is not None
    change = abs(chosen - current) / current * 100
    assert rails.min_change_pct <= change <= rails.max_change_pct
    assert _ends_ok(chosen, rails.endings)
    assert reaches == (band_of(chosen, stats) is target)
    # Never moves away from the target band.
    order = [Band.ENTRY, Band.MID, Band.PREMIUM]
    before, after = order.index(band_of(current, stats)), order.index(band_of(chosen, stats))
    assert abs(order.index(target) - after) <= abs(order.index(target) - before)
    if reaches:
        again = suggest_price(chosen, stats=stats, target=target, guardrails=rails)
        assert again[0] is Outcome.ALREADY_IN_BAND


# ---- over the fixture ----------------------------------------------------------------------


def test_position_category_and_brand() -> None:
    m = price_position(metrics_dataset(), "p01", A)
    assert m.status is Status.OK
    assert m.data.label == RULE_LABEL
    category, brand = m.data.cohorts
    assert all(c.label == RULE_LABEL for c in m.data.cohorts)
    # Serum offers priced on the last date, minus p01: 13 at shop_a, 10 at shop_b (p11 unpriced,
    # p13 early), 1 at shop_c. All are measured in ml, so the basis is unit price.
    assert (category.key, category.basis, category.n, category.excluded) == (
        "serum",
        Basis.UNIT_PRICE,
        24,
        0,
    )
    assert brand.key == "fixture beauty / skincare"
    assert brand.n == 18
    assert category.value == "1.8000"
    assert category.band is not None
    assert m.cohort is not None
    assert m.cohort.n == 24


def test_competitors_drop_own_retailer() -> None:
    m = price_position(metrics_dataset(), "p01", A, peers=PeerScope.COMPETITORS)
    assert m.data.cohorts[0].n == 11


def test_unpriced_and_unknown() -> None:
    m = price_position(metrics_dataset(), "p14", A)
    assert (m.status, m.reason, m.data.price) == (Status.NOT_ENOUGH_DATA, Reason.NOT_IN_SCOPE, None)
    with pytest.raises(UnknownInput):
        price_position(metrics_dataset(), "nope", A)


def test_small_cohort_has_no_band() -> None:
    # p14 (makeup) at shop_b: the only makeup peer is p15 at shop_c.
    m = price_suggestion(metrics_dataset(), "p14", B, Band.ENTRY)
    assert (m.status, m.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)
    assert m.data.suggested is None
    assert m.data.label == RULE_LABEL
    assert m.cohort is not None


def test_suggestion_over_fixture() -> None:
    """The example in price-suggestions.md §6, pinned so the doc cannot drift."""
    m = price_suggestion(metrics_dataset(), "p01", A, Band.PREMIUM)
    assert m.status is Status.OK
    wire = m.model_dump(mode="json", by_alias=True)["data"]
    assert wire["label"] == RULE_LABEL
    assert (wire["suggested"]["amount"], wire["changePct"], wire["reachesBand"]) == (
        "99.00",
        "10.0",
        False,
    )
    assert [r["code"] for r in wire["rationale"]] == [
        "current_band",
        "target",
        "clamped",
        "rounded",
        "short_of_band",
    ]
    assert wire["rationale"][1]["params"]["point"] == "100.00"
    mid = price_suggestion(metrics_dataset(), "p01", A, Band.MID).data
    assert (mid.outcome, mid.suggested) == (Outcome.ALREADY_IN_BAND, None)


def _names(schema: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        found |= set(schema.get("properties", {}))
        for value in schema.values():
            found |= _names(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= _names(value)
    return found


@pytest.mark.parametrize("model", [PricePosition, PriceSuggestion, Gated])
def test_no_demand_fields(model: type[PricePosition | PriceSuggestion | Gated]) -> None:
    names = {n.casefold() for n in _names(model.model_json_schema(by_alias=False))}
    assert not [n for n in names for w in DEMAND_WORDS if w in n]
