"""Frozen source records preserving Ulta UAE catalogue semantics.

Missing monetary values always carry a reason. They are never coerced to zero.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from pi_core import FieldState, PriceType

PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class FrozenModel(BaseModel):
    """Strict, immutable base for source records."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class Locale(StrEnum):
    """Locales in the UAE pilot."""

    EN = "en"
    AR = "ar"


class LocalizedText(FrozenModel):
    """Text as published in each storefront locale."""

    en: str | None = None
    ar: str | None = None

    @model_validator(mode="after")
    def at_least_one_locale(self) -> Self:
        if not self.en and not self.ar:
            raise ValueError("at least one locale value is required")
        return self


class PriceValue(FrozenModel):
    """One price slot; absent amounts require provenance instead of zero."""

    amount: PositiveDecimal | None
    currency: Literal["AED"] = "AED"
    field_state: FieldState | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def explain_missing_value(self) -> Self:
        if self.amount is None and self.field_state is None:
            raise ValueError("a missing price requires a field_state; missing is never zero")
        if self.field_state is FieldState.OBSERVED:
            raise ValueError("observed is not a missing-price reason")
        if self.amount is not None and (self.field_state is not None or self.reason is not None):
            raise ValueError("a present price cannot have a missing field_state or reason")
        return self


class Prices(FrozenModel):
    """All price concepts exposed by the source."""

    price_type: PriceType = PriceType.FULL
    current: PriceValue
    regular: PriceValue
    promo: PriceValue
    member: PriceValue
    range_min: PriceValue = Field(
        default_factory=lambda: PriceValue(
            amount=None, field_state=FieldState.NOT_APPLICABLE, reason="not a range"
        )
    )
    range_max: PriceValue = Field(
        default_factory=lambda: PriceValue(
            amount=None, field_state=FieldState.NOT_APPLICABLE, reason="not a range"
        )
    )

    @model_validator(mode="after")
    def validate_price_shape(self) -> Self:
        if self.price_type is PriceType.RANGE:
            if self.current.amount is not None:
                raise ValueError("range price cannot have a single current amount")
            if self.current.field_state is not FieldState.NOT_APPLICABLE:
                raise ValueError("range current price must be explicitly not applicable")
            if self.range_min.amount is None or self.range_max.amount is None:
                raise ValueError("range price requires minimum and maximum amounts")
            if self.range_min.amount > self.range_max.amount:
                raise ValueError("range minimum cannot exceed maximum")
        elif self.price_type is PriceType.QUOTE_ONLY:
            if self.current.amount is not None:
                raise ValueError("quote-only price cannot have a current amount")
            if self.current.field_state is not FieldState.NOT_APPLICABLE:
                raise ValueError("quote-only current price must be explicitly not applicable")
        elif self.current.amount is None:
            raise ValueError("a numeric price type requires a current amount")
        return self


class Promotion(FrozenModel):
    """Promotion attached to a product or variant."""

    promotion_id: str | None = None
    title: LocalizedText
    description: LocalizedText | None = None
    terms: LocalizedText | None = None


class StockState(StrEnum):
    """Source stock state. Access failures remain unknown."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class Stock(FrozenModel):
    """Availability without treating collection failures as sell-out."""

    state: StockState
    quantity: Annotated[int, Field(ge=0)] | None = None
    reason: str | None = None
    source_field_observed: bool = False

    @model_validator(mode="after")
    def validate_state_details(self) -> Self:
        if self.state is StockState.UNKNOWN and not self.reason:
            raise ValueError("unknown stock requires a reason")
        if self.state is StockState.OUT_OF_STOCK and self.quantity not in {None, 0}:
            raise ValueError("out-of-stock quantity must be zero or absent")
        if self.state is StockState.OUT_OF_STOCK and not self.source_field_observed:
            raise ValueError("out-of-stock requires an explicitly observed source field")
        return self


class Content(FrozenModel):
    """Localized catalogue copy."""

    name: LocalizedText
    short_description: LocalizedText | None = None
    description: LocalizedText | None = None
    ingredients: LocalizedText | None = None
    directions: LocalizedText | None = None


class Ratings(FrozenModel):
    """Aggregate source ratings."""

    average: NonNegativeDecimal | None = None
    count: Annotated[int, Field(ge=0)] | None = None
    rating_scale: PositiveDecimal | None = None
    field_state: FieldState | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def complete_or_explain(self) -> Self:
        present = (self.average is not None, self.count is not None, self.rating_scale is not None)
        if len(set(present)) != 1:
            raise ValueError("rating average, count, and scale must all be present or absent")
        if self.average is None and self.field_state is None:
            raise ValueError("missing ratings require a field_state")
        if self.field_state is FieldState.OBSERVED:
            raise ValueError("observed is not a missing-ratings reason")
        if self.average is not None and (self.field_state is not None or self.reason is not None):
            raise ValueError("present ratings cannot have a missing field_state or reason")
        if (
            self.average is not None
            and self.rating_scale is not None
            and self.average > self.rating_scale
        ):
            raise ValueError("rating average cannot exceed its scale")
        return self


class Image(FrozenModel):
    """Source image reference; the connector does not download images."""

    url: AnyHttpUrl
    alt: LocalizedText | None = None
    position: Annotated[int, Field(ge=0)] | None = None


class VariantRecord(FrozenModel):
    """Sellable Ulta shade/size/SKU."""

    source_variant_id: str
    sku: str | None = None
    barcode: str | None = None
    shade: LocalizedText | None = None
    size: LocalizedText | None = None
    prices: Prices
    promotions: tuple[Promotion, ...] = ()
    stock: Stock
    images: tuple[Image, ...] = ()


class ProductRecord(FrozenModel):
    """Full source-shaped Ulta UAE product record."""

    source_product_id: str
    canonical_url: AnyHttpUrl
    brand: LocalizedText
    category_path: tuple[LocalizedText, ...]
    content: Content
    ratings: Ratings
    promotions: tuple[Promotion, ...] = ()
    images: tuple[Image, ...] = ()
    variants: tuple[VariantRecord, ...]

    @model_validator(mode="after")
    def require_variants(self) -> Self:
        if not self.variants:
            raise ValueError("a product must contain at least one variant")
        return self
