"""``category_compare``: category-to-category prices over both full catalogues (no matching).

The v3 fixture on its latest date: shop_a prices 14 ``skincare`` products (seven at 50.00, then
70, 80, 90, 95.50, 100, 105.25, 110); shop_b prices 11 (five at 50.00, six at 100.00) plus p14
(``makeup``, not an exporter code, so ``other``), with p13 early and p11 unpriced that day.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pi_dataset import DatasetV3, MoneyValue
from pi_metrics import (
    MIN_COHORT,
    CaveatCode,
    Reason,
    Status,
    UnknownInput,
    category_compare,
    summary,
)
from pi_metrics.category_compare import UNMAPPED_CAP, CategoryComparison
from pi_metrics.model import Cheaper, Metric
from pi_metrics.taxonomy import Level, Unmapped
from v3_fixture import doc, load, offer, profile

A, B, C, D = "shop_a", "shop_b", "shop_c", "shop_d"


def aed(amount: str) -> MoneyValue:
    return MoneyValue.of(Decimal(amount), "AED")


def categorised(categories: dict[str, list[str]], d: dict[str, Any] | None = None) -> DatasetV3:
    d = doc() if d is None else d
    for product in d["products"]:
        product["category"] = categories.get(product["id"], product["category"])
    return load(d)


def codes_only() -> DatasetV3:
    """Today's served file: every category is the exporter's code alone, no breadcrumb."""
    d = doc()
    for product in d["products"]:
        product["category"] = product["category"][:1]
    return load(d)


def run(
    ds: DatasetV3, level: Level = Level.BUCKET, a: str = A, b: str = B
) -> Metric[CategoryComparison]:
    return category_compare(ds, a, b, level)


def test_each_side_gets_its_own_ladder_and_the_medians_give_the_gap() -> None:
    result = run(load(doc()))
    assert result.status is Status.OK
    assert result.as_of.isoformat() == "2026-09-30"
    row = result.data.rows[0]
    assert (row.key, row.label.en, row.shared) == ("skincare", "Skincare", True)
    base, other = row.base, row.other
    assert (base.n, base.too_few, base.reason) == (14, False, None)
    assert (base.min, base.p25, base.median, base.p75, base.max) == (
        aed("50.00"),
        aed("50.00"),
        aed("50.00"),
        aed("95.50"),
        aed("110.00"),
    )
    assert base.mean == aed("71.48")  # 1000.75 / 14, half-even
    assert (other.n, other.median, other.mean) == (11, aed("100.00"), aed("77.27"))
    assert row.gap is not None
    assert (row.gap.amount, row.gap.pct, row.gap.cheaper) == (
        aed("50.00"),
        Decimal(100),
        Cheaper.BASE,
    )
    assert result.cohort is not None
    assert result.cohort.n == 1


def test_a_thin_cell_is_too_few_with_its_n_and_no_figures_never_zero() -> None:
    row = next(r for r in run(load(doc())).data.rows if r.key == "other")
    assert (row.base.n, row.other.n, row.shared) == (0, 1, False)
    for cell in (row.base, row.other):
        assert cell.too_few
        assert cell.reason is Reason.COHORT_TOO_SMALL
        assert {cell.median, cell.mean, cell.p25, cell.p75, cell.min, cell.max} == {None}
    assert (row.gap, row.gap_reason) == (None, Reason.COHORT_TOO_SMALL)


def test_one_thin_side_withholds_the_gap_but_keeps_the_other_ladder() -> None:
    ds = categorised({p: ["lips"] for p in ("p01", "p02", "p03", "p04", "p05", "p06")})
    row = next(r for r in run(ds).data.rows if r.key == "lips")
    assert (row.base.n, row.other.n) == (6, 6)
    thin = categorised({p: ["lips"] for p in ("p01", "p02", "p03", "p04")})
    row = next(r for r in run(thin).data.rows if r.key == "lips")
    assert row.base.too_few
    assert row.other.too_few
    ds = categorised({p: ["lips"] for p in ("p01", "p02", "p03", "p04", "p05", "p12")})
    row = next(r for r in run(ds).data.rows if r.key == "lips")
    assert (row.base.n, row.other.n) == (6, 5)
    assert row.gap is not None
    ds = categorised({p: ["lips"] for p in ("p01", "p02", "p03", "p04", "p12", "p13")})
    row = next(r for r in run(ds).data.rows if r.key == "lips")
    assert (row.base.n, row.other.n) == (6, 4)  # p12 isn't at shop_b; p13 is early there
    assert row.base.median is not None
    assert row.other.too_few
    assert (row.gap, row.gap_reason) == (None, Reason.COHORT_TOO_SMALL)


def test_no_comparable_category_is_not_enough_data() -> None:
    result = run(categorised({p: [f"c{p}"] for p in ("p01", "p02")}, _thin()))
    assert result.status is Status.NOT_ENOUGH_DATA
    assert result.reason is Reason.COHORT_TOO_SMALL
    assert result.data.rows
    assert all(r.gap is None for r in result.data.rows)


def _thin() -> dict[str, Any]:
    d = doc()
    d["products"] = [p for p in d["products"] if p["id"] in {"p01", "p02", "p03"}]
    return d


def test_every_priced_product_is_in_exactly_one_cell_per_side() -> None:
    result = run(load(doc()))
    for side in ("base", "other"):
        cells = [getattr(r, side) for r in result.data.rows]
        coverage = getattr(result.data.coverage, side)
        assert sum(c.n for c in cells) == coverage.priced
    assert (result.data.coverage.base.priced, result.data.coverage.other.priced) == (14, 12)
    assert result.data.coverage.other.other_bucket == 1
    assert result.data.coverage.other.other_pct == Decimal(100) / 12


def test_early_and_unpriced_offers_are_left_out() -> None:
    result = run(load(doc()))
    assert [c.code for c in result.caveats] == [CaveatCode.EARLY_EXCLUDED]
    assert result.caveats[0].params == {"count": "1"}
    d = doc()
    offer(d, "p01", B)["series"]["price"][-1] = None
    assert run(load(d)).data.coverage.other.priced == 11
    # An early offer not seen on the latest date isn't counted as excluded, as in /summary.
    d = doc()
    unseen = offer(d, "p13", B)["series"]
    unseen["price"][-1] = None
    if unseen.get("availability"):
        unseen["availability"][-1] = None
    assert run(load(d)).caveats == ()
    assert CaveatCode.EARLY_EXCLUDED not in {c.code for c in summary(load(d), B).caveats}


def test_an_offer_off_the_market_currency_is_not_priced() -> None:
    ds = load(doc())
    product = next(p for p in ds.products if p.id == "p01")
    usd = (None,) * (len(ds.meta.dates) - 1) + (MoneyValue.of(Decimal("10.00"), "USD"),)
    foreign = product.offers[B].model_copy(
        update={
            "currency": "USD",
            "series": product.offers[B].series.model_copy(update={"price": usd}),
        }
    )
    swapped = product.model_copy(update={"offers": product.offers | {B: foreign}})
    ds = ds.model_copy(
        update={"products": tuple(swapped if p.id == "p01" else p for p in ds.products)}
    )
    assert run(ds).data.coverage.other.priced == 11


def test_rows_lead_with_the_best_compared_category() -> None:
    ds = categorised({p: ["lips"] for p in ("p01", "p02", "p03", "p04", "p05", "p06")})
    rows = run(ds).data.rows
    # lips: 6 and 6; skincare: 8 and 5; other: 0 and 1. Ranked by the smaller side.
    assert [(r.key, r.base.n, r.other.n) for r in rows[:3]] == [
        ("lips", 6, 6),
        ("skincare", 8, 5),
        ("other", 0, 1),
    ]
    # Every bucket is a row, the empty ones last by key, each tooFew with n = 0.
    assert [r.key for r in rows[3:]] == [
        "body",
        "cheek",
        "concealer",
        "eyes",
        "foundation",
        "fragrance",
    ]
    assert {(r.base.n, r.other.n, r.base.too_few, r.shared) for r in rows[3:]} == {
        (0, 0, True, False)
    }


def test_a_blocked_side_withholds_every_figure_and_gap() -> None:
    result = run(load(doc()), b=D)
    assert result.status is Status.NOT_ENOUGH_DATA
    assert result.reason is Reason.RETAILER_BLOCKED
    for row in result.data.rows:
        assert row.other.reason is Reason.RETAILER_BLOCKED
        assert row.other.median is None
        assert (row.gap, row.gap_reason) == (None, Reason.RETAILER_BLOCKED)


def test_a_partial_side_is_a_caveat() -> None:
    result = run(load(doc()), b=C)
    assert CaveatCode.RETAILER_PARTIAL in {c.code for c in result.caveats}


def test_the_same_retailer_twice_or_an_unknown_one_is_refused() -> None:
    with pytest.raises(UnknownInput):
        run(load(doc()), b=A)
    with pytest.raises(UnknownInput):
        run(load(doc()), b="shop_z")


def test_another_vertical_is_not_applicable() -> None:
    result = run(load(profile(doc(), "food_menu")))
    assert (result.status, result.reason) == (Status.NOT_ENOUGH_DATA, Reason.NOT_APPLICABLE)
    assert result.data.rows == ()


# ---------------------------------------------------------------- level=common


def test_codes_alone_serve_buckets_and_say_common_has_no_breadcrumb() -> None:
    ds = codes_only()
    bucket = run(ds)
    assert [r.key for r in bucket.data.rows][:2] == ["skincare", "other"]
    assert len(bucket.data.rows) == 9
    assert CaveatCode.BREADCRUMB_MISSING not in {c.code for c in bucket.caveats}
    common = run(ds, Level.COMMON)
    assert common.data.rows == ()
    # Nothing to read, not too few: a client keyed on ``reason`` must not say "too few".
    assert (common.status, common.reason) == (Status.NOT_ENOUGH_DATA, Reason.FIELD_NOT_COLLECTED)
    assert [(c.code, c.params) for c in common.caveats[1:]] == [
        (CaveatCode.BREADCRUMB_MISSING, {"retailer": A, "count": "14"}),
        (CaveatCode.BREADCRUMB_MISSING, {"retailer": B, "count": "12"}),
    ]
    cov = common.data.coverage
    assert (cov.base.mapped, cov.base.unmapped, cov.base.no_breadcrumb) == (0, 14, 14)
    assert [(u.retailer, u.path, u.reason, u.n) for u in common.data.unmapped] == [
        (A, (), Unmapped.NO_BREADCRUMB, 14),
        (B, (), Unmapped.NO_BREADCRUMB, 12),
    ]


def test_common_places_by_breadcrumb_and_lists_what_it_cannot() -> None:
    crumbs = {
        "p01": ["eyes", "Skincare", "Eye Cream"],  # the exporter's eye-before-skin order
        "p02": ["eyes", "Skincare", "Eye Cream"],
        "p03": ["skincare", "Skincare", "Mystery"],
        "p04": ["skincare", "Skincare", "Mystery"],
    }
    result = run(categorised(crumbs), Level.COMMON)
    eye = next(r for r in result.data.rows if r.key == "eye_care")
    assert (eye.label.en, eye.base.n, eye.other.n) == ("Eye care", 2, 2)
    assert [(u.retailer, u.path, u.reason, u.n) for u in result.data.unmapped] == [
        (A, ("Skincare", "Mystery"), Unmapped.NO_RULE, 2),
        (B, ("Skincare", "Mystery"), Unmapped.NO_RULE, 2),
        (B, (), Unmapped.NO_BREADCRUMB, 1),  # p14's code alone
    ]
    assert result.data.unmapped_paths == 3
    unmapped = [c.params for c in result.caveats if c.code is CaveatCode.UNMAPPED_CATEGORY]
    assert unmapped == [{"retailer": A, "count": "2"}, {"retailer": B, "count": "2"}]
    by_bucket = run(categorised(crumbs))
    skincare = next(r for r in by_bucket.data.rows if r.key == "skincare")
    assert skincare.base.n == 14  # the eye creams are skincare, whatever their code


def test_the_unmapped_list_is_capped_most_frequent_first() -> None:
    d = doc()
    for i, product in enumerate(d["products"]):
        product["category"] = ["skincare", f"Zz {i:02d}"]
    d["products"][1]["category"] = d["products"][0]["category"]
    result = run(load(d), Level.COMMON)
    assert result.data.unmapped[0].n == 2
    assert len(result.data.unmapped) == min(UNMAPPED_CAP, result.data.unmapped_paths)


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.sampled_from(["lips", "eyes", "skincare", "body", "other"]), min_size=16, max_size=16
    ),
    st.randoms(use_true_random=False),
)
def test_cells_partition_each_side_and_order_never_matters(codes: list[str], rnd: Any) -> None:
    d = doc()
    for product, code in zip(d["products"], codes, strict=True):
        product["category"] = [code]
    first = run(load(d))
    rnd.shuffle(d["products"])
    assert run(load(d)) == first
    for side in ("base", "other"):
        cells = [getattr(r, side) for r in first.data.rows]
        assert sum(c.n for c in cells) == getattr(first.data.coverage, side).priced
        for cell in cells:
            assert cell.too_few == (cell.n < MIN_COHORT)
            assert (cell.median is None) == cell.too_few
            ladder = (cell.min, cell.p25, cell.median, cell.p75, cell.max)
            amounts = [m.decimal() for m in ladder if m is not None]
            assert amounts == sorted(amounts)
            assert len(amounts) in {0, 5}
