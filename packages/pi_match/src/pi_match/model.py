"""Input records and match output for the first-pass matcher."""

from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from pi_core.base import PiModel


class ProductRecord(PiModel):
    """One product (or variant) from one retailer snapshot, as published. Missing stays None."""

    source: str = Field(min_length=1)  # e.g. "ulta_ae", "sephora_ae"
    source_key: str = Field(min_length=1)  # the retailer's own product/variant id
    brand: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str | None = None
    size: str | None = None  # size text as published, e.g. "50 ml"; else parsed from the name
    shade: str | None = None
    gtin: str | None = None
    category: str | None = None
    price: Decimal | None = None
    currency: str | None = None


class Bucket(StrEnum):
    """First-pass confidence buckets."""

    EXACT = "exact"
    PROBABLE = "probable"
    CANDIDATE = "candidate"


class UnitPrice(PiModel):
    """Price per 1 ml or 1 g, when both size and price are known."""

    amount: Decimal
    currency: str
    unit: str


class MatchPair(PiModel):
    """A scored Ulta↔Sephora pair with the reasons behind its bucket."""

    left_source: str
    left_key: str
    right_source: str
    right_key: str
    brand_key: str
    left_name: str
    right_name: str
    bucket: Bucket
    score: Decimal
    reasons: tuple[str, ...]
    left_price: Decimal | None
    right_price: Decimal | None
    currency: str | None
    left_unit_price: UnitPrice | None
    right_unit_price: UnitPrice | None
    #: (right - left) / left for the same currency; per unit when both sizes are known.
    price_gap_pct: Decimal | None
    price_basis: str | None  # "unit" | "item" | None (not comparable)


class BrandOverlap(PiModel):
    """Brand keys found in both snapshots, and in only one."""

    both: tuple[str, ...]
    only_left: tuple[str, ...]
    only_right: tuple[str, ...]
    left_brand_count: int
    right_brand_count: int
