from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pi_connector_ulta.models import (
    LocalizedText,
    PriceValue,
    Ratings,
    Stock,
    StockState,
)


@given(st.decimals(min_value="0.01", max_value="100000", allow_nan=False, allow_infinity=False))
def test_positive_decimal_prices_are_preserved(amount: Decimal) -> None:
    price = PriceValue(amount=amount)
    assert price.amount == amount
    assert isinstance(price.amount, Decimal)


@given(st.decimals(max_value="0", allow_nan=False, allow_infinity=False))
def test_non_positive_prices_are_rejected(amount: Decimal) -> None:
    with pytest.raises(ValidationError):
        PriceValue(amount=amount)


def test_missing_price_requires_reason_and_never_becomes_zero() -> None:
    with pytest.raises(ValidationError, match="missing price requires a reason"):
        PriceValue(amount=None)
    missing = PriceValue(amount=None, reason="not published")
    assert missing.amount is None


def test_present_price_rejects_missing_reason() -> None:
    with pytest.raises(ValidationError, match="present price"):
        PriceValue(amount=Decimal("1"), reason="not published")


def test_models_are_strict_and_frozen() -> None:
    with pytest.raises(ValidationError):
        PriceValue(amount=1.5)  # type: ignore[arg-type]
    price = PriceValue(amount=Decimal("1"))
    with pytest.raises(ValidationError):
        price.amount = Decimal("2")


def test_localized_text_needs_a_non_empty_locale() -> None:
    with pytest.raises(ValidationError, match="at least one locale"):
        LocalizedText(en="", ar=None)


def test_unknown_and_blocked_stock_require_reasons() -> None:
    for state in (StockState.UNKNOWN, StockState.BLOCKED):
        with pytest.raises(ValidationError, match="requires a reason"):
            Stock(state=state)


def test_blocked_stock_cannot_claim_quantity() -> None:
    with pytest.raises(ValidationError, match="cannot carry a quantity"):
        Stock(state=StockState.BLOCKED, quantity=0, reason="403")


def test_out_of_stock_rejects_positive_quantity() -> None:
    with pytest.raises(ValidationError, match="quantity must be zero"):
        Stock(state=StockState.OUT_OF_STOCK, quantity=2)


def test_ratings_are_complete_or_explained() -> None:
    with pytest.raises(ValidationError, match="both be present"):
        Ratings(average=Decimal("4"), count=None)
    with pytest.raises(ValidationError, match="missing ratings require"):
        Ratings()
    assert Ratings(average=None, count=None, reason="not published").average is None
