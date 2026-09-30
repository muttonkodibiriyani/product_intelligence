from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pi_dataset import Dataset, DecidedBy, MoneyValue, RetailerStatus
from pi_metrics import EVERYTHING, Cheaper, GroupBy, ProductFilter, compare, gap
from pi_metrics.fixtures import DATES, A, B, C, D, edge, metrics_dataset, rebuild, with_saudi_shop
from pi_metrics.model import CaveatCode, Excluded, Reason, Status
from pi_metrics.view import UnknownInput


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return metrics_dataset()


def aed(amount: str) -> MoneyValue:
    return MoneyValue.of(Decimal(amount), "AED")


def test_every_row_carries_its_single_exclusion_reason(ds: Dataset) -> None:
    rows = {r.id: r for r in compare(ds, A, B, EVERYTHING).data.rows}
    assert {pid: r.excluded_reason for pid, r in rows.items() if not r.counted} == {
        "p07": Excluded.MATCH_UNREVIEWED,
        "p08": Excluded.MATCH_REJECTED,
        "p09": Excluded.MATCH_NOT_EXACT,
        "p10": Excluded.SIZE_MISMATCH,
        "p11": Excluded.UNPRICED,
        "p12": Excluded.NOT_OFFERED,
        "p13": Excluded.EARLY,
        "p14": Excluded.NOT_OFFERED,
        "p16": Excluded.NO_MATCH,
    }
    assert "p15" not in rows  # offered by neither side
    assert all(r.excluded_reason is None and r.gap is not None for r in rows.values() if r.counted)


def test_summary_over_the_exact_counted_pairs(ds: Dataset) -> None:
    result = compare(ds, A, B, EVERYTHING)
    assert result.status is Status.OK
    assert result.reason is None
    assert result.cohort is not None
    assert result.cohort.n == 6
    summary = result.data.summary
    assert summary is not None
    wire = summary.model_dump(mode="json")
    assert wire["median_gap_pct"] == "2.4"
    assert wire["mean_gap_pct"] == "4.5"
    assert summary.cheaper_counts == {A: 3, B: 2}
    assert summary.equal_count == 1
    assert summary.basket.base == aed("580.75")
    assert summary.basket.other == aed("600.00")
    assert result.as_of == DATES[-1]
    assert result.caveats[0].code is CaveatCode.EARLY_EXCLUDED


def test_the_gap_direction_is_explicit() -> None:
    dearer = gap(aed("90.00"), aed("100.00"))
    assert dearer.amount == aed("10.00")
    assert dearer.cheaper is Cheaper.BASE
    assert gap(aed("100.00"), aed("90.00")).cheaper is Cheaper.OTHER
    assert gap(aed("100.00"), aed("100.00")).cheaper is Cheaper.EQUAL
    assert gap(aed("80.00"), aed("100.00")).pct == Decimal(25)


def test_an_earlier_date_uses_that_dates_prices(ds: Dataset) -> None:
    result = compare(ds, A, B, EVERYTHING, on=DATES[0])
    rows = {r.id: r for r in result.data.rows}
    assert rows["p11"].counted  # b was priced then
    assert rows["p05"].base_price == aed("120.00")
    assert result.cohort is not None
    assert result.cohort.n == 7
    assert result.as_of == DATES[0]


def test_no_transitivity_through_a_third_retailer(ds: Dataset) -> None:
    p16 = {r.id: r for r in compare(ds, A, B, EVERYTHING).data.rows}["p16"]
    assert p16.excluded_reason is Excluded.NO_MATCH
    assert {r.id: r for r in compare(ds, A, C, EVERYTHING).data.rows}["p16"].counted


def test_below_the_cohort_minimum_the_summary_is_withheld(ds: Dataset) -> None:
    result = compare(ds, A, B, ProductFilter(ids=("p01", "p02", "p03", "p07")))
    assert result.status is Status.NOT_ENOUGH_DATA
    assert result.reason is Reason.COHORT_TOO_SMALL
    assert result.data.summary is None
    assert len(result.data.rows) == 4  # rows are always shown


def test_only_unreviewed_candidates_say_so(ds: Dataset) -> None:
    result = compare(ds, A, B, ProductFilter(ids=("p07", "p12", "p16")))
    assert result.reason is Reason.MATCHES_UNREVIEWED


def test_nothing_comparable_is_no_match(ds: Dataset) -> None:
    assert compare(ds, A, B, ProductFilter(ids=("p12", "p16"))).reason is Reason.NO_MATCH
    assert compare(ds, A, B, ProductFilter(ids=("nope",))).reason is Reason.NO_MATCH


def test_only_rejected_or_inexact_candidates_are_too_small(ds: Dataset) -> None:
    result = compare(ds, A, B, ProductFilter(ids=("p08", "p09")))
    assert result.reason is Reason.COHORT_TOO_SMALL


def test_a_blocked_side_withholds_everything(ds: Dataset) -> None:
    result = compare(ds, A, D, EVERYTHING, group_by=GroupBy.BRAND)
    assert result.reason is Reason.RETAILER_BLOCKED
    assert result.data.summary is None
    assert result.data.sides.other.reason is Reason.RETAILER_BLOCKED
    assert result.data.groups
    assert {g.reason for g in result.data.groups} == {Reason.RETAILER_BLOCKED}


def test_a_partial_side_is_a_caveat_not_a_block(ds: Dataset) -> None:
    result = compare(ds, A, C, EVERYTHING)
    assert result.reason is Reason.COHORT_TOO_SMALL
    assert [c.code for c in result.caveats] == [CaveatCode.RETAILER_PARTIAL]
    assert result.data.sides.other.status is RetailerStatus.PARTIAL
    assert result.data.sides.other.reason is Reason.RETAILER_PARTIAL


def test_different_market_currencies_are_never_compared(ds: Dataset) -> None:
    result = compare(with_saudi_shop(ds), A, "shop_e", EVERYTHING, group_by=GroupBy.BRAND)
    assert result.reason is Reason.CURRENCY_MISMATCH
    assert {g.reason for g in result.data.groups} == {Reason.CURRENCY_MISMATCH}


def test_sides_report_what_each_retailer_contributes(ds: Dataset) -> None:
    sides = compare(ds, A, B, EVERYTHING).data.sides
    assert (sides.base.retailer, sides.base.observed, sides.base.only_here) == (A, 14, 1)
    assert (sides.other.retailer, sides.other.observed, sides.other.only_here) == (B, 12, 1)
    assert sides.base.counted == sides.other.counted == 6
    assert sides.base.reason is None


def test_groups_apply_the_cohort_rule_each(ds: Dataset) -> None:
    by_category = compare(ds, A, B, EVERYTHING, group_by=GroupBy.CATEGORY).data
    assert by_category.group_by is GroupBy.CATEGORY
    groups = {g.key: g for g in by_category.groups}
    assert groups["skincare"].status is Status.OK
    assert groups["skincare"].summary == by_category.summary
    assert groups["makeup"].reason is Reason.NO_MATCH
    by_brand = compare(ds, A, B, EVERYTHING, group_by=GroupBy.BRAND).data.groups
    assert [(g.key, g.n, g.reason) for g in by_brand] == [
        ("Fixture Beauty", 3, Reason.COHORT_TOO_SMALL),
        ("Sample Labs", 3, Reason.COHORT_TOO_SMALL),
    ]
    assert compare(ds, A, B, EVERYTHING).data.groups == ()


def test_an_auto_approved_edge_counts(ds: Dataset) -> None:
    # Approved by auto-accept is counted like a human approval (design §8.3).
    p01 = ds.products[0]
    auto = edge(A, B).model_copy(update={"decided_by": DecidedBy.AUTO})
    changed = ds.model_copy(
        update={"products": (p01.model_copy(update={"matches": (auto,)}), *ds.products[1:])}
    )
    row = compare(rebuild(changed), A, B, ProductFilter(ids=("p01",))).data.rows[0]
    assert row.counted


def test_a_locked_edge_counts_and_a_proposed_one_does_not(ds: Dataset) -> None:
    rows = {r.id: r for r in compare(ds, A, B, EVERYTHING).data.rows}
    assert rows["p03"].counted  # locked
    assert not rows["p07"].counted  # proposed


@pytest.mark.parametrize(
    ("base", "other", "on"),
    [(A, A, None), (A, "nope", None), ("nope", A, None), (A, B, DATES[0].replace(year=2020))],
)
def test_bad_input_is_a_request_error(ds: Dataset, base: str, other: str, on: date | None) -> None:
    with pytest.raises(UnknownInput):
        compare(ds, base, other, EVERYTHING, on=on)
