"""Per-brand gaps of one focus retailer against every other (lane D).

The fixture's focus is shop A (supported). B is supported, C partial (skincare unobserved), D
blocked. On the last date: p01-p06, p10 and p11 have an accepted A-B edge; p07's is proposed,
p08's rejected, p09's family; p12 is A only; p13's B offer is an early sample; p14 is B only and
p15 C only (makeup); p16 has A, B and C with accepted A-C and B-C edges and no A-B edge.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

import v3_fixture
from metrics_fixture import A, B, C, D, metrics_dataset, rebuild
from pi_core.enums import MatchClass, ReviewState
from pi_dataset import Dataset, RetailerStatus
from pi_metrics.assortment import GapLabel
from pi_metrics.brand_gaps import (
    BrandGaps,
    CrawlWindow,
    CrossLink,
    ShopCount,
    Side,
    brand_gaps,
)
from pi_metrics.model import EVERYTHING, CaveatCode, ProductFilter, Reason, Status
from pi_metrics.view import UnknownInput


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return metrics_dataset()


def sides(data: BrandGaps) -> dict[Side, list[tuple[str, str]]]:
    found: dict[Side, list[tuple[str, str]]] = {}
    for row in data.items:
        found.setdefault(row.side, []).append((row.retailer, row.id))
    return {side: sorted(rows) for side, rows in found.items()}


def with_status(ds: Dataset, **status: RetailerStatus) -> Dataset:
    retailers = tuple(
        r.model_copy(update={"status": status.get(r.id, r.status)}) for r in ds.meta.retailers
    )
    return rebuild(ds, retailers=retailers)


def test_every_focus_listing_takes_its_strongest_link(ds: Dataset) -> None:
    result = brand_gaps(ds, A, EVERYTHING)
    assert result.status is Status.OK
    found = sides(result.data)
    assert found[Side.BOTH] == [
        (A, p) for p in ("p01", "p02", "p03", "p04", "p05", "p06", "p10", "p11", "p16")
    ]
    # Proposed exact, and an approved edge to an early sample: evidence, never "both".
    assert found[Side.UNCONFIRMED] == [(A, "p07"), (A, "p13")]
    assert found[Side.FAMILY] == [(A, "p09")]
    # A rejected edge is no link at all.
    assert found[Side.FOCUS_ONLY] == [(A, "p08"), (A, "p12")]
    totals = result.data.totals
    assert (totals.focus_n, totals.both, totals.unconfirmed, totals.family, totals.focus_only) == (
        14,
        9,
        2,
        1,
        2,
    )
    assert totals.both_by == (ShopCount(retailer=B, n=8), ShopCount(retailer=C, n=1))


def test_nothing_is_transitive(ds: Dataset) -> None:
    """p16: A-C and B-C accepted say nothing about A-B; the grouping is unconfirmed evidence."""
    (row,) = [
        r for r in brand_gaps(ds, A, EVERYTHING).data.items if r.id == "p16" and r.retailer == A
    ]
    assert (row.side, row.both_at, row.not_at) == (Side.BOTH, (C,), ())


def test_not_at_counts_only_supported_shops_with_a_complete_run(ds: Dataset) -> None:
    data = brand_gaps(ds, A, EVERYTHING).data
    # Only B is supported; C (partial) and D (blocked) are withheld, never a 0.
    assert data.totals.not_at == (ShopCount(retailer=B, n=2),)
    assert {r.id for r in data.items if B in r.not_at} == {"p08", "p12"}
    assert [(w.retailer, w.reason) for w in data.withheld] == [
        (C, Reason.RETAILER_PARTIAL),
        (D, Reason.RETAILER_BLOCKED),
    ]
    assert data.focus_only_label is GapLabel.UNMATCHED  # some compared shop is withheld
    assert data.absence_label is GapLabel.MISSING


def test_a_shop_that_becomes_supported_gets_its_count_with_no_code_change(ds: Dataset) -> None:
    """Statuses are read from the view: C supported, but its skincare run is not observed, so
    only listings in observed categories could be absent there (none in this fixture)."""
    data = brand_gaps(with_status(ds, shop_c=RetailerStatus.SUPPORTED), A, EVERYTHING).data
    assert [s.retailer for s in data.totals.not_at] == [B, C]
    assert data.totals.not_at[1].n == 0
    uncovered = rebuild(
        with_status(ds, shop_c=RetailerStatus.SUPPORTED),
        retailers=tuple(
            r.model_copy(update={"status": RetailerStatus.SUPPORTED}) if r.id == C else r
            for r in ds.meta.retailers
        ),
    )
    without_window = uncovered.model_copy(
        update={"not_observed": tuple(w for w in uncovered.not_observed if w.retailer != C)}
    )
    cleared = brand_gaps(without_window, A, EVERYTHING).data
    # p16 has an accepted A-C edge: never absent at C.
    assert {r.id for r in cleared.items if C in r.not_at} == {
        "p01",
        "p02",
        "p03",
        "p04",
        "p05",
        "p06",
        "p07",
        "p08",
        "p09",
        "p10",
        "p11",
        "p12",
        "p13",
    }


def test_others_only_lists_listings_with_no_link_to_the_focus(ds: Dataset) -> None:
    data = brand_gaps(ds, A, EVERYTHING).data
    assert sides(data)[Side.OTHERS_ONLY] == [(B, "p08"), (B, "p14"), (C, "p15")]
    assert data.totals.others_only == 3
    assert data.totals.others_by == (ShopCount(retailer=B, n=2), ShopCount(retailer=C, n=1))


def test_others_only_is_none_when_the_focus_is_not_supported(ds: Dataset) -> None:
    data = brand_gaps(ds, C, EVERYTHING).data
    assert data.totals.others_only is None
    assert Side.OTHERS_ONLY not in sides(data)
    assert (C, Reason.RETAILER_PARTIAL) in [(w.retailer, w.reason) for w in data.withheld]


def test_an_unobserved_focus_catalogue_is_not_an_absence(ds: Dataset) -> None:
    window = ds.not_observed[0].model_copy(update={"retailer": A, "categories": ("makeup",)})
    changed = rebuild(ds.model_copy(update={"not_observed": (*ds.not_observed, window)}))
    result = brand_gaps(changed, A, EVERYTHING)
    assert sides(result.data)[Side.OTHERS_ONLY] == [(B, "p08")]
    assert (CaveatCode.NOT_OBSERVED_EXCLUDED, "2") in [
        (c.code, c.params.get("count")) for c in result.caveats
    ]


def test_cross_links_from_the_match_file_are_evidence_never_both(ds: Dataset) -> None:
    links = (
        CrossLink(
            a_product="p12",
            a_retailer=A,
            b_product="p14",
            b_retailer=B,
            match_class=MatchClass.EXACT,
            review_state=ReviewState.APPROVED,  # not merged by the view: not a clique
        ),
        CrossLink(
            a_product="p15",
            a_retailer=C,
            b_product="p08",
            b_retailer=A,
            match_class=MatchClass.FAMILY,
            review_state=ReviewState.PROPOSED,
        ),
        CrossLink(
            a_product="p08",
            a_retailer=A,
            b_product="p14",
            b_retailer=B,
            match_class=MatchClass.EXACT,
            review_state=ReviewState.REJECTED,
        ),
    )
    found = sides(brand_gaps(ds, A, EVERYTHING, links=links).data)
    assert (A, "p12") in found[Side.UNCONFIRMED]
    assert (A, "p08") in found[Side.FAMILY]
    assert found[Side.OTHERS_ONLY] == [(B, "p08")]


def test_shares_need_a_cohort(ds: Dataset) -> None:
    rows = {r.brand: r for r in brand_gaps(ds, A, EVERYTHING).data.by_brand}
    big = rows["Fixture Beauty"]
    assert big.focus_n >= 5
    assert big.focus_only_share == Decimal(big.focus_only) / big.focus_n * 100
    thin = brand_gaps(ds, A, ProductFilter(ids=("p12",))).data.totals
    assert (thin.focus_n, thin.focus_only_share, thin.share_reason) == (
        1,
        None,
        Reason.COHORT_TOO_SMALL,
    )


def test_brand_rows_add_up_to_the_totals(ds: Dataset) -> None:
    data = brand_gaps(ds, A, EVERYTHING).data
    for field in ("focus_n", "both", "unconfirmed", "family", "focus_only", "others_only"):
        assert sum(getattr(r, field) for r in data.by_brand) == getattr(data.totals, field)
    assert sum(len(r.not_at) and r.not_at[0].n for r in data.by_brand) == data.totals.not_at[0].n


def test_the_basis_names_every_side_and_its_window(ds: Dataset) -> None:
    plain = brand_gaps(ds, A, EVERYTHING).data.sides
    assert [(s.retailer, s.status, s.window) for s in plain] == [
        (A, RetailerStatus.SUPPORTED, None),
        (B, RetailerStatus.SUPPORTED, None),
        (C, RetailerStatus.PARTIAL, None),
        (D, RetailerStatus.BLOCKED, None),
    ]
    assert plain[0].listings == 14

    def window_of(_: object, retailer_id: str, /) -> CrawlWindow | None:
        return (
            CrawlWindow(start=date(2026, 9, 28), end=date(2026, 9, 30))
            if retailer_id == A
            else None
        )

    windows = brand_gaps(ds, A, EVERYTHING, window_of=window_of).data.sides
    assert windows[0].window == CrawlWindow(start=date(2026, 9, 28), end=date(2026, 9, 30))


def test_an_unreviewed_match_stage_never_says_missing(ds: Dataset) -> None:
    data = brand_gaps(rebuild(ds, match_stage="proposed"), A, EVERYTHING).data
    assert (data.focus_only_label, data.absence_label) == (GapLabel.UNMATCHED, GapLabel.UNMATCHED)


def test_unknown_focus_is_rejected(ds: Dataset) -> None:
    with pytest.raises(UnknownInput):
        brand_gaps(ds, "nope", EVERYTHING)


def test_the_same_inputs_give_the_same_answer(ds: Dataset) -> None:
    assert brand_gaps(ds, A, EVERYTHING) == brand_gaps(ds, A, EVERYTHING)


def test_a_profile_it_does_not_apply_to_is_not_applicable() -> None:
    other = v3_fixture.load(v3_fixture.profile(v3_fixture.doc(), "hardware"))
    result = brand_gaps(other, A, EVERYTHING)
    assert (result.status, result.reason) == (Status.NOT_ENOUGH_DATA, Reason.NOT_APPLICABLE)
    assert (result.data.items, result.data.by_brand) == ((), ())
    assert result.data.totals.not_at == (ShopCount(retailer=B, n=0),)


def test_an_edge_between_two_other_shops_never_links_them_to_the_focus(ds: Dataset) -> None:
    """B's p14 and C's p15 matched to each other: both are still not at A."""
    link = CrossLink(
        a_product="p14",
        a_retailer=B,
        b_product="p15",
        b_retailer=C,
        match_class=MatchClass.EXACT,
        review_state=ReviewState.APPROVED,
    )
    found = sides(brand_gaps(ds, A, EVERYTHING, links=(link,)).data)
    assert found[Side.OTHERS_ONLY] == [(B, "p08"), (B, "p14"), (C, "p15")]
