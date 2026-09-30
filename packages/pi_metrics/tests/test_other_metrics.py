from __future__ import annotations

from decimal import Decimal

import pytest

from pi_core import AvailabilityState
from pi_dataset import Dataset, FieldStatus
from pi_metrics import (
    EVERYTHING,
    GapLabel,
    ProductFilter,
    assortment_gaps,
    availability,
    coverage,
    launches,
    promotions,
    reviews_summary,
)
from pi_metrics.fixtures import (
    DATES,
    A,
    B,
    C,
    D,
    metrics_dataset,
    rebuild,
    with_capabilities,
    with_dates,
    with_fields,
)
from pi_metrics.model import CaveatCode, Reason, Status
from pi_metrics.view import UnknownInput


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return metrics_dataset()


# promotions


def test_promo_share_and_items_deepest_first(ds: Dataset) -> None:
    result = promotions(ds, (A, B), EVERYTHING)
    assert result.status is Status.OK
    shares = {s.retailer: s.model_dump(mode="json") for s in result.data.retailers}
    assert (shares[A]["n"], shares[A]["onPromo"], shares[A]["share"]) == (6, 3, "50.0")
    assert shares[B]["share"] == "0.0"
    assert [(i.id, i.model_dump(mode="json")["statedPct"]) for i in result.data.items] == [
        ("p05", "33.3"),
        ("p04", "20.4"),
        ("p01", "10.0"),
    ]


def test_promo_depth_filter_and_date(ds: Dataset) -> None:
    deep = promotions(ds, (A,), EVERYTHING, min_pct=Decimal(20))
    assert [i.id for i in deep.data.items] == ["p05", "p04"]
    early = promotions(ds, (A,), EVERYTHING, on=DATES[0])
    assert [i.id for i in early.data.items] == ["p04", "p01"]


def test_promo_withheld_for_thin_partial_or_blocked(ds: Dataset) -> None:
    thin = promotions(ds, (A,), ProductFilter(ids=("p01",)))
    assert thin.reason is Reason.COHORT_TOO_SMALL
    assert thin.data.retailers[0].share is None
    partial = promotions(ds, (C,), EVERYTHING)
    assert partial.reason is Reason.RETAILER_PARTIAL
    assert [c.code for c in partial.caveats] == [CaveatCode.RETAILER_PARTIAL]
    assert promotions(ds, (D,), EVERYTHING).reason is Reason.RETAILER_BLOCKED


def test_promo_needs_the_capability_and_the_field(ds: Dataset) -> None:
    off = promotions(with_capabilities(ds, promotions=False), (A,), EVERYTHING)
    assert off.reason is Reason.CAPABILITY_OFF
    missing = promotions(with_fields(ds, regular=FieldStatus.NOT_COLLECTED), (A,), EVERYTHING)
    assert missing.reason is Reason.FIELD_NOT_COLLECTED
    assert missing.data.retailers == ()


# assortment


def test_a_gap_needs_a_reviewed_match_stage_to_be_missing(ds: Dataset) -> None:
    result = assortment_gaps(ds, B, A, EVERYTHING)
    assert result.status is Status.OK
    assert [(i.id, i.label) for i in result.data.items] == [("p12", GapLabel.MISSING)]
    assert result.data.total == 1
    assert [(b.brand, b.count) for b in result.data.by_brand] == [("Fixture Beauty", 1)]
    unreviewed = assortment_gaps(rebuild(ds, match_stage="proposed"), B, A, EVERYTHING)
    assert [i.label for i in unreviewed.data.items] == [GapLabel.UNMATCHED]


def test_no_gap_claim_against_a_partial_or_blocked_retailer(ds: Dataset) -> None:
    assert assortment_gaps(ds, C, A, EVERYTHING).reason is Reason.RETAILER_PARTIAL
    assert assortment_gaps(ds, D, A, EVERYTHING).reason is Reason.RETAILER_BLOCKED
    with pytest.raises(UnknownInput):
        assortment_gaps(ds, A, A, EVERYTHING)


def test_an_unobserved_catalogue_is_not_a_gap(ds: Dataset) -> None:
    window = ds.not_observed[0].model_copy(update={"retailer": B})
    changed = rebuild(ds.model_copy(update={"not_observed": (*ds.not_observed, window)}))
    result = assortment_gaps(changed, B, A, EVERYTHING)
    assert result.data.items == ()
    assert [(c.code, c.params["count"]) for c in result.caveats] == [
        (CaveatCode.NOT_OBSERVED_EXCLUDED, "1")
    ]


# availability


def test_availability_shares_over_observed_states(ds: Dataset) -> None:
    result = availability(ds, (A, B), EVERYTHING)
    assert result.status is Status.OK
    rows = {r.retailer: r.model_dump(mode="json") for r in result.data.retailers}
    assert rows[A]["denominator"] == 5
    assert (rows[A]["outOfStockShare"], rows[A]["lowStockShare"]) == ("40.0", "20.0")
    assert rows[A]["counts"]["removed"] == 1
    assert rows[B]["outOfStockShare"] == "0.0"


def test_availability_partial_and_off(ds: Dataset) -> None:
    result = availability(ds, (A, C), EVERYTHING)
    assert result.reason is Reason.RETAILER_PARTIAL
    thin = availability(ds, (A,), ProductFilter(ids=("p01",)))
    assert thin.data.retailers[0].reason is Reason.COHORT_TOO_SMALL
    off = availability(with_capabilities(ds, stock=False), (A,), EVERYTHING)
    assert off.reason is Reason.CAPABILITY_OFF


def test_removed_without_a_complete_run_is_not_observed(ds: Dataset) -> None:
    # Make shop_a's skincare catalogue unobserved on the last date: p06's removal is unconfirmed.
    window = ds.not_observed[0].model_copy(
        update={"retailer": A, "start": DATES[-1], "end": DATES[-1]}
    )
    changed = rebuild(ds.model_copy(update={"not_observed": (*ds.not_observed, window)}))
    result = availability(changed, (A,), EVERYTHING)
    assert result.data.retailers[0].counts[AvailabilityState.REMOVED] == 0
    assert CaveatCode.REMOVED_UNCONFIRMED in {c.code for c in result.caveats}


# launches


def test_a_launch_needs_a_complete_previous_run(ds: Dataset) -> None:
    result = launches(ds, (A, B, C), EVERYTHING)
    assert [(i.id, i.retailer, i.first_seen) for i in result.data.items] == [("p14", B, DATES[1])]
    assert [(c.code, c.params) for c in result.caveats] == [
        (CaveatCode.LAUNCHES_WITHHELD, {"count": "1"})
    ]
    assert launches(ds, (B,), EVERYTHING, since=DATES[-1]).data.items == ()


def test_launches_need_history(ds: Dataset) -> None:
    off = launches(with_capabilities(ds, history=False), (B,), EVERYTHING)
    assert off.reason is Reason.CAPABILITY_OFF
    assert launches(with_dates(ds, 1), (B,), EVERYTHING).reason is Reason.CAPABILITY_OFF


# reviews


def test_reviews_use_one_scale_and_weight_by_count(ds: Dataset) -> None:
    result = reviews_summary(ds, (A, B), EVERYTHING)
    rows = {r.retailer: r.model_dump(mode="json") for r in result.data.retailers}
    assert (rows[A]["n"], rows[A]["avgRating"], rows[A]["scale"]) == (13, "4.20", "5")
    assert rows[A]["ratingCount"] == 130
    assert [c.code for c in result.caveats] == [CaveatCode.RATING_SCALE_MIXED]


def test_reviews_off_or_thin(ds: Dataset) -> None:
    off = reviews_summary(with_capabilities(ds, ratings=False), (A,), EVERYTHING)
    assert off.reason is Reason.CAPABILITY_OFF
    gone = reviews_summary(with_fields(ds, rating=FieldStatus.NOT_COLLECTED), (A,), EVERYTHING)
    assert gone.reason is Reason.FIELD_NOT_COLLECTED
    thin = reviews_summary(ds, (A,), ProductFilter(ids=("p01",)))
    assert thin.data.retailers[0].avg_rating is None
    assert reviews_summary(ds, (D,), EVERYTHING).status is Status.NOT_ENOUGH_DATA


# coverage


def test_coverage_counts_collected_and_matched(ds: Dataset) -> None:
    rows = {r.id: r for r in coverage(ds, ()).data.retailers}
    assert (rows[A].product_count, rows[A].matched_count, rows[A].freshness) == (14, 10, DATES[-1])
    assert (rows[D].product_count, rows[D].freshness) == (0, None)
    assert [r.id for r in coverage(ds, (C,)).data.retailers] == [C]
