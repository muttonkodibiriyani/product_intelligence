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
from pi_core.listing import ImageRef, ListingRecord, gtin14, is_valid_gtin
from pi_core.money import CURRENCY_EXPONENTS, CurrencyMismatchError, Money
from pi_core.observation import InstallmentPlan, OfferObservation
from pi_core.promotion import PromotionRecord
from pi_core.types import content_hash_of

__all__ = [
    "CURRENCY_EXPONENTS",
    "FORBIDDEN_RUNGS",
    "AvailabilityState",
    "Channel",
    "CollectionContext",
    "Concentration",
    "CoverageStatus",
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
    "ListingRecord",
    "Locale",
    "Market",
    "MatchClass",
    "Money",
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
    "is_valid_gtin",
    "logical_key",
]

__version__ = "0.1.0"
