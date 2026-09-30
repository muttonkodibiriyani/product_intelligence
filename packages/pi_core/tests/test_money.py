from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_core import CurrencyMismatchError, Money


def test_three_decimal_currency_preserved() -> None:
    # UAT-08: three-decimal currencies survive without rounding artifacts.
    m = Money.of("1.235", "KWD")
    assert m.amount == Decimal("1.235")
    assert m.exponent == 3
    assert str(m) == "1.235 KWD"


def test_float_is_rejected() -> None:
    with pytest.raises(TypeError):
        Money.of(1.1, "SAR")  # type: ignore[arg-type]


def test_bool_is_rejected() -> None:
    with pytest.raises(TypeError):
        Money.of(True, "SAR")
    with pytest.raises(TypeError):
        Money(True, "SAR")  # type: ignore[arg-type]


def test_non_decimal_constructor_rejected() -> None:
    with pytest.raises(TypeError):
        Money(10, "SAR")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["abc", ""])
def test_invalid_amount(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid amount"):
        Money.of(bad, "SAR")


def test_non_finite_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        Money.of("NaN", "SAR")


def test_unknown_currency_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported currency"):
        Money.of("1", "XXX")


def test_currency_is_upper_cased() -> None:
    assert Money.of("5", "aed").currency == "AED"


def test_rounding_half_up_for_display() -> None:
    assert Money.of("10.005", "SAR").rounded().amount == Decimal("10.01")
    assert Money.of("1.2345", "KWD").rounded().amount == Decimal("1.235")


def test_arithmetic_same_currency() -> None:
    a = Money.of("80", "SAR")
    b = Money.of("99", "SAR")
    assert (a + b).amount == Decimal("179")
    assert (b - a).amount == Decimal("19")
    assert (a * 2).amount == Decimal("160")
    assert (a * Decimal("0.5")).amount == Decimal("40.0")
    assert a < b


def test_cross_currency_is_an_error() -> None:
    with pytest.raises(CurrencyMismatchError):
        _ = Money.of("1", "SAR") + Money.of("1", "AED")
    with pytest.raises(CurrencyMismatchError):
        _ = Money.of("1", "SAR") < Money.of("1", "AED")


def test_multiply_by_float_rejected() -> None:
    with pytest.raises(TypeError):
        _ = Money.of("1", "SAR") * 1.5  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = Money.of("1", "SAR") * True


@given(
    st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=3),
    st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=3),
)
def test_addition_is_exact_and_commutative(x: Decimal, y: Decimal) -> None:
    a, b = Money.of(x, "KWD"), Money.of(y, "KWD")
    assert (a + b).amount == x + y
    assert (a + b) == (b + a)
