from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from metrics_fixture import (
    IN,
    OUT,
    A,
    B,
    C,
    D,
    edge,
    metrics_dataset,
    offer,
    product,
    with_capabilities,
)
from pi_core import ReviewState
from pi_dataset import Dataset, DatasetV3, Product
from pi_metrics import view
from pi_metrics.findings import (
    EXAMPLES_LISTED,
    MISSING,
    ORDER,
    POSITION_MIN,
    PRICE_BANDS,
    RATED_SHOP_MIN,
    THRESHOLD,
    ChartKind,
    ChipCode,
    Finding,
    FindingKey,
    Findings,
    MatchBasis,
    Param,
    ParamKind,
    band_labels,
    band_of,
    concentration,
    findings,
    fragrance_line,
    name_tokens,
    nearest_rank,
    spearman,
)
from pi_metrics.model import Metric, Reason, Status
from pi_metrics.view import UnknownInput
from v3_fixture import doc, load, profile

#: A is the rival and B the focus throughout: compare's gap is (B - A) / A.
FOCUS, RIVAL = B, A
MATCH_BASED = (
    FindingKey.BRAND_DEPTH_GAPS,
    FindingKey.BRAND_PRICE_POLICY,
    FindingKey.SIZE_LEVEL_GAPS,
    FindingKey.REAL_DISCOUNTS,
)


def _with(products: list[Product]) -> Dataset:
    ds = metrics_dataset()
    return Dataset.model_validate(
        ds.model_copy(update={"products": tuple(products)}).model_dump(by_alias=True)
    )


def _named(p: Product, name: str) -> Product:
    return p.model_copy(update={"name": name})


def _run(ds: Dataset | DatasetV3, *, unverified: frozenset[str] = frozenset()) -> Metric[Findings]:
    return findings(ds, FOCUS, RIVAL, unverified=unverified)


def _get(m: Metric[Findings], key: FindingKey) -> Finding:
    return next(f for f in m.data.findings if f.key is key)


def _value(p: Param) -> str:
    return p.value


def _pair(
    pid: str,
    brand: str,
    rival: str,
    focus: str,
    size: str = "50",
    *,
    regular: str | None = None,
    state: ReviewState = ReviewState.APPROVED,
) -> Product:
    return product(
        pid,
        {
            RIVAL: offer(RIVAL, [rival] * 3, size=size),
            FOCUS: offer(
                FOCUS, [focus] * 3, size=size, regular=None if regular is None else [regular] * 3
            ),
        },
        [edge(A, B, state)],
        brand=brand,
    )


def _single(
    pid: str,
    shop: str,
    price: str | None,
    *,
    brand: str = "Fixture Beauty",
    name: str | None = None,
    category: str = "skincare",
    size: str = "50",
    regular: str | None = None,
    rating: tuple[str, str, int] | None = None,
    stock: object = None,
) -> Product:
    o = offer(
        shop,
        [price] * 3,
        size=size,
        regular=None if regular is None else [regular] * 3,
        rating=rating,
        stock=None if stock is None else [IN, IN, stock],  # type: ignore[list-item]
    )
    p = product(pid, {shop: o}, brand=brand, category=(category,))
    return p if name is None else _named(p, name)


# ---------------------------------------------------------------- arithmetic


def test_spearman_ranks_with_ties_and_refuses_no_variance() -> None:
    d = [Decimal(n) for n in (1, 2, 3, 4)]
    assert spearman(d, d) == Decimal(1)
    assert spearman(d, d[::-1]) == Decimal(-1)
    assert spearman(d, [Decimal(n) for n in (1, 1, 2, 2)]) == Decimal("0.89")
    assert spearman(d, [Decimal(5)] * 4) is None
    assert spearman(d[:1], d[:1]) is None


@given(st.lists(st.tuples(st.integers(0, 50), st.integers(0, 50)), min_size=2, max_size=40))
def test_spearman_is_bounded_and_symmetric(points: list[tuple[int, int]]) -> None:
    xs = [Decimal(x) for x, _ in points]
    ys = [Decimal(y) for _, y in points]
    rho = spearman(xs, ys)
    assert rho == spearman(ys, xs)
    if rho is not None:
        assert Decimal(-1) <= rho <= Decimal(1)
        assert rho == rho.quantize(Decimal("0.01"))


def test_nearest_rank_is_an_observed_lower_value() -> None:
    values = [Decimal(n) for n in (4, 1, 3, 2)]
    assert nearest_rank(values, Decimal("0.5")) == Decimal(2)
    assert nearest_rank(values, Decimal(0)) == Decimal(1)
    assert nearest_rank(values, Decimal(1)) == Decimal(4)


@given(
    st.lists(st.integers(0, 1000), min_size=1, max_size=30),
    st.integers(0, 100),
    st.integers(0, 100),
)
def test_nearest_rank_is_observed_and_monotone(values: list[int], p: int, q: int) -> None:
    d = [Decimal(v) for v in values]
    lo, hi = sorted((Decimal(p) / 100, Decimal(q) / 100))
    assert nearest_rank(d, lo) in d
    assert nearest_rank(d, lo) <= nearest_rank(d, hi)


def test_price_bands_have_labels_and_edges() -> None:
    assert band_labels() == ("<50", "50-99", "100-199", "200-399", "400-799", "800+")
    assert [band_of(Decimal(v)) for v in ("49.99", "50", "99.99", "800", "5000")] == [
        0,
        1,
        1,
        5,
        5,
    ]
    assert len(band_labels()) == len(PRICE_BANDS) + 1


def test_names_fold_to_lines_and_concentrations() -> None:
    assert concentration("Libre Eau de Parfum") == "edp"
    assert concentration("Libre EDT") == "edt"
    assert concentration("Libre Le Parfum") is None
    assert fragrance_line("Libre Eau de Parfum Intense 90 ml") == "libre"
    assert fragrance_line("Libre Eau de Toilette") == "libre"
    assert name_tokens("Lash Clash Extreme Volume Mascara 8 ml") == frozenset(
        {"lash", "clash", "extreme", "volume", "mascara"}
    )


# ---------------------------------------------------------------- request and ranking


def test_the_two_shops_must_differ_and_exist() -> None:
    ds = metrics_dataset()
    with pytest.raises(UnknownInput):
        findings(ds, A, A)
    with pytest.raises(UnknownInput):
        findings(ds, A, "nowhere")


def test_without_counted_pairs_the_match_based_findings_say_why() -> None:
    proposed = [
        _pair(f"r{n}", "Brand", "100.00", "90.00", state=ReviewState.PROPOSED) for n in range(6)
    ]
    m = _run(_with(proposed))
    assert m.data.counted_pairs == 0
    for key in MATCH_BASED:
        f = _get(m, key)
        assert (f.status, f.reason) == (Status.NOT_ENOUGH_DATA, Reason.MATCHES_UNREVIEWED)
        assert (f.params, f.chart, f.examples, f.n) == ({}, None, (), 0)
    m = _run(_with([_single("x", A, "10.00")]))
    assert {_get(m, k).reason for k in MATCH_BASED} == {Reason.NO_MATCH}


def test_findings_rank_shown_first_then_withheld_in_order() -> None:
    m = _run(_with([_single("x", A, "10.00")]))
    assert [f.rank for f in m.data.findings] == list(range(1, 13))
    assert {f.key for f in m.data.findings} == set(ORDER)
    statuses = [f.status is Status.OK for f in m.data.findings]
    assert statuses == sorted(statuses, reverse=True)
    for flag in (True, False):
        keys = [f.key for f in m.data.findings if (f.status is Status.OK) is flag]
        assert keys == sorted(keys, key=ORDER.index)
    assert m.data.thirds == (C, D)
    assert m.as_of == metrics_dataset().meta.dates[-1]


def test_off_profile_answers_not_applicable() -> None:
    m = _run(load(profile(doc(), "food_menu")))
    assert (m.status, m.reason, m.data.findings) == (
        Status.NOT_ENOUGH_DATA,
        Reason.NOT_APPLICABLE,
        (),
    )


def test_partial_shops_are_flagged() -> None:
    m = _run(_with([_single("x", A, "10.00")]))
    assert [c.params for c in m.caveats] == [{"retailer": C}]


# ---------------------------------------------------------------- 1 brand white space


def _absent(brands: int) -> list[Product]:
    return [
        _single(f"{b}-{n}", RIVAL, "30.00", brand=f"Brand {b}", rating=("4.80", "5", 100 + b))
        for b in range(brands)
        for n in range(5)
    ]


def test_white_space_lists_rival_brands_the_focus_lacks() -> None:
    rows = [*_absent(6), _single("f", FOCUS, "10.00", brand="BRAND 0")]  # folds to Brand 0
    rows += [_single(f"few{n}", RIVAL, "10.00", brand="Few") for n in range(4)]
    rows += [_single(f"c{n}", C, "10.00", brand="Only C", category="makeup") for n in range(2)]
    f = _get(_run(_with(rows)), FindingKey.BRAND_WHITE_SPACE)
    assert f.status is Status.OK
    assert (f.n, f.of, f.match) == (5, 8, MatchBasis.BRAND_LEVEL)
    p = f.params
    assert (p["absent"].value, p["shared"].value, p["sharedExact"].value) == ("5", "1", "0")
    names = ("Brand 5", "Brand 4", "Brand 3", "Brand 2", "Brand 1")
    assert p["absentNames"].items == names
    assert p["absentReviews"].value == str(5 * (105 + 104 + 103 + 102 + 101))
    assert (p["third"].value, p["thirdOnly"].value, p["thirdTop"].items) == (C, "1", ("Only C",))
    # one price, so every rated listing is in the cheapest quartile: ties go to the first key
    assert (p["lead"].value, p["leadChampions"].value) == ("Brand 1", "5")
    assert f.chart is not None
    assert [r.label for r in f.chart.rows] == list(names)
    assert [e.brand for e in f.examples] == list(names)
    withheld = _get(_run(_with(_absent(4))), FindingKey.BRAND_WHITE_SPACE)
    assert (withheld.status, withheld.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)


def test_white_space_names_the_lead_with_the_most_champions() -> None:
    """Champions are in their category's cheapest quartile and rated 90 % of scale or more."""
    rows = _absent(5)
    rows += [
        _single(f"ch{n}", RIVAL, f"{n + 1}.00", brand="Brand 2", rating=("4.80", "5", 60))
        for n in range(20)
    ]
    f = _get(_run(_with(rows)), FindingKey.BRAND_WHITE_SPACE)
    p = f.params
    assert (p["lead"].value, p["leadListings"].value) == ("Brand 2", "25")
    # 45 rated; the lower quartile edge is the 12th price (nearest rank, lower)
    assert p["leadChampions"].value == "12"
    assert (p["leadFrom"].value, p["leadTo"].value) == ("1.00", "12.00")


# ---------------------------------------------------------------- 2 brand depth gaps


def test_depth_gaps_count_absent_heroes_and_screen_likely_misses() -> None:
    heroes = [
        _single(
            f"h{n}",
            RIVAL,
            "50.00",
            brand="House",
            name=f"Hero {w} Mascara",
            category="makeup",
            rating=("4.50", "5", 600 + n),
        )
        for n, w in enumerate(("alpha", "beta", "gamma", "delta", "epsilon", "zeta"))
    ]
    screen = _single(
        "near",
        FOCUS,
        "40.00",
        brand="House",
        name="Hero Zeta Mascara Waterproof",
        category="fragrance",
    )
    shared = [
        _single(f"fr{n}", FOCUS, "40.00", brand="House", category="fragrance") for n in range(4)
    ]
    counted = [_pair(f"c{n}", "House", "100.00", "90.00") for n in range(5)]
    f = _get(_run(_with([*heroes, screen, *shared, *counted])), FindingKey.BRAND_DEPTH_GAPS)
    assert f.status is Status.OK
    p = f.params
    assert (p["heroes"].value, p["absent"].value, p["screened"].value) == ("6", "5", "1")
    assert (f.n, f.of) == (5, 6)
    assert f.examples[0].name == "Hero epsilon Mascara"  # the most reviewed first
    # House at the focus: 5 fragrance and 5 counted (skincare) items: 50 %, not a house
    assert p["houses"].value == "0"
    assert p["lead"] == MISSING


# ---------------------------------------------------------------- 3 brand price policy


@pytest.fixture(scope="module")
def priced() -> Dataset:
    """Undercut: focus cheaper on 5 of 5 (90 ml). Parity: level on 5 of 5. Small: 2 pairs."""
    rows = [
        *(_pair(f"u{n}", "Undercut", "100.00", "91.00", "90") for n in range(5)),
        *(_pair(f"p{n}", "Parity", "100.00", "100.00") for n in range(5)),
        *(_pair(f"s{n}", "Small", "100.00", "120.00", "30") for n in range(2)),
        _pair("r0", "Unreviewed", "100.00", "50.00", state=ReviewState.PROPOSED),
        _pair("l0", "Listed", "100.00", "90.00", "50", regular="105.00"),
    ]
    return _with(rows)


def test_price_policy_by_brand_over_counted_pairs(priced: Dataset) -> None:
    m = _run(priced)
    assert m.data.counted_pairs == 13
    f = _get(m, FindingKey.BRAND_PRICE_POLICY)
    assert (f.status, f.n, f.of, f.match) == (Status.OK, 13, 14, MatchBasis.COUNTED_PAIRS)
    p = f.params
    assert [p[k].value for k in ("focusCheaper", "level", "rivalCheaper")] == ["6", "5", "2"]
    # basket: 5 x 91 + 5 x 100 + 2 x 120 + 90 = 1285 against 1300
    assert (p["basketFocus"].value, p["basketRival"].value) == ("1285.00", "1300.00")
    assert p["basketPct"].value == "-1.2"
    assert p["cheaperAtRegular"].value == "5"  # the Listed pair is dearer at its regular
    assert (p["lead"].value, p["leadCheaper"].value, p["leadMedianPct"].value) == (
        "Undercut",
        "5",
        "-9.0",
    )
    assert (p["parityLead"].value, p["parityLeadLevel"].value) == ("Parity", "5")
    assert p["undercutNames"].items == ("Undercut",)
    assert p["undercutLowPct"].value == p["undercutHighPct"].value == "-9.0"
    assert f.chart is not None
    assert [(r.label, r.value) for r in f.chart.rows] == [
        ("Undercut", Decimal(-9)),
        ("Parity", Decimal(0)),
    ]
    # the two leading brands' pairs, the lead first
    assert [(e.retailer, e.versus, e.brand) for e in f.examples] == [
        (FOCUS, RIVAL, "Undercut"),
        (FOCUS, RIVAL, "Undercut"),
        (FOCUS, RIVAL, "Parity"),
    ]
    assert f.examples[0].gap_pct == Decimal(-9)


# ---------------------------------------------------------------- 4 size level gaps


def test_size_gaps_name_the_hero_and_the_entry_size(priced: Dataset) -> None:
    f = _get(_run(priced), FindingKey.SIZE_LEVEL_GAPS)
    assert f.status is Status.OK
    p = f.params
    assert (p["hero"].value, p["heroMedianPct"].value, p["heroCheaper"].value) == (
        "90 ml",
        "-9.0",
        "5",
    )
    assert (p["entry"].value, p["entryN"].value, p["entryMedianPct"].value) == ("50 ml", "6", "0.0")
    assert p["suppressed"].value == "1"  # 30 ml, two pairs
    assert (f.n, f.of) == (11, 13)
    assert {e.brand for e in f.examples} == {"Undercut", "Parity", "Listed"}


def test_one_listed_size_withholds_size_gaps() -> None:
    rows = [_pair(f"u{n}", "Undercut", "100.00", "91.00", "90") for n in range(5)]
    f = _get(_run(_with(rows)), FindingKey.SIZE_LEVEL_GAPS)
    assert (f.status, f.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)


# ---------------------------------------------------------------- 5 stock


def test_stock_counts_out_of_stock_by_brand_and_rival_gaps() -> None:
    rows = [
        *(_single(f"o{n}", FOCUS, "10.00", brand="Short", stock=OUT) for n in range(5)),
        *(_single(f"i{n}", FOCUS, "10.00", brand="Short", stock=IN) for n in range(5)),
        *(_single(f"w{n}", FOCUS, "10.00", brand="Whole", stock=OUT) for n in range(5)),
        *(_single(f"l{n}", FOCUS, "10.00", brand="Lux", stock=IN) for n in range(3)),
        *(_single(f"r{n}", RIVAL, "10.00", brand="LUX", stock=OUT) for n in range(5)),
        *(_single(f"r{n}i", RIVAL, "10.00", brand="LUX", stock=IN) for n in range(1)),
    ]
    f = _get(_run(_with(rows)), FindingKey.STOCK)
    assert f.status is Status.OK
    p = f.params
    assert (p["brand1"].value, p["brand1Out"].value, p["brand1Observed"].value) == (
        "Short",
        "5",
        "10",
    )
    assert (p["unavailableBrands"].value, p["unavailableListings"].value) == ("1", "5")
    assert (p["withStock"].value, p["listed"].value) == ("18", "18")
    assert p["rivalShort"].items == ("LUX",)
    assert (p["rivalShortOut"].items, p["rivalShortFocusIn"].items) == (("5",), ("3",))
    assert "Whole" not in {r.label for r in f.chart.rows} if f.chart else False
    assert [(c.code, c.retailer) for c in f.chips] == [
        (ChipCode.STOCK_NOT_COLLECTED, C),
        (ChipCode.STOCK_NOT_COLLECTED, D),
    ]
    assert {e.stock for e in f.examples} == {OUT}


def test_stock_without_the_capability_is_withheld() -> None:
    ds = with_capabilities(_with([_single("x", FOCUS, "10.00", stock=OUT)]), stock=False)
    f = _get(_run(ds), FindingKey.STOCK)
    assert (f.status, f.reason) == (Status.NOT_ENOUGH_DATA, Reason.CAPABILITY_OFF)


# ---------------------------------------------------------------- 6 promo strategy


def _promo() -> list[Product]:
    rows = [_single(f"d{n}", FOCUS, "70.00", brand="Deal", regular="100.00") for n in range(9)]
    rows.append(_single("d9", FOCUS, "100.00", brand="Deal", regular="100.00"))
    rows += [_single(f"f{n}", FOCUS, "500.00", brand="Full", regular="500.00") for n in range(10)]
    rows += [_single(f"c{n}", C, "50.00", regular="100.00", category="makeup") for n in range(2)]
    return rows


def test_promo_strategy_finds_the_flat_depth_and_dependent_brands() -> None:
    f = _get(_run(_with(_promo())), FindingKey.PROMO_STRATEGY)
    assert f.status is Status.OK
    p = f.params
    assert (p["marked"].value, p["stated"].value) == ("9", "20")
    assert (p["modePct"].value, p["modeCount"].value) == ("30.0", "9")
    assert (p["dependent"].value, p["dependentNames"].items) == ("1", ("Deal",))
    assert (p["dependentMarked"].items, p["dependentListed"].items) == (("9",), ("10",))
    assert (p["lowBandPct"], p["highBandPct"].value) == (MISSING, "0.0")
    assert (p["third"].value, p["thirdMarked"].value, p["thirdMedianPct"].value) == (
        C,
        "2",
        "50.0",
    )
    assert f.chart is not None
    assert [(r.label, r.value, r.n, r.of) for r in f.chart.rows] == [("Deal", Decimal(90), 9, 10)]
    assert [e.retailer for e in f.examples] == [FOCUS] * 3 + [C] * 2
    assert f.examples[0].regular is not None
    assert [(c.code, c.retailer) for c in f.chips] == [(ChipCode.DISCOUNTS_NOT_SHOWN, D)]


def test_unverified_was_prices_show_no_discounts() -> None:
    m = _run(_with(_promo()), unverified=frozenset({FOCUS}))
    f = _get(m, FindingKey.PROMO_STRATEGY)
    assert (f.status, f.reason) == (Status.NOT_ENOUGH_DATA, Reason.WAS_PRICE_UNVERIFIED)
    assert (ChipCode.DISCOUNTS_NOT_SHOWN, FOCUS) in {(c.code, c.retailer) for c in f.chips}
    shown = [e for g in m.data.findings for e in g.examples if e.retailer == FOCUS]
    assert all(e.regular is None for e in shown)


def test_promotions_off_withholds_promo_strategy() -> None:
    ds = with_capabilities(_with(_promo()), promotions=False)
    f = _get(_run(ds), FindingKey.PROMO_STRATEGY)
    assert (f.status, f.reason) == (Status.NOT_ENOUGH_DATA, Reason.CAPABILITY_OFF)


# ---------------------------------------------------------------- 7 real discounts


def test_real_discounts_compare_the_stated_regular_with_the_other_shop() -> None:
    rows = [_pair(f"m{n}", "Mark", "100.00", "70.00", regular="101.00") for n in range(4)]
    rows.append(_pair("far", "Mark", "100.00", "60.00", regular="120.00"))
    f = _get(_run(_with(rows)), FindingKey.REAL_DISCOUNTS)
    assert f.status is Status.OK
    p = f.params
    assert (p["markdowns"].value, p["real"].value, p["pairs"].value) == ("5", "4", "5")
    assert (p["leadPct"].value, p["leadShop"].value, p["leadVersus"].value) == ("50.0", B, A)
    assert (p["leadPrice"].value, p["leadRegular"].value, p["leadVersusPrice"].value) == (
        "60.00",
        "120.00",
        "100.00",
    )
    assert f.examples[0].gap_pct == Decimal(-40)
    few = _get(_run(_with(rows[:4])), FindingKey.REAL_DISCOUNTS)
    assert (few.status, few.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)


# ---------------------------------------------------------------- 8 fragrance ladder


def _bottles(shop: str, line: str, edp: str, edt: str, size: str = "50") -> list[Product]:
    return [
        _single(
            f"{shop}-{line.replace(' ', '')}-{k}{size}",
            shop,
            price,
            brand="House",
            name=f"{line} {name}",
            category="fragrance",
            size=size,
        )
        for k, name, price in (("p", "Eau de Parfum", edp), ("t", "Eau de Toilette", edt))
    ]


def test_fragrance_ladder_medians_and_inversions() -> None:
    rows: list[Product] = []
    for n, edp in enumerate(("110.00", "120.00", "130.00", "140.00", "90.00")):
        rows += _bottles(FOCUS, f"Line {n}", edp, "100.00")
    rows += _bottles(FOCUS, "Line 0", "200.00", "100.00", size="100")  # another bottle size
    rows += (
        _single(
            "set",
            FOCUS,
            "50.00",
            brand="House",
            name="Line 1 Eau de Parfum Set",
            category="fragrance",
        ),
    )
    rows += _bottles(RIVAL, "Line 0", "110.00", "100.00")
    f = _get(_run(_with(rows)), FindingKey.FRAGRANCE_LADDER)
    assert f.status is Status.OK
    p = f.params
    assert (p["focusEdpN"].value, p["focusEdpPct"].value, p["focusEdpNegative"].value) == (
        "6",
        "20.0",
        "1",
    )
    assert (p["rivalEdpN"].value, p["rivalEdpPct"]) == ("1", MISSING)
    assert (p["inversions"].value, p["leadPct"].value, p["leadBase"].value) == (
        "1",
        "-10.0",
        "Line 4 Eau de Toilette",
    )
    assert f.chart is not None
    assert f.chart.kind is ChartKind.STRIPS
    assert [(r.label, r.retailer, r.n) for r in f.chart.rows] == [("edp_edt", FOCUS, 6)]
    assert {(c.code, c.retailer) for c in f.chips} == {
        (ChipCode.TOO_FEW_PAIRS, s) for s in (RIVAL, C, D)
    }
    assert [e.versus_name for e in f.examples] == ["Line 4 Eau de Toilette"]


def test_two_listings_of_one_kind_are_skipped_not_guessed() -> None:
    rows: list[Product] = []
    for n in range(5):
        rows += _bottles(FOCUS, f"Line {n}", "110.00", "100.00")
    rows.append(
        _single("dup", FOCUS, "90.00", brand="House", name="Line 0 EDP", category="fragrance")
    )
    f = _get(_run(_with(rows)), FindingKey.FRAGRANCE_LADDER)
    assert (f.status, f.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)


# ---------------------------------------------------------------- 9 size traps


def _sizes(pid: str, shop: str, name: str, prices: dict[str, str]) -> list[Product]:
    return [
        _single(f"{pid}-{v}", shop, p, brand="Ladder", name=name, size=v) for v, p in prices.items()
    ]


def test_size_traps_list_the_focus_steps_not_cheaper() -> None:
    rows: list[Product] = []
    for n in range(4):
        rows += _sizes(f"ok{n}", FOCUS, f"Cream {n}", {"30": "60.00", "50": "90.00"})
    rows += _sizes("bad", FOCUS, "Gel", {"30": "60.00", "50": "110.00"})
    f = _get(_run(_with(rows)), FindingKey.SIZE_TRAPS)
    assert f.status is Status.OK
    p = f.params
    assert (p["focusSteps"].value, p["focusNotCheaper"].value, p["focusSavingPct"].value) == (
        "5",
        "1",
        "10.0",
    )
    assert (p["rivalSteps"].value, p["rivalNotCheaper"], p["rivalSavingPct"]) == (
        "0",
        MISSING,
        MISSING,
    )
    assert p["leadPct"].value == "10.0"
    (e,) = f.examples
    assert (e.name, e.versus, e.versus_price, e.gap_pct) == (
        "Gel",
        FOCUS,
        e.versus_price,
        Decimal(10),
    )
    assert e.versus_price is not None
    assert e.versus_price.amount == "60.00"
    assert ChipCode.TOO_FEW_PAIRS in {c.code for c in f.chips}
    few = _get(_run(_with(rows[:8])), FindingKey.SIZE_TRAPS)
    assert (few.status, few.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)


# ---------------------------------------------------------------- 10 positioning


def test_positioning_shares_by_band_and_suppresses_small_categories() -> None:
    rows = [
        _single(f"fl{n}", FOCUS, "40.00" if n < 10 else "80.00", category="lips")
        for n in range(POSITION_MIN)
    ]
    rows += [_single(f"rl{n}", RIVAL, "900.00", category="lips") for n in range(POSITION_MIN)]
    rows += [_single(f"re{n}", RIVAL, "60.00", category="eyes") for n in range(POSITION_MIN - 1)]
    f = _get(_run(_with(rows)), FindingKey.POSITIONING)
    assert f.status is Status.OK
    p = f.params
    assert (p["lipsUnderFocus"].value, p["lipsMedianFocus"].value) == ("33.3", "80.00")
    assert (p["lipsOverRival"].value, p["lipsUnderRival"].value) == ("100.0", "0.0")
    assert (p["eyesUnderRival"], p["fragranceMedianFocus"]) == (MISSING, MISSING)
    assert (f.n, f.of) == (60, 89)
    assert f.chart is not None
    assert f.chart.columns == band_labels()
    focus_row = next(r for r in f.chart.rows if r.retailer == FOCUS)
    assert focus_row.parts[:2] == (Decimal(10) * 100 / 30, Decimal(20) * 100 / 30)
    only_focus = _get(_run(_with(rows[:POSITION_MIN])), FindingKey.POSITIONING)
    assert only_focus.reason is Reason.COHORT_TOO_SMALL


# ---------------------------------------------------------------- 11 price vs rating


def _rated_shop(shop: str, count: int) -> list[Product]:
    """Prices 1..count; the cheapest quarter rated 4.8, the dearest quarter 3.5."""
    q = count // 4
    return [
        _single(
            f"{shop}-{n}",
            shop,
            f"{n + 1}.00",
            rating=("4.80" if n < q else "3.50" if n >= count - q else "4.20", "5", 60),
        )
        for n in range(count)
    ]


def test_price_vs_rating_speaks_for_the_first_shop_with_enough_ratings() -> None:
    rows = [*_rated_shop(RIVAL, RATED_SHOP_MIN), *_rated_shop(FOCUS, 20)]
    f = _get(_run(_with(rows)), FindingKey.PRICE_VS_RATING)
    assert f.status is Status.OK
    p = f.params
    assert (p["shop"].value, p["n"].value, p["focusRated"].value) == (RIVAL, "100", "20")
    assert (p["champions"].value, p["laggards"].value) == ("25", "25")
    assert p["lowCategory"].value == "skincare"
    assert Decimal(p["lowRho"].value) < Decimal(0)
    assert [(c.code, c.retailer) for c in f.chips] == [
        (ChipCode.TOO_FEW_RATINGS, s) for s in (FOCUS, C, D)
    ]
    assert f.chart is not None
    assert [(r.label, r.parts) for r in f.chart.rows] == [
        ("high", (Decimal(25), Decimal(0), Decimal(0), Decimal(0))),
        ("mid", (Decimal(0), Decimal(25), Decimal(25), Decimal(0))),
        ("low", (Decimal(0), Decimal(0), Decimal(0), Decimal(25))),
    ]
    assert [e.rating for e in f.examples] == [Decimal("4.8")] * 3 + [Decimal("3.5")] * 3
    few = _get(_run(_with(_rated_shop(RIVAL, RATED_SHOP_MIN - 1))), FindingKey.PRICE_VS_RATING)
    assert (few.status, few.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)


# ---------------------------------------------------------------- 12 pricing anomalies


def _floored(ds: Dataset, ids: set[str]) -> DatasetV3:
    """The view with the latest price of ``ids`` withheld, as the API's price floor serves it."""
    v3 = view.as_v3(ds)
    last = len(v3.meta.dates) - 1
    products = []
    for p in v3.products:
        offers = dict(p.offers)
        if p.id in ids:
            for cid, o in offers.items():
                prices = (*o.series.price[:last], None)
                cleared = o.model_copy(
                    update={"series": o.series.model_copy(update={"price": prices})}
                )
                offers[cid] = view.WithheldOffer.of(cleared, frozenset({last}))
        products.append(p.model_copy(update={"offers": offers}))
    return v3.model_copy(update={"products": tuple(products)})


def test_pricing_anomalies_count_withheld_prices_in_stock_first() -> None:
    rows = [
        _single("gift", FOCUS, "0.01", brand="Gift", stock=OUT),
        _single("bag", FOCUS, "0.01", brand="Bag", stock=IN),
        _single("ok", FOCUS, "10.00", brand="Ok", stock=IN),
    ]
    f = _get(_run(_floored(_with(rows), {"gift", "bag"})), FindingKey.PRICING_ANOMALIES)
    assert f.status is Status.OK
    p = f.params
    assert (p["focusCount"].value, p["focusInStock"].value, p["rivalCount"].value) == (
        "2",
        "1",
        "0",
    )
    assert [(e.brand, e.price, e.price_withheld) for e in f.examples] == [
        ("Bag", None, True),
        ("Gift", None, True),
    ]
    assert (f.n, f.of) == (2, 3)
    clean = _get(_run(_with(rows)), FindingKey.PRICING_ANOMALIES)
    assert (clean.status, clean.reason) == (Status.NOT_ENOUGH_DATA, Reason.COHORT_TOO_SMALL)


# ---------------------------------------------------------------- every finding


def _all_shown() -> list[Product]:
    rows: list[Product] = [*_absent(5), *_promo()]
    rows += [_pair(f"u{n}", "Undercut", "100.00", "91.00", "90") for n in range(5)]
    rows += [_pair(f"p{n}", "Parity", "100.00", "100.00") for n in range(5)]
    return rows


def test_every_finding_carries_its_evidence() -> None:
    m = _run(_with(_all_shown()))
    for f in m.data.findings:
        assert f.threshold == THRESHOLD[f.key]
        assert len(f.examples) <= EXAMPLES_LISTED
        names = [(e.retailer, e.brand, e.name) for e in f.examples]
        assert len(names) == len(set(names))
        if f.status is Status.OK:
            assert f.reason is None
            assert f.chart is not None
            assert f.of is None or f.n <= f.of
            assert all(isinstance(p.kind, ParamKind) for p in f.params.values())
        else:
            assert f.reason is not None
            assert (f.params, f.chart, f.examples) == ({}, None, ())


@settings(deadline=None, max_examples=20)
@given(st.integers(0, 3), st.integers(0, 4))
def test_more_suppressed_brands_never_raise_the_shown_count(extra: int, small: int) -> None:
    """Adding rival-only brands below the listing minimum never changes the absent count."""
    rows = _absent(5)
    rows += [
        _single(f"x{b}-{n}", RIVAL, "10.00", brand=f"Tiny {b}")
        for b in range(extra)
        for n in range(small)
    ]
    f = _get(_run(_with(rows)), FindingKey.BRAND_WHITE_SPACE)
    assert f.params["absent"].value == "5"
