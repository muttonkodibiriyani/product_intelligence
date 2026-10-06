from __future__ import annotations

from decimal import Decimal

import pytest

from metrics_fixture import (
    IN,
    OUT,
    A,
    B,
    D,
    edge,
    metrics_dataset,
    offer,
    product,
    with_capabilities,
    with_fields,
)
from pi_core import AvailabilityState, ReviewState
from pi_dataset import Dataset, DatasetV3, Product, Size
from pi_dataset.models import FieldStatus
from pi_metrics import view
from pi_metrics.insights import (
    CATEGORIES_LISTED,
    PICKS_LISTED,
    LadderBasis,
    Policy,
    ValueBasis,
    ValuePicks,
    insights,
    policy,
)
from pi_metrics.model import CaveatCode, Reason, Status
from pi_metrics.view import UnknownInput


def _with(products: list[Product]) -> Dataset:
    ds = metrics_dataset()
    return Dataset.model_validate(
        ds.model_copy(update={"products": tuple(products)}).model_dump(by_alias=True)
    )


def _pair(pid: str, brand: str, a: str, b: str, size: str = "50", **kw: ReviewState) -> Product:
    state = kw.get("state", ReviewState.APPROVED)
    return product(
        pid,
        {A: offer(A, [a] * 3, size=size), B: offer(B, [b] * 3, size=size)},
        [edge(A, B, state)],
        brand=brand,
    )


@pytest.fixture(scope="module")
def priced() -> Dataset:
    """Undercut: B cheaper on 5 of 5. Parity: equal on 4 of 5. Mixed. Small: 2 pairs."""
    rows = [
        *(_pair(f"u{n}", "Undercut", "100.00", "91.00", "90") for n in range(5)),
        *(_pair(f"p{n}", "Parity", "100.00", "100.00") for n in range(4)),
        _pair("p4", "Parity", "100.00", "103.00"),
        *(_pair(f"m{n}", "Mixed", "100.00", p) for n, p in enumerate(["90.00", "110.00"] * 3)),
        *(_pair(f"s{n}", "Small", "100.00", "50.00", "30") for n in range(2)),
        _pair("r0", "Unreviewed", "100.00", "80.00", state=ReviewState.PROPOSED),
    ]
    return _with(rows)


def test_policy_needs_the_share_on_one_side() -> None:
    assert policy(0, 4, 1) is Policy.OTHER_CHEAPER  # 80% exactly
    assert policy(0, 3, 1) is Policy.MIXED  # 75%
    assert policy(4, 0, 1) is Policy.BASE_CHEAPER
    assert policy(0, 1, 4) is Policy.PARITY
    assert policy(0, 0, 0) is Policy.MIXED


def test_brand_policy_over_counted_pairs_only(priced: Dataset) -> None:
    p = insights(priced, A, B).data.pricing
    assert p.status is Status.OK
    assert p.n == 18  # the proposed pair is not counted
    assert p.unreviewed == 1
    brands = {b.brand: b for b in p.brands}
    assert set(brands) == {"Undercut", "Parity", "Mixed"}
    assert brands["Undercut"].policy is Policy.OTHER_CHEAPER
    assert brands["Undercut"].median_gap_pct == Decimal(-9)
    assert (brands["Undercut"].other_cheaper, brands["Undercut"].n) == (5, 5)
    assert brands["Parity"].policy is Policy.PARITY
    assert (brands["Parity"].equal, brands["Parity"].base_cheaper) == (4, 1)
    assert brands["Mixed"].policy is Policy.MIXED
    assert p.suppressed_brands == 1
    assert p.brands[0].brand == "Undercut"  # most negative median first


def test_gap_by_measure_suppresses_small_sizes(priced: Dataset) -> None:
    p = insights(priced, A, B).data.pricing
    sizes = {(s.value, s.unit): s for s in p.sizes}
    assert set(sizes) == {("50", "ml"), ("90", "ml")}
    assert sizes[("90", "ml")].n == 5
    assert sizes[("50", "ml")].n == 11
    assert p.suppressed_sizes == 1  # 30 ml, two pairs


def test_only_unreviewed_pairs_give_no_pricing_rows() -> None:
    ds = _with(
        [_pair(f"r{n}", "Brand", "100.00", "90.00", state=ReviewState.PROPOSED) for n in range(6)]
    )
    p = insights(ds, A, B).data.pricing
    assert (p.status, p.reason) == (Status.NOT_ENOUGH_DATA, Reason.MATCHES_UNREVIEWED)
    assert (p.n, p.unreviewed, p.brands, p.sizes) == (0, 6, (), ())


def _sizes(pid: str, brand: str, name: str, prices: dict[str, str]) -> list[Product]:
    return [
        product(f"{pid}-{v}", {A: offer(A, [p] * 3, size=v)}, brand=brand).model_copy(
            update={"name": name}
        )
        for v, p in prices.items()
    ]


@pytest.fixture(scope="module")
def ladders() -> Dataset:
    steps = []
    for n in range(4):  # 30 -> 50 -> 100 ml, each larger size cheaper per ml
        steps += _sizes(
            f"ok{n}", "Ladder", f"Cream {n}", {"30": "60.00", "50": "90.00", "100": "150.00"}
        )
    steps += _sizes("bad", "Ladder", "Gel", {"30": "60.00", "50": "110.00"})  # 2.00 -> 2.20/ml
    steps += _sizes("far", "Ladder", "Water", {"100": "18.00", "125": "52.00"})  # +131%: held out
    steps += _sizes("dup", "Ladder", "Twin", {"30": "60.00"})
    steps += [
        p.model_copy(update={"id": "dup-30b"})
        for p in _sizes("dup", "Ladder", "Twin", {"30": "70.00"})
    ]
    steps += _sizes("dup2", "Ladder", "Twin", {"50": "80.00"})
    return _with(steps)


def test_ladder_counts_steps_and_lists_the_exceptions(ladders: Dataset) -> None:
    a = next(lad for lad in insights(ladders, A, B).data.ladders if lad.retailer == A)
    assert a.reason is None
    assert (a.steps, a.not_cheaper, a.held_out) == (9, 1, 1)
    (bad,) = a.exceptions
    assert (bad.name, bad.smaller_value, bad.larger_value) == ("Gel", "30", "50")
    assert bad.unit_change_pct == Decimal(10)
    assert bad.basis is LadderBasis.NAME
    # 30->50: 2.00 -> 1.80 (-10%), 50->100: 1.80 -> 1.50 (-16.7%), Gel +10%: median -10
    assert a.median_saving_pct == Decimal(10)


def test_a_ladder_below_the_cohort_or_blocked_is_withheld(ladders: Dataset) -> None:
    by = {lad.retailer: lad for lad in insights(ladders, A, B).data.ladders}
    assert by[B].reason is Reason.COHORT_TOO_SMALL
    assert by[B].median_saving_pct is None
    assert by[D].reason is Reason.RETAILER_BLOCKED


def test_the_retailers_family_id_groups_sizes_under_different_names(ladders: Dataset) -> None:
    doc = view.as_v3(ladders).model_dump(mode="json", by_alias=True)
    for p in doc["products"]:
        if p["id"].startswith(("bad-", "ok0-")):
            p["name"] = f"Renamed {p['id']}"
            p["offers"][A]["content"] = {"captured": [], "family": p["id"].split("-")[0]}
    a = next(
        lad
        for lad in insights(DatasetV3.model_validate(doc), A, B).data.ladders
        if lad.retailer == A
    )
    assert (a.steps, a.not_cheaper) == (9, 1)
    assert a.exceptions[0].basis is LadderBasis.FAMILY
    assert a.exceptions[0].family == "bad"


def test_partial_retailers_are_flagged() -> None:
    m = insights(metrics_dataset(), A, B)
    assert m.status is Status.OK
    assert [c.code for c in m.caveats] == [CaveatCode.RETAILER_PARTIAL]


def test_off_profile_or_capability_answers_not_enough_data() -> None:
    m = insights(with_capabilities(metrics_dataset(), sizes=False), A, B)
    assert (m.status, m.reason) == (Status.NOT_ENOUGH_DATA, Reason.CAPABILITY_OFF)
    assert m.data.ladders == ()


def test_unknown_or_equal_contexts_are_refused() -> None:
    with pytest.raises(UnknownInput):
        insights(metrics_dataset(), A, A)
    with pytest.raises(UnknownInput):
        insights(metrics_dataset(), A, "nowhere")


def _stocked(pid: str, brand: str, last: AvailabilityState | None) -> Product:
    return product(pid, {A: offer(A, ["10.00"] * 3, stock=[IN, IN, last])}, brand=brand)


def test_brand_stockouts_are_counts_apart_from_brands_the_source_reports_unavailable() -> None:
    rows = [
        *(_stocked(f"w{n}", "Whole", OUT) for n in range(5)),  # every listing out: unavailable
        *(_stocked(f"t{n}", "Tiny", OUT) for n in range(2)),  # unavailable, too few to list
        *(_stocked(f"h{n}", "Half", OUT) for n in range(6)),
        *(_stocked(f"h{n}i", "Half", IN) for n in range(6)),
        _stocked("h-unseen", "Half", None),  # not observed: neither out nor observed
        *(_stocked(f"b{n}", "Big", OUT) for n in range(7)),
        _stocked("b-in", "Big", IN),
        *(_stocked(f"f{n}", "Few", OUT) for n in range(2)),
        _stocked("f-in", "Few", IN),
        _stocked("gone", "Gone", AvailabilityState.REMOVED),  # not an observed stock state
    ]
    by = {s.retailer: s for s in insights(_with(rows), A, B).data.stockouts}
    a = by[A]
    assert a.reason is None
    assert [(r.brand, r.out_of_stock, r.observed) for r in a.brands] == [
        ("Big", 7, 8),
        ("Half", 6, 12),
    ]
    assert (a.qualifying, a.suppressed) == (2, 1)  # Few: two out, not listed
    assert (a.listed, a.with_stock, a.out_of_stock) == (32, 30, 15)  # 7 + 6 + 2, partly out only
    assert (a.unavailable_brands, a.unavailable_listings) == (2, 7)  # Whole and Tiny
    assert [(r.brand, r.out_of_stock, r.observed) for r in a.unavailable] == [("Whole", 5, 5)]
    assert (by[B].brands, by[B].listed, by[B].unavailable) == ((), 0, ())
    assert by[D].reason is Reason.RETAILER_BLOCKED
    assert (by[D].listed, by[D].with_stock, by[D].unavailable_brands) == (0, 0, 0)


def test_stockouts_without_the_stock_capability_say_so() -> None:
    m = insights(with_capabilities(metrics_dataset(), stock=False), A, B)
    assert {s.reason for s in m.data.stockouts} == {Reason.CAPABILITY_OFF, Reason.RETAILER_BLOCKED}
    assert {(s.listed, s.with_stock, s.out_of_stock, s.unavailable) for s in m.data.stockouts} == {
        (0, 0, 0, ())
    }


def test_a_blocked_side_counts_no_pair() -> None:
    """Six approved A-D pairs with D blocked: no counted pair, no cohort, nothing withheld."""
    rows = [
        product(
            f"d{n}",
            {A: offer(A, ["100.00"] * 3), D: offer(D, ["90.00"] * 3)},
            [edge(A, D, ReviewState.APPROVED)],
            brand="Undercut",
        )
        for n in range(6)
    ]
    m = insights(_with(rows), A, D)
    p = m.data.pricing
    assert (p.status, p.reason) == (Status.NOT_ENOUGH_DATA, Reason.RETAILER_BLOCKED)
    assert (p.n, p.suppressed_brands, p.suppressed_sizes) == (0, 0, 0)
    assert (p.brands, p.sizes) == ((), ())
    assert m.cohort is not None
    assert m.cohort.n == 0


def test_only_observed_stock_states_are_counted() -> None:
    """Unknown, blocked, removed and unobserved (null) listings are in neither count."""
    unseen = (AvailabilityState.UNKNOWN, AvailabilityState.BLOCKED, AvailabilityState.REMOVED, None)
    rows = [
        *(_stocked(f"w{n}", "Whole", OUT) for n in range(5)),
        *(_stocked(f"x{n}", "Whole", s) for n, s in enumerate(unseen)),
    ]
    a = next(s for s in insights(_with(rows), A, B).data.stockouts if s.retailer == A)
    assert [(r.brand, r.out_of_stock, r.observed) for r in a.unavailable] == [("Whole", 5, 5)]
    assert (a.listed, a.with_stock, a.unavailable_listings, a.out_of_stock) == (9, 5, 5, 0)


def test_a_larger_size_at_the_same_unit_price_is_not_cheaper() -> None:
    """30 ml at 60.00 and 50 ml at 100.00 are both 2.00/ml: a 0 % step counts as not cheaper."""
    steps: list[Product] = []
    for n in range(5):
        steps += _sizes(f"flat{n}", "Flat", f"Flat {n}", {"30": "60.00", "50": "100.00"})
    a = next(lad for lad in insights(_with(steps), A, B).data.ladders if lad.retailer == A)
    assert (a.steps, a.not_cheaper) == (5, 5)
    assert {s.unit_change_pct for s in a.exceptions} == {Decimal(0)}


def _rated(
    pid: str,
    price: str,
    rating: tuple[str, str, int] | None,
    category: str = "skincare",
    *,
    brand: str = "Fixture Beauty",
) -> Product:
    return product(
        pid, {A: offer(A, [price] * 3, rating=rating)}, category=(category,), brand=brand
    )


def test_value_picks_are_well_rated_at_or_below_the_category_median() -> None:
    rows = [
        _rated("p10", "10.00", ("4.50", "5", 20)),  # 90 % with 20 ratings: a pick
        _rated("p20", "20.00", ("4.49", "5", 500)),  # below 90 %
        _rated("p30", "30.00", ("9.00", "10", 25)),  # 90 % of a 10 scale, at the median
        _rated("p40", "40.00", ("5.00", "5", 100)),  # above the median
        _rated("p50", "50.00", ("4.90", "5", 19)),  # too few ratings: not rated
        _rated("p60", "60.00", None),
        *(_rated(f"m{n}", "10.00", ("5.00", "5", 50), "makeup") for n in range(4)),
    ]
    by = {v.retailer: v for v in insights(_with(rows), A, B).data.value}
    a = by[A]
    assert a.reason is None
    (row,) = a.categories
    assert row.category == "skincare"
    assert (row.priced, row.rated, row.picks) == (6, 4, 2)
    assert row.median.amount == "30.00"  # nearest rank: the lower middle of six
    # Equal 90 % shares shrink toward the category mean (92.45 %): fewer ratings move further.
    assert [(i.id, i.rating, i.scale, i.rating_count) for i in row.items] == [
        ("p10", Decimal("4.5"), "5", 20),
        ("p30", Decimal(9), "10", 25),
    ]
    assert row.items[1].price.amount == "30.00"
    assert row.items[1].image is None
    assert (row.basis, row.unit_medians) == (ValueBasis.SHELF, ())
    assert (row.items[1].size_value, row.items[1].size_unit, row.items[1].unit_price) == (
        "50",
        "ml",
        "0.6000",
    )
    assert (a.qualifying, a.suppressed) == (1, 1)  # makeup: four priced offers, no median
    assert (by[B].reason, by[B].categories) == (Reason.COHORT_TOO_SMALL, ())
    assert by[D].reason is Reason.RETAILER_BLOCKED


def test_value_lists_the_largest_categories_and_the_best_picks() -> None:
    rows = [
        *(
            _rated(f"c{c}-{n}", "10.00", ("5.00", "5", 20 + n), f"cat{c}")
            for c in range(9)
            for n in range(5)
        ),
        *(
            _rated(f"big{n}", f"{10 + n}.00", ("5.00", "5", 20), brand=f"Brand {n}")
            for n in range(12)
        ),
    ]
    a = next(v for v in insights(_with(rows), A, B).data.value if v.retailer == A)
    assert a.qualifying == 10
    assert len(a.categories) == CATEGORIES_LISTED
    assert [r.category for r in a.categories[:3]] == ["skincare", "cat0", "cat1"]
    big = a.categories[0]
    assert (big.priced, big.median.amount, big.picks) == (12, "15.00", 6)
    assert len(big.items) == PICKS_LISTED
    assert [i.id for i in big.items] == ["big0", "big1", "big2", "big3", "big4"]  # cheapest first
    assert a.categories[1].items[0].id == "c0-4"  # most ratings first


def test_value_without_ratings_says_why() -> None:
    off = insights(with_capabilities(metrics_dataset(), ratings=False), A, B).data.value
    assert {v.retailer: v.reason for v in off}[A] is Reason.CAPABILITY_OFF
    missing = with_fields(metrics_dataset(), rating=FieldStatus.NOT_COLLECTED)
    assert {v.retailer: v.reason for v in insights(missing, A, B).data.value}[A] is (
        Reason.FIELD_NOT_COLLECTED
    )


def _named(pid: str, name: str, category: str = "fragrance") -> Product:
    return _rated(pid, "10.00", ("5.00", "5", 50), category).model_copy(update={"name": name})


def test_body_care_filed_under_fragrance_is_left_out_of_the_value_cohort() -> None:
    rows = [
        *(_named(f"e{n}", f"Oud {n} Eau de Parfum") for n in range(4)),
        _named("set", "Rose Eau de Toilette & Body Lotion Set"),  # a fragrance term: stays
        _named("mist", "Vanilla Body Mist"),  # a mist is fragrance
        _named("bathsheba", "Bathsheba Noir"),  # "bath" only as a whole word
        _named("lotion", "Body Badalada Daily Glow Lotion"),
        _named("kids", "Kids Oat & Milk 3-in-1"),
        _named("gel", "Amber SHOWER Gel"),  # case-insensitive
        *(_named(f"s{n}", "Hand Cream", "skincare") for n in range(5)),  # only fragrance is ruled
    ]
    a = next(v for v in insights(_with(rows), A, B).data.value if v.retailer == A)
    by = {c.category: c for c in a.categories}
    assert (by["fragrance"].priced, by["fragrance"].excluded) == (7, 3)
    assert (by["skincare"].priced, by["skincare"].excluded) == (5, 0)
    assert not {i.id for i in by["fragrance"].items} & {"lotion", "kids", "gel"}


def _pick(
    pid: str,
    name: str,
    category: str = "skincare",
    *,
    price: str = "10.00",
    rating: tuple[str, str, int] = ("5.00", "5", 50),
    stock: list[AvailabilityState | None] | None = None,
    brand: str | None = None,
    size: tuple[str, str] | None = ("50", "ml"),
) -> Product:
    o = offer(A, [price] * 3, rating=rating, stock=stock)
    o = o.model_copy(update={"size": None if size is None else Size(value=size[0], unit=size[1])})
    return product(pid, {A: o}, category=(category,), brand=brand or f"Brand {pid}").model_copy(
        update={"name": name}
    )


def _value_a(rows: list[Product]) -> ValuePicks:
    return next(v for v in insights(_with(rows), A, B).data.value if v.retailer == A)


def test_the_catch_all_category_is_never_ranked() -> None:
    rows = [
        *(_pick(f"o{n}", "Nail Polish", "other") for n in range(6)),
        *(_pick(f"s{n}", "Night Cream") for n in range(5)),
    ]
    a = _value_a(rows)
    assert [c.category for c in a.categories] == ["skincare"]
    assert (a.unranked, a.qualifying, a.suppressed) == (6, 1, 0)


def test_tools_and_misfiled_body_care_leave_the_cohort() -> None:
    rows = [
        # skincare: tools and body care out; an applicator's description or "De-Puff" stays.
        *(
            _pick(pid, name)
            for pid, name in [
                ("brush", "Kabuki Brush"),
                ("sponge", "Makeup Sponges"),
                ("roller", "Jade Roller"),
                ("scrub", "Citrus Sugar Scrub"),
                ("epsom", "Lavender Epsom Soak"),
                ("adhesive", "Brush On Lash Adhesive"),
                ("liner", "Brush-Tip Liner"),
                ("depuff", "De-Puff Eye Gel"),
                ("n1", "Night Cream"),
                ("n2", "Day Cream"),
            ]
        ),
        # body: body care belongs here; a tool still does not.
        *(_pick(f"b{n}", f"Coconut Body Wash {n}", "body") for n in range(4)),
        _pick("sugar", "Sugar Scrub", "body"),
        _pick("mitt", "Bath Mitt", "body"),
        # fragrance: shaving is body care unless a fragrance term says otherwise.
        _pick("shave", "Truly After Shave Oil", "fragrance"),
        _pick("aftershave", "Cooling Aftershave Balm", "fragrance"),
        _pick("shaving", "Shaving Foam", "fragrance"),
        _pick("edt", "Aftershave Eau de Toilette", "fragrance"),
        _pick("rollon", "Rose Roll-On Perfume", "fragrance"),
        *(_pick(f"e{n}", f"Oud {n} Eau de Parfum", "fragrance") for n in range(3)),
    ]
    by = {c.category: c for c in _value_a(rows).categories}
    assert {k: (c.priced, c.excluded) for k, c in by.items()} == {
        "skincare": (5, 5),
        "body": (5, 1),
        "fragrance": (5, 3),
    }
    assert {i.id for i in by["skincare"].items} == {"adhesive", "liner", "depuff", "n1", "n2"}


def test_a_pick_is_in_stock_or_of_unknown_stock_on_the_date() -> None:
    rows = [
        _pick("out", "Gone", stock=[IN, IN, OUT]),
        _pick("back", "Back", stock=[OUT, OUT, IN]),
        _pick("low", "Low", stock=[IN, IN, AvailabilityState.LOW_STOCK]),
        _pick("unseen", "Unseen", stock=[IN, IN, None]),
        _pick("never", "Never"),
        _pick("more", "More"),
    ]
    (row,) = _value_a(rows).categories
    assert (row.priced, row.picks) == (6, 5)
    assert "out" not in {i.id for i in row.items}


def test_fragrance_is_ranked_per_unit_against_its_units_median() -> None:
    rows = [
        _pick("big", "Big Eau de Parfum", "fragrance", price="100.00", size=("100", "ml")),
        _pick("mid", "Mid Eau de Parfum", "fragrance", price="60.00", size=("50", "ml")),
        _pick("small", "Small Eau de Parfum", "fragrance", price="45.00", size=("30", "ml")),
        _pick("mini", "Mini Eau de Parfum", "fragrance", price="20.00", size=("10", "ml")),
        _pick("dear", "Dear Eau de Parfum", "fragrance", price="80.00", size=("40", "ml")),
        _pick("solid", "Solid Perfume", "fragrance", price="15.00", size=("10", "g")),
        _pick("bare", "Plain Cologne", "fragrance", price="10.00", size=None),
    ]
    (row,) = _value_a(rows).categories
    assert row.basis is ValueBasis.PER_UNIT
    assert row.median.amount == "45.00"  # the shelf median is still reported
    # 1.00, 1.20, 1.50, 2.00, 2.00 per ml; one offer in g is below the cohort, so no g median.
    assert [(m.unit, m.median, m.n) for m in row.unit_medians] == [("ml", "1.5000", 5)]
    # The 100 ml bottle is above the shelf median and a pick; the unsized, the solid (no g
    # median) and the 10 ml at 2.00/ml are not.
    assert [(i.id, i.unit_price) for i in row.items] == [
        ("big", "1.0000"),
        ("mid", "1.2000"),
        ("small", "1.5000"),
    ]
    assert row.picks == 3


def test_small_sizes_are_never_shelf_price_picks() -> None:
    rows = [
        _pick("mini", "Mini Night Cream"),
        _pick("travel", "Travel Cleanser"),
        _pick("deluxe", "Deluxe Sample Serum"),
        *(_pick(f"n{n}", f"Night Cream {n}") for n in range(3)),
    ]
    (row,) = _value_a(rows).categories
    assert (row.priced, row.picks) == (6, 3)
    assert {i.id for i in row.items} == {"n0", "n1", "n2"}


def test_many_ratings_outrank_a_few_perfect_ones() -> None:
    rows = [
        _pick("few", "Few", rating=("5.00", "5", 20)),
        _pick("many", "Many", rating=("4.80", "5", 2000)),
        *(_pick(f"ok{n}", f"Ok {n}", rating=("4.50", "5", 100)) for n in range(3)),
    ]
    (row,) = _value_a(rows).categories
    assert [i.id for i in row.items[:2]] == ["many", "few"]


def test_one_pick_per_name_and_at_most_two_per_brand() -> None:
    rows = [
        _pick("d1", "Glow Serum", brand="Dup", price="9.00"),
        _pick("d2", "GLOW  serum", brand="dup", price="8.00"),  # the same name: cheaper kept
        _pick("a", "Other A", brand="Dup"),
        _pick("b", "Other B", brand="Dup"),
        _pick("solo", "Solo", brand="Solo"),
    ]
    (row,) = _value_a(rows).categories
    assert (row.priced, row.picks) == (5, 3)
    assert [i.id for i in row.items] == ["d2", "a", "solo"]


def test_a_ladder_exception_says_which_size_is_on_sale() -> None:
    def size(pid: str, name: str, value: str, price: str, regular: str) -> Product:
        o = offer(A, [price] * 3, regular=[regular] * 3, size=value)
        return product(pid, {A: o}, brand="Sale").model_copy(update={"name": name})

    rows = [
        size("l30", "Large Sale", "30", "60.00", "60.00"),
        size("l50", "Large Sale", "50", "110.00", "120.00"),  # 2.00 -> 2.20/ml, larger on sale
        size("s30", "Small Sale", "30", "50.00", "60.00"),  # 1.67 -> 2.00/ml, smaller on sale
        size("s50", "Small Sale", "50", "100.00", "100.00"),
    ]
    a = next(lad for lad in insights(_with(rows), A, B).data.ladders if lad.retailer == A)
    flags = {s.name: (s.smaller_on_sale, s.larger_on_sale) for s in a.exceptions}
    assert flags == {"Large Sale": (False, True), "Small Sale": (True, False)}
