"""Shared domain model for the Product Intelligence platform.

Imported by every other package, so it must stay small, typed and exhaustively tested. Its only
runtime dependency is pydantic, used for the frozen record models.
"""

from pi_core.base import FieldStateModel, PiModel
from pi_core.context import CollectionContext, Source, SourceContext
from pi_core.enums import (
    FORBIDDEN_RUNGS,
    AvailabilityState,
    Channel,
    Concentration,
    CoverageStatus,
    Device,
    FetchMethod,
    FieldState,
    ImageRole,
    LadderRung,
    Locale,
    Market,
    MatchClass,
    PriceType,
    PromotionMechanic,
    QualityStatus,
    ReviewState,
    SourceKind,
    TaxStatus,
)
from pi_core.evidence import Evidence
from pi_core.ids import logical_key
from pi_core.listing import ImageRef, ListingFields, ListingRecord, gtin14, is_valid_gtin
from pi_core.markets import COUNTRY_CODES, is_rtl, language_of, region_of
from pi_core.money import CURRENCY_EXPONENTS, CurrencyMismatchError, Money
from pi_core.observation import InstallmentPlan, OfferFields, OfferObservation
from pi_core.promotion import PromotionRecord
from pi_core.types import CountryCode, CurrencyCode, LocaleTag, content_hash_of

__all__ = [
    "COUNTRY_CODES",
    "CURRENCY_EXPONENTS",
    "FORBIDDEN_RUNGS",
    "AvailabilityState",
    "Channel",
    "CollectionContext",
    "Concentration",
    "CountryCode",
    "CoverageStatus",
    "CurrencyCode",
    "CurrencyMismatchError",
    "Device",
    "Evidence",
    "FetchMethod",
    "FieldState",
    "FieldStateModel",
    "ImageRef",
    "ImageRole",
    "InstallmentPlan",
    "LadderRung",
    "ListingFields",
    "ListingRecord",
    "Locale",
    "LocaleTag",
    "Market",
    "MatchClass",
    "Money",
    "OfferFields",
    "OfferObservation",
    "PiModel",
    "PriceType",
    "PromotionMechanic",
    "PromotionRecord",
    "QualityStatus",
    "ReviewState",
    "Source",
    "SourceContext",
    "SourceKind",
    "TaxStatus",
    "content_hash_of",
    "gtin14",
    "is_rtl",
    "is_valid_gtin",
    "language_of",
    "logical_key",
    "region_of",
]

__version__ = "0.1.0"
