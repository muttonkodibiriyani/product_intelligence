"""Signals are in [0, 1] or absent; absent ones are never imputed."""

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_similar.items import Item, items
from pi_similar.signals import (
    WEIGHTS,
    ConflictError,
    PriceBands,
    Signal,
    attributes,
    combine,
    cosine,
    price,
)
from similar_fixtures import NORTH, SOUTH, Off, Prod, dataset

unit = st.decimals(0, 1, places=4)
maybe = st.none() | unit


def test_combine_is_the_weighted_mean_of_present_signals() -> None:
    signals = {Signal.TEXT: Decimal("0.8"), Signal.IMAGE: None, Signal.PRICE: Decimal("0.5")}
    assert combine(signals) == Decimal("0.7000")  # (0.4*0.8 + 0.2*0.5) / 0.6
    assert WEIGHTS[Signal.TEXT] == Decimal("0.4")


@pytest.mark.parametrize(
    "signals",
    [
        {Signal.TEXT: Decimal(1)},
        {Signal.TEXT: Decimal(1), Signal.IMAGE: None, Signal.PRICE: None},
        {Signal.PRICE: Decimal(1), Signal.ATTRIBUTES: Decimal(1)},
    ],
)
def test_combine_needs_two_signals_one_of_them_text_or_image(
    signals: dict[Signal, Decimal | None],
) -> None:
    assert combine(signals) is None


@given(text=maybe, image=maybe, price_=maybe, attrs=maybe)
def test_combine_is_in_unit_range_and_ignores_absent_signals(
    text: Decimal | None, image: Decimal | None, price_: Decimal | None, attrs: Decimal | None
) -> None:
    signals = {
        Signal.TEXT: text,
        Signal.IMAGE: image,
        Signal.PRICE: price_,
        Signal.ATTRIBUTES: attrs,
    }
    score = combine(signals)
    present = {k: v for k, v in signals.items() if v is not None}
    assert score == combine(present)  # an absent signal changes nothing
    if score is not None:
        assert 0 <= score <= 1
        assert min(present.values()) - Decimal("0.0001") <= score
        assert score <= max(present.values()) + Decimal("0.0001")


@pytest.mark.parametrize(
    ("value", "expected"), [(0.81234, "0.8123"), (-0.3, "0.0000"), (1.2, "1.0000")]
)
def test_cosine_is_clamped_to_unit_range(value: float, expected: str) -> None:
    assert str(cosine(value)) == expected


def _fragrances(prices: list[str], **offer: Off) -> tuple[Item, ...]:
    return items(
        [
            dataset(
                [
                    Prod(
                        f"p{i}",
                        "Bloom EDP",
                        ["Fragrance"],
                        {NORTH if i % 2 else SOUTH: Off(amount)},
                    )
                    for i, amount in enumerate(prices)
                ]
            )
        ]
    )


def test_price_bands_same_adjacent_far_and_absent() -> None:
    found = _fragrances(
        ["10.00", "20.00", "30.00", "40.00", "50.00", "60.00", "70.00", "80.00", "90.00", "100.00"]
    )
    bands = PriceBands.of(found)
    by_id = {it.product: it for it in found}
    assert price(by_id["p0"], by_id["p1"], bands) == (Decimal(1), "price_band:same")
    assert price(by_id["p0"], by_id["p2"], bands) == (Decimal("0.5"), "price_band:adjacent")
    assert price(by_id["p0"], by_id["p9"], bands) == (Decimal(0), "price_band:far")
    few = _fragrances(["10.00", "20.00"])
    assert price(few[0], few[1], PriceBands.of(few)) == (None, None)  # too few for bands


def test_price_is_absent_without_a_unit_price() -> None:
    found = _fragrances(["10.00", "20.00", "30.00", "40.00", "50.00"])
    unpriced = items([dataset([Prod("x", "Bloom EDP", ["Fragrance"], {NORTH: Off(None)})])])[0]
    assert price(found[0], unpriced, PriceBands.of(found)) == (None, None)


def _priced(offers: list[Off]) -> tuple[Item, ...]:
    """Fragrance items, alternating retailers, one per offer."""
    retailers = (NORTH, SOUTH)
    return items(
        [
            dataset(
                [
                    Prod(f"p{i}", "Bloom EDP", ["Fragrance"], {retailers[i % 2]: o})
                    for i, o in enumerate(offers)
                ]
            )
        ]
    )


AMOUNTS = ["10.00", "20.00", "30.00", "40.00", "50.00"]


def test_price_is_absent_across_currencies() -> None:
    # One dataset has one market currency, so the SAR items are the same items re-priced in SAR.
    aed_items = _priced([Off(a) for a in AMOUNTS])
    found = (*aed_items, *(replace(it, currency="SAR") for it in aed_items))
    aed, sar = found[0], found[len(AMOUNTS)]
    bands = PriceBands.of(found)
    assert bands.band(aed) == bands.band(sar)  # each currency has bands, and the same one
    assert price(aed, sar, bands) == (None, None)


def test_price_is_absent_across_price_bases() -> None:
    found = _priced([Off(a) for a in AMOUNTS] + [Off(a, size=("50", "g")) for a in AMOUNTS])
    ml, g = found[0], found[len(AMOUNTS)]
    assert ml.unit_price is not None
    assert g.unit_price is not None
    assert ml.unit_price.basis is not g.unit_price.basis
    bands = PriceBands.of(found)
    assert bands.band(ml) == bands.band(g)  # each basis has bands, and the same one
    assert price(ml, g, bands) == (None, None)


def _one(name: str, **attrs: str) -> Item:
    return items([dataset([Prod("x", name, ["Fragrance"], {NORTH: Off()}, attributes=attrs)])])[0]


def test_attributes_agree_unknown_and_conflict() -> None:
    edp_women, edp = _one("Bloom EDP for Women"), _one("Rose Eau de Parfum")
    value, reasons = attributes(edp_women, edp)
    # form and concentration agree (1, 1); gender known on one side (0.5)
    assert value == Decimal("0.8333")
    assert reasons == ("same_form:fragrance", "same_concentration:edp", "gender_unknown_one_side")
    with pytest.raises(ConflictError):
        attributes(edp, _one("Rose Eau de Toilette"))
    with pytest.raises(ConflictError):
        attributes(edp_women, _one("Oud EDP for Men"))
    assert attributes(_one("Rose"), _one("Oud"))[0] is None  # nothing known on both sides
