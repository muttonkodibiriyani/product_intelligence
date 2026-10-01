"""``pi_metrics.summary``: one context's catalogue at a glance (``/v1/summary``)."""

from __future__ import annotations

import copy
import sys
from decimal import Decimal
from typing import Any

import pytest

from pi_metrics import Reason, Status, summary
from pi_metrics.model import CaveatCode
from pi_metrics.summary import Section, Summary, default_context
from pi_metrics.view import UnknownInput
from v3_fixture import Doc, doc, load, offer, profile


def money(amount: str) -> dict[str, Any]:
    return {"amount": amount, "minor": int(Decimal(amount) * 100), "currency": "AED"}


def priced(d: Doc, product_id: str, context_id: str, price: str, regular: str | None) -> None:
    series = offer(d, product_id, context_id)["series"]
    series["price"][-1] = money(price)
    if series.get("regular") is not None:
        series["regular"][-1] = None if regular is None else money(regular)


def only_a(prices: list[str]) -> Doc:
    """``shop_a`` sells ``p01``.. with these prices on the latest date and no promotion."""
    d = doc()
    template = next(p for p in d["products"] if "shop_a" in p["offers"])
    products = []
    for k in range(1, len(prices) + 1):
        p = copy.deepcopy(template)
        p |= {"id": f"q{k:02}", "brand": "Brand X" if k % 2 else "brand x", "matches": []}
        p["offers"] = {"shop_a": p["offers"]["shop_a"]}
        products.append(p)
    d["products"] = products
    for p, price in zip(products, prices, strict=True):
        priced(d, p["id"], "shop_a", price, price)
    return d


def data(d: Doc, context: str | None = "shop_a") -> Summary:
    return summary(load(d), context).data


def test_percentiles_are_nearest_rank_observed_prices() -> None:
    d = only_a(["10.00", "20.00", "30.00", "40.00", "50.00", "60.00"])
    s = data(d)
    assert s.median_price is not None
    assert s.median_price.amount == "30.00"  # lower middle of an even count
    assert s.ladder is not None
    (row,) = s.ladder
    assert [m.amount for m in (row.min, row.p25, row.p50, row.p75, row.max)] == [
        "10.00",
        "20.00",
        "30.00",
        "50.00",
        "60.00",
    ]
    assert (s.products, s.priced, s.categories, s.retailer) == (6, 6, 1, "shop_a")
    assert s.currency == "AED"


def test_fold_equal_brands_count_once_under_their_least_raw_form() -> None:
    d = only_a(["10.00"] * 7)
    offer(d, "q07", "shop_a")["series"]["price"][-1] = None
    s = data(d)
    assert (s.brands, s.products, s.priced) == (1, 7, 6)  # n counts priced products only
    assert s.brand_price is not None
    assert [(b.brand, b.n, b.median.amount) for b in s.brand_price] == [("Brand X", 6, "10.00")]


def test_no_promotion_is_a_zero_share_not_a_missing_one() -> None:
    s = data(only_a(["10.00"] * 6))
    assert s.promo_share_pct == 0
    assert s.top_discounts == ()
    assert s.promo_depth is not None
    assert s.promo_depth.cells == ((0, 0, 0, 0, 0),)


def test_promotion_depths_fall_in_half_open_bands() -> None:
    d = only_a(["10.00"] * 6)
    for pid, price in (("q01", "9.00"), ("q02", "8.00"), ("q03", "5.00"), ("q04", "9.99")):
        priced(d, pid, "shop_a", price, "10.00")
    s = data(d)
    assert s.promo_share_pct is not None
    assert round(s.promo_share_pct, 1) == Decimal("66.7")
    assert s.promo_depth is not None
    assert s.promo_depth.cells == ((1, 1, 1, 0, 1),)  # 0.1 / 10 / 20 / 50
    assert s.top_discounts is not None
    assert [t.id for t in s.top_discounts] == ["q03", "q02", "q01", "q04"]
    assert all(t.image is None for t in s.top_discounts)


def test_an_unpublished_regular_price_is_not_counted_as_no_promotion() -> None:
    d = only_a(["10.00"] * 7)
    for pid in ("q01", "q02"):
        priced(d, pid, "shop_a", "10.00", None)
    priced(d, "q03", "shop_a", "5.00", "10.00")
    s = data(d)
    assert s.promo_share_pct == 20  # 1 of the 5 with both prices
    priced(d, "q04", "shop_a", "10.00", None)
    s = data(d)
    assert s.promo_share_pct is None  # 4 with both prices are too few
    assert [(w.section, w.reason) for w in s.withheld] == [
        (Section.PROMOTIONS, Reason.COHORT_TOO_SMALL)
    ]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda d: d["meta"]["capabilities"].update(promotions=False), Reason.CAPABILITY_OFF),
        (lambda d: d["meta"]["fields"].update(regular="not_collected"), Reason.FIELD_NOT_COLLECTED),
        (lambda d: d["meta"]["fields"].pop("regular"), Reason.FIELD_NOT_COLLECTED),
    ],
)
def test_promotions_are_withheld_never_zero_without_the_regular_price(
    change: Any, reason: Reason
) -> None:
    d = only_a(["10.00"] * 6)
    change(d)
    m = summary(load(d), "shop_a")
    s = m.data
    assert (s.promo_share_pct, s.promo_depth, s.top_discounts) == (None, None, None)
    assert [(w.section, w.reason) for w in s.withheld] == [(Section.PROMOTIONS, reason)]
    assert m.status is Status.OK
    assert s.median_price is not None


def test_too_few_prices_withhold_every_price_figure() -> None:
    m = summary(load(only_a(["10.00"] * 4)), "shop_a")
    s = m.data
    assert (m.status, m.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)
    assert (s.median_price, s.ladder, s.brand_price, s.price_hist) == (None, None, None, None)
    assert {w.section: w.reason for w in s.withheld} == {
        Section.PRICES: Reason.COHORT_TOO_SMALL,
        Section.PROMOTIONS: Reason.COHORT_TOO_SMALL,
        Section.RATINGS: Reason.COHORT_TOO_SMALL,
    }
    assert s.products == 4


def test_a_blocked_retailer_has_an_empty_summary() -> None:
    m = summary(load(doc()), "shop_d")
    assert (m.status, m.reason) == (Status.NOT_ENOUGH_DATA, Reason.RETAILER_BLOCKED)
    s = m.data
    assert (s.products, s.priced, s.brands, s.categories, s.category_mix) == (None,) * 5
    assert {w.reason for w in m.data.withheld} == {Reason.RETAILER_BLOCKED}
    assert len(m.data.withheld) == len(Section)


def test_a_partial_retailer_is_summarised_with_a_caveat() -> None:
    m = summary(load(doc()), "shop_c")
    assert CaveatCode.RETAILER_PARTIAL in {c.code for c in m.caveats}


def test_early_samples_are_left_out_and_counted() -> None:
    m = summary(load(doc()), "shop_b")
    early = [c for c in m.caveats if c.code is CaveatCode.EARLY_EXCLUDED]
    assert [c.params for c in early] == [{"count": "1"}]
    assert "p13" not in {t.id for t in m.data.top_discounts or ()}


def test_the_default_context_has_the_most_collected_offers() -> None:
    ds = load(doc())
    assert default_context(ds).id == "shop_a"
    assert summary(ds, None).data.retailer == "shop_a"


def test_an_unknown_context_is_an_input_error() -> None:
    with pytest.raises(UnknownInput):
        summary(load(doc()), "shop_z")


def test_a_profile_outside_the_list_is_not_applicable() -> None:
    d = profile(doc(), "beauty")
    d["meta"]["profile"]["name"] = d["meta"]["vertical"] = "hardware"
    m = summary(load(d), "shop_a")
    assert m.reason is Reason.NOT_APPLICABLE


def test_the_histogram_covers_every_price_on_log_bins() -> None:
    prices = ["1.00", "2.50", "9.99", "10.00", "99.00", "1000.00"]
    hist = data(only_a(prices)).price_hist
    assert hist is not None
    assert (hist.edges[0], hist.edges[-1]) == ("1.00", "1000.00")
    assert len(hist.counts) == len(hist.edges) - 1 == 20
    assert sum(hist.counts) == len(prices)
    assert hist.counts[-1] == 1  # the last bin is closed
    edges = [Decimal(e) for e in hist.edges]
    assert edges == sorted(set(edges))


def test_one_price_everywhere_has_no_histogram() -> None:
    assert data(only_a(["10.00"] * 6)).price_hist is None


def test_ratings_use_the_most_common_scale_and_are_sampled_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = only_a([f"{10 + k}.00" for k in range(8)])
    offer(d, "q08", "shop_a")["rating"] = {"average": "8.00", "scale": "10", "count": 3}
    offer(d, "q07", "shop_a")["rating"] = {"average": "4.00", "scale": "5", "count": 0}
    m = summary(load(d), "shop_a")
    rp = m.data.rating_price
    assert rp is not None
    assert (rp.n, rp.scale, rp.sampled, len(rp.points)) == (6, "5", False, 6)
    assert round(rp.rated_pct, 1) == Decimal("75.0")
    assert [c.params for c in m.caveats if c.code is CaveatCode.RATING_SCALE_MIXED] == [
        {"retailer": "shop_a", "count": "1"}
    ]
    monkeypatch.setattr(sys.modules["pi_metrics.summary"], "RATING_POINTS", 3)
    first = summary(load(d), "shop_a").data.rating_price
    again = summary(load(d), "shop_a").data.rating_price
    assert first is not None
    assert first.sampled
    assert len(first.points) == 3
    assert first == again
    shown = [Decimal(p.price) for p in first.points]
    assert shown == sorted(shown)


def test_ratings_off_are_withheld() -> None:
    d = only_a(["10.00"] * 6)
    d["meta"]["capabilities"]["ratings"] = False
    s = data(d)
    assert s.rating_price is None
    assert (Section.RATINGS, Reason.CAPABILITY_OFF) in {(w.section, w.reason) for w in s.withheld}


def test_ratings_not_collected_are_withheld() -> None:
    d = only_a(["10.00"] * 6)
    d["meta"]["fields"]["rating"] = "not_collected"
    reasons = {w.section: w.reason for w in data(d).withheld}
    assert reasons[Section.RATINGS] is Reason.FIELD_NOT_COLLECTED


def test_rows_are_capped_and_ordered_by_size(monkeypatch: pytest.MonkeyPatch) -> None:
    d = only_a(["10.00"] * 12)
    for p in d["products"][:5]:
        p["category"] = ["makeup", "lips"]
    for p in d["products"][5:]:
        p["brand"] = "Other"
    s = data(d)
    assert s.ladder is not None
    assert [(r.category, r.n) for r in s.ladder] == [("skincare", 7), ("makeup", 5)]
    assert [(c.category, c.n) for c in s.category_mix or ()] == [
        (("skincare", "serum"), 7),
        (("makeup", "lips"), 5),
    ]
    monkeypatch.setattr(sys.modules["pi_metrics.summary"], "CATEGORY_ROWS", 1)
    monkeypatch.setattr(sys.modules["pi_metrics.summary"], "MIX_ROWS", 1)
    s = data(d)
    assert s.ladder is not None
    assert s.promo_depth is not None
    assert [r.category for r in s.ladder] == list(s.promo_depth.category) == ["skincare"]
    assert len(s.category_mix or ()) == 1
    assert s.categories == 2


def test_products_are_the_offers_observed_on_the_latest_date() -> None:
    """Reviewer's #104 point 3: an offer seen only on an earlier date is not counted."""
    d = only_a(["10.00"] * 8)
    gone = offer(d, "q08", "shop_a")["series"]
    gone["price"][-1] = None
    if gone.get("availability") is not None:
        gone["availability"][-1] = None
    unpriced = offer(d, "q07", "shop_a")["series"]
    unpriced["price"][-1] = None
    assert unpriced.get("availability") is not None
    unpriced["availability"][-1] = "in_stock"
    s = data(d)
    assert (s.products, s.priced) == (7, 6)  # q08 unseen; q07 seen without a price
    assert sum(c.n for c in s.category_mix or ()) == 7
