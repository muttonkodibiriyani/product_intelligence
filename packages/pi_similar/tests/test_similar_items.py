"""Items read only what the file carries; anything unreadable stays None."""

from decimal import Decimal

import pytest

from pi_match.normalise import Concentration, Form, ItemKind
from pi_match.unit_price import Basis
from pi_similar.items import Department, Gender, department, gender, items
from similar_fixtures import NORTH, SOUTH, Off, Prod, dataset


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (["Beauty", "Fragrance", "Women"], Department.FRAGRANCE),
        (["Fragrance", "Hair Mist"], Department.FRAGRANCE),
        (["Hair", "Hair Oil"], Department.HAIR),
        (["Makeup", "Lips"], Department.MAKEUP),
        (["Skincare", "Serum"], Department.SKINCARE),
        (["Bath & Body", "Body Mist"], Department.BODY),
        (["Gifts"], None),
    ],
)
def test_department_is_the_first_level_that_names_one(
    category: list[str], expected: Department | None
) -> None:
    assert department(category) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bloom Eau de Parfum for Women", Gender.WOMEN),
        ("Pour Homme EDT", Gender.MEN),
        ("Unisex Oud for men and women", Gender.UNISEX),
        ("Duo for men and women", None),
        ("Bloom", None),
    ],
)
def test_gender_is_one_named_gender_or_none(text: str, expected: Gender | None) -> None:
    assert gender(text) is expected


def test_items_parse_offers_and_skip_early_ones() -> None:
    doc = dataset(
        [
            Prod(
                "p1",
                "Bloom Eau de Parfum for Women",
                ["Fragrance", "Women"],
                {NORTH: Off("120.00", ("50", "ml")), SOUTH: Off("90.00", ("1.7", "fl oz"))},
            ),
            Prod(
                "p2",
                "Bloom Mini",
                ["Fragrance"],
                {NORTH: Off(None), SOUTH: Off(early=True)},
                attributes={"concentration": "Eau de Toilette", "gender": "men"},
            ),
            Prod("p3", "Lip Kit", ["Makeup"], {NORTH: Off("50.00", ("3", "pcs"))}),
        ]
    )
    first, second, third, fourth = items([doc])
    assert (first.product, first.retailer, second.retailer) == ("p1", NORTH, SOUTH)
    assert first.department is Department.FRAGRANCE
    assert first.form is Form.FRAGRANCE
    assert first.concentration is Concentration.EDP
    assert first.gender is Gender.WOMEN
    assert first.unit_price is not None
    assert (first.unit_price.amount, first.unit_price.basis) == (
        Decimal("240.00"),
        Basis.PER_100_ML,
    )
    assert second.unit_price is not None  # fl oz is a measured size
    assert first.text.startswith("Bloom Eau de Parfum for Women\nFragrance / Women")
    # attributes win over the name; never priced means no unit price; the early offer is skipped
    assert (third.product, third.concentration, third.gender) == (
        "p2",
        Concentration.EDT,
        Gender.MEN,
    )
    assert third.kind is ItemKind.MINI
    assert third.unit_price is None
    # a price per piece is not a price per ml or g
    assert (fourth.product, fourth.unit_price) == ("p3", None)


def test_no_size_means_no_unit_price() -> None:
    (only,) = items([dataset([Prod("p1", "Serum", ["Skincare"], {NORTH: Off(size=None)})])])
    assert only.unit_price is None
