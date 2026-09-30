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
        price.amount = Decimal("2")  # type: ignore[misc]


def test_localized_text_needs_a_non_empty_locale() -> None:
    with pytest.raises(ValidationError, match="at least one locale"):
        LocalizedText(en="", ar=None)


def test_unknown_stock_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="requires a reason"):
        Stock(state=StockState.UNKNOWN)


def test_out_of_stock_rejects_positive_quantity() -> None:
    with pytest.raises(ValidationError, match="quantity must be zero"):
        Stock(state=StockState.OUT_OF_STOCK, quantity=2, source_field_observed=True)


def test_out_of_stock_requires_an_explicit_source_field() -> None:
    with pytest.raises(ValidationError, match="explicitly observed"):
        Stock(state=StockState.OUT_OF_STOCK, quantity=0)
    stock = Stock(state=StockState.OUT_OF_STOCK, quantity=0, source_field_observed=True)
    assert stock.state is StockState.OUT_OF_STOCK


def test_ratings_are_complete_or_explained() -> None:
    with pytest.raises(ValidationError, match="all be present"):
        Ratings(average=Decimal("4"), count=None)
    with pytest.raises(ValidationError, match="missing ratings require"):
        Ratings()
    assert Ratings(average=None, count=None, reason="not published").average is None


def test_ratings_carry_and_enforce_the_published_scale() -> None:
    rating = Ratings(average=Decimal("7.5"), count=4, rating_scale=Decimal("10"))
    assert rating.rating_scale == Decimal("10")
    with pytest.raises(ValidationError, match="cannot exceed"):
        Ratings(average=Decimal("7.5"), count=4, rating_scale=Decimal("5"))
