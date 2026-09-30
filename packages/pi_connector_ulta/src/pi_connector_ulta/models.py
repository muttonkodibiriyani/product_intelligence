"""Frozen source records preserving Ulta UAE catalogue semantics.

Missing monetary values always carry a reason. They are never coerced to zero.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

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
    reason: str | None = None

    @model_validator(mode="after")
    def explain_missing_value(self) -> Self:
        if self.amount is None and not self.reason:
            raise ValueError("a missing price requires a reason; missing is never zero")
        if self.amount is not None and self.reason is not None:
            raise ValueError("a present price cannot have a missing reason")
        return self


class Prices(FrozenModel):
    """All price concepts exposed by the source."""

    current: PriceValue
    regular: PriceValue
    promo: PriceValue
    member: PriceValue


class Promotion(FrozenModel):
    """Promotion attached to a product or variant."""

    promotion_id: str | None = None
    title: LocalizedText
    description: LocalizedText | None = None
    terms: LocalizedText | None = None


class StockState(StrEnum):
    """Source stock state. Access failures remain unknown or blocked."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class Stock(FrozenModel):
    """Availability without treating collection failures as sell-out."""

    state: StockState
    quantity: Annotated[int, Field(ge=0)] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_state_details(self) -> Self:
        if self.state in {StockState.UNKNOWN, StockState.BLOCKED} and not self.reason:
            raise ValueError("unknown or blocked stock requires a reason")
        if self.state is StockState.BLOCKED and self.quantity is not None:
            raise ValueError("blocked stock cannot carry a quantity")
        if self.state is StockState.OUT_OF_STOCK and self.quantity not in {None, 0}:
            raise ValueError("out-of-stock quantity must be zero or absent")
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

    average: Annotated[Decimal, Field(ge=0, le=5, allow_inf_nan=False)] | None = None
    count: Annotated[int, Field(ge=0)] | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def complete_or_explain(self) -> Self:
        if (self.average is None) != (self.count is None):
            raise ValueError("rating average and count must both be present or absent")
        if self.average is None and not self.reason:
            raise ValueError("missing ratings require a reason")
        if self.average is not None and self.reason is not None:
            raise ValueError("present ratings cannot have a missing reason")
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


# TODO(pi-core#6): map ProductRecord/VariantRecord into canonical pi_core records once PR #6 lands.
