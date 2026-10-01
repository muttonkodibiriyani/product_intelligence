from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_match.normalise import Size
from pi_match.unit_price import (
    UNIT_PRICE_Q,
    BasePrice,
    Basis,
    derive_unit_price,
    pack_count,
    parse_count,
    price_per_base,
)

ML, G = "ml", "g"


@pytest.mark.parametrize(
    ("price", "size", "expected"),
    [
        (Decimal(120), Size(Decimal(50), ML), BasePrice(Decimal("240.0000"), Basis.PER_100_ML)),
        (Decimal(99), Size(Decimal(30), ML), BasePrice(Decimal("330.0000"), Basis.PER_100_ML)),
        (Decimal(45), Size(Decimal("3.5"), G), BasePrice(Decimal("1285.7143"), Basis.PER_100_G)),
        (Decimal(10), Size(Decimal(1000), ML), BasePrice(Decimal("1.0000"), Basis.PER_100_ML)),
    ],
)
def test_price_per_100_ml_or_g(price: Decimal, size: Size, expected: BasePrice) -> None:
    assert price_per_base(price, size) == expected


def test_price_per_unit() -> None:
    assert price_per_base(Decimal(90), count=60) == BasePrice(Decimal("1.5000"), Basis.PER_UNIT)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"price": None, "size": Size(Decimal(50), ML)},
        {"price": Decimal(0), "size": Size(Decimal(50), ML)},
        {"price": Decimal(10)},  # no size, no count
        {"price": Decimal(10), "size": Size(Decimal(0), ML)},
        {"price": Decimal(10), "count": 0},
        {"price": Decimal(10), "size": Size(Decimal(50), ML), "pack": 2},  # multi-pack
        {"price": Decimal(10), "size": Size(Decimal(50), ML), "count": 3},  # which basis?
    ],
)
def test_no_unit_price(kwargs: dict[str, object]) -> None:
    assert price_per_base(**kwargs) is None  # type: ignore[arg-type]


def test_a_pack_of_one_is_not_a_multipack() -> None:
    assert price_per_base(Decimal(10), Size(Decimal(50), ML), pack=1) is not None


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("2 x 50 ml", 2),
        ("50 ml x 2", 2),
        ("50ml \u00d72", 2),
        ("50ML X 2", 2),
        ("x2 50ml", 2),
        ("\u00d7 3 30 g", 3),
        ("1.5 x 30ml", Decimal("1.5")),
        ("30ml x 1,5", Decimal("1.5")),
        ("3x15ml", 3),
        ("Pack of 4", 4),
        ("set of 3", 3),
        ("6-pack", 6),
        ("Lip Duo", 2),
        ("Mini trio", 3),
        ("['2 x 30 ml']", 2),
        ("50 ml", None),
        ("SPF 50", None),
        ("Max 50 ml", None),
        ("1.7 fl ozx2", 2),
        (None, None),
    ],
)
def test_pack_count(text: str | None, count: int | Decimal | None) -> None:
    assert pack_count(text) == count


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("60 capsules", 60),
        ("30 pcs", 30),
        ("['12 pads']", 12),
        ("24 count", 24),
        ("10 pcs / 20 pcs", None),  # several counts: ambiguous
        ("50 ml", None),
        ("", None),
    ],
)
def test_parse_count(text: str, count: int | None) -> None:
    assert parse_count(text) == count


@pytest.mark.parametrize(
    ("price", "text", "expected"),
    [
        (Decimal(120), "50 ml", BasePrice(Decimal("240.0000"), Basis.PER_100_ML)),
        (Decimal(120), "['50'] ['ML']", BasePrice(Decimal("240.0000"), Basis.PER_100_ML)),
        (Decimal(60), "1.7 fl oz", BasePrice(Decimal("119.3437"), Basis.PER_100_ML)),
        (Decimal(90), "60 capsules", BasePrice(Decimal("1.5000"), Basis.PER_UNIT)),
        (Decimal(120), "['50', '90'] ['ML']", None),  # ambiguous size list
        (Decimal(120), "2 x 50 ml", None),  # multi-pack
        (Decimal(120), "50 ml x 2", None),
        (Decimal(120), "50ml \u00d72", None),
        (Decimal(120), "x2 50ml", None),
        (Decimal(120), "1.5 x 30ml", None),  # a non-integer multiplier is ambiguous
        (Decimal(120), "1 x 50 ml", BasePrice(Decimal("240.0000"), Basis.PER_100_ML)),
        (Decimal(120), "Kit 3 pieces", None),  # kits and sets hold different items
        (Decimal(120), "Gift Set 50 ml", None),
        (Decimal(120), "60 capsules, 30 ml", None),  # size and count: which basis?
        (Decimal(120), "[Limited] 50 ml", BasePrice(Decimal("240.0000"), Basis.PER_100_ML)),
        (Decimal(120), "NOSIZE", None),
        (Decimal(120), None, None),
        (None, "50 ml", None),
    ],
)
def test_derive_unit_price(price: Decimal | None, text: str | None, expected: BasePrice) -> None:
    assert derive_unit_price(price, text) == expected


_AMOUNTS = st.decimals(min_value=Decimal("0.5"), max_value=Decimal(2000), places=2)
_PRICES = st.decimals(min_value=Decimal("0.01"), max_value=Decimal(50000), places=2)


@given(_PRICES, _AMOUNTS, st.integers(min_value=1, max_value=100), st.sampled_from([ML, G]))
def test_scaling_the_size_by_k_divides_the_unit_price_by_k(
    price: Decimal, amount: Decimal, k: int, unit: str
) -> None:
    base = price_per_base(price, Size(amount, unit))
    scaled = price_per_base(price, Size(amount * k, unit))
    assert base is not None
    assert scaled is not None
    assert scaled.basis == base.basis
    # Each result is rounded to UNIT_PRICE_Q, so they agree to within one quantum.
    assert abs(scaled.amount - base.amount / k) <= UNIT_PRICE_Q


@given(_PRICES, st.integers(min_value=1, max_value=500), st.integers(min_value=1, max_value=20))
def test_scaling_the_count_by_k_divides_the_unit_price_by_k(price: Decimal, n: int, k: int) -> None:
    base = price_per_base(price, count=n)
    scaled = price_per_base(price, count=n * k)
    assert base is not None
    assert scaled is not None
    assert abs(scaled.amount - base.amount / k) <= UNIT_PRICE_Q


_SIZES = st.builds(
    lambda n, unit, space: f"{n}{space}{unit}",
    st.integers(min_value=1, max_value=1000),
    st.sampled_from(["ml", "ML", "g", "fl oz"]),
    st.sampled_from(["", " "]),
)
_TIMES = st.sampled_from([" x ", "x", " X ", "\u00d7", " \u00d7 ", "x ", " x"])


@given(_PRICES, _SIZES, st.integers(min_value=2, max_value=48), _TIMES)
def test_a_multipack_never_gets_a_unit_price(price: Decimal, size: str, n: int, times: str) -> None:
    for label in (f"{size}{times}{n}", f"{n}{times}{size}", f"x{n} {size}"):
        assert derive_unit_price(price, label) is None, label
