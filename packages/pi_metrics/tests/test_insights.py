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
)
from pi_core import AvailabilityState, ReviewState
from pi_dataset import Dataset, DatasetV3, Product
from pi_metrics import view
from pi_metrics.insights import LadderBasis, Policy, insights, policy
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


def test_brand_stockouts_are_counts_whole_brand_first() -> None:
    rows = [
        *(_stocked(f"w{n}", "Whole", OUT) for n in range(5)),
        *(_stocked(f"h{n}", "Half", OUT) for n in range(6)),
        *(_stocked(f"h{n}i", "Half", IN) for n in range(6)),
        _stocked("h-unseen", "Half", None),  # not observed: neither out nor observed
        *(_stocked(f"f{n}", "Few", OUT) for n in range(2)),
        _stocked("gone", "Gone", AvailabilityState.REMOVED),  # not an observed stock state
    ]
    by = {s.retailer: s for s in insights(_with(rows), A, B).data.stockouts}
    a = by[A]
    assert a.reason is None
    assert [(r.brand, r.out_of_stock, r.observed) for r in a.brands] == [
        ("Whole", 5, 5),
        ("Half", 6, 12),
    ]
    assert (a.qualifying, a.suppressed) == (2, 1)
    assert by[B].brands == ()
    assert by[D].reason is Reason.RETAILER_BLOCKED


def test_stockouts_without_the_stock_capability_say_so() -> None:
    m = insights(with_capabilities(metrics_dataset(), stock=False), A, B)
    assert {s.reason for s in m.data.stockouts} == {Reason.CAPABILITY_OFF, Reason.RETAILER_BLOCKED}


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
    assert [(r.brand, r.out_of_stock, r.observed) for r in a.brands] == [("Whole", 5, 5)]


def test_a_larger_size_at_the_same_unit_price_is_not_cheaper() -> None:
    """30 ml at 60.00 and 50 ml at 100.00 are both 2.00/ml: a 0 % step counts as not cheaper."""
    steps: list[Product] = []
    for n in range(5):
        steps += _sizes(f"flat{n}", "Flat", f"Flat {n}", {"30": "60.00", "50": "100.00"})
    a = next(lad for lad in insights(_with(steps), A, B).data.ladders if lad.retailer == A)
    assert (a.steps, a.not_cheaper) == (5, 5)
    assert {s.unit_change_pct for s in a.exceptions} == {Decimal(0)}
