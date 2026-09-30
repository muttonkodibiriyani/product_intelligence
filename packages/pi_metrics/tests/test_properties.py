"""Properties of the metric rules that hold for any prices, not just the fixture's."""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from metrics_fixture import A, B, metrics_dataset
from pi_dataset import MoneyValue
from pi_metrics import (
    EVERYTHING,
    MIN_COHORT,
    Cheaper,
    GroupBy,
    PairRow,
    ProductFilter,
    assortment_gaps,
    availability,
    compare,
    coverage,
    gap,
    launches,
    price_index,
    promotions,
    reviews_summary,
)
from pi_metrics.compare import summarise
from pi_metrics.model import fixed

cents = st.integers(min_value=1, max_value=10_000_000)


def aed(minor: int) -> MoneyValue:
    return MoneyValue.of(Decimal(minor).scaleb(-2), "AED")


@given(cents, cents)
def test_gap_is_exact_and_names_the_cheaper_side(base: int, other: int) -> None:
    g = gap(aed(base), aed(other))
    assert g.amount.minor == other - base
    assert g.pct * aed(base).decimal() / 100 == aed(other - base).decimal() or base != other
    expected = Cheaper.EQUAL if base == other else Cheaper.BASE if base < other else Cheaper.OTHER
    assert g.cheaper is expected
    assert (g.pct > 0) == (other > base)


def row(i: int, base: int, other: int) -> PairRow:
    return PairRow(
        id=f"p{i}",
        name=f"P{i}",
        brand="b",
        category=("c",),
        base_price=aed(base),
        other_price=aed(other),
        gap=gap(aed(base), aed(other)),
        counted=True,
        excluded_reason=None,
    )


@given(st.lists(st.tuples(cents, cents), min_size=0, max_size=12), st.randoms())
def test_summary_needs_the_cohort_and_ignores_row_order(
    prices: list[tuple[int, int]], rnd: random.Random
) -> None:
    rows = [row(i, b, o) for i, (b, o) in enumerate(prices)]
    summary = summarise(tuple(rows), "x", "y")
    if len(rows) < MIN_COHORT:
        assert summary is None
        return
    assert summary is not None
    shuffled = rows[:]
    rnd.shuffle(shuffled)
    assert summarise(tuple(shuffled), "x", "y") == summary
    assert summary.n == len(rows)
    assert sum(summary.cheaper_counts.values()) + summary.equal_count == len(rows)
    assert summary.basket.base.minor == sum(b for b, _ in prices)
    lo, hi = min(r.gap.pct for r in rows if r.gap), max(r.gap.pct for r in rows if r.gap)
    assert lo <= summary.median_gap_pct <= hi
    assert lo <= summary.mean_gap_pct <= hi


@given(st.decimals(min_value=-1000, max_value=1000, allow_nan=False, places=4))
def test_one_decimal_rounds_half_away_from_zero(value: Decimal) -> None:
    text = fixed(1)(value)
    assert abs(Decimal(text) - value) <= Decimal("0.05")
    assert fixed(1)(Decimal("2.25")) == "2.3"
    assert fixed(1)(Decimal("-2.25")) == "-2.3"


def test_filters_are_case_insensitive_and_combine() -> None:
    ds = metrics_dataset()

    def ids(where: ProductFilter) -> list[str]:
        return [p.id for p in ds.products if where.matches(p)]

    assert len(ids(EVERYTHING)) == len(ds.products)
    assert ids(ProductFilter(brands=("sample labs",))) == ["p02", "p04", "p06"]
    assert ids(ProductFilter(categories=("MAKEUP",))) == ["p14", "p15"]
    assert ids(ProductFilter(categories=("serum",), brands=("Sample Labs",), ids=("p02",))) == [
        "p02"
    ]
    assert ids(ProductFilter(ids=("p02",), brands=("Fixture Beauty",))) == []


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_no_float_and_camel_case_on_the_wire() -> None:
    ds = metrics_dataset()
    results: list[BaseModel] = [
        compare(ds, A, B, EVERYTHING, group_by=GroupBy.BRAND),
        price_index(ds, A, B, EVERYTHING),
        promotions(ds, (), EVERYTHING),
        assortment_gaps(ds, B, A, EVERYTHING),
        availability(ds, (), EVERYTHING),
        launches(ds, (), EVERYTHING),
        reviews_summary(ds, (), EVERYTHING),
        coverage(ds, ()),
    ]
    for result in results:
        wire = json.loads(result.model_dump_json())
        assert "asOf" in wire
        values = list(_walk(wire))
        assert not [v for v in values if isinstance(v, float)]
        # Field names are camelCase; snake_case keys are data (enum values, source keys).
        assert "cohort_too_small" not in wire
