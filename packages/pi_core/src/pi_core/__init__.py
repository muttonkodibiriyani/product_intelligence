"""Shared domain model for the Product Intelligence platform.

Everything here is dependency-free and imported by every other package, so it
must stay small, typed and exhaustively tested.
"""

from pi_core.enums import (
    AvailabilityState,
    Channel,
    CoverageStatus,
    FieldState,
    LadderRung,
    MatchClass,
    PriceType,
    QualityStatus,
    ReviewState,
    TaxStatus,
)
from pi_core.money import CURRENCY_EXPONENTS, CurrencyMismatchError, Money

__all__ = [
    "CURRENCY_EXPONENTS",
    "AvailabilityState",
    "Channel",
    "CoverageStatus",
    "CurrencyMismatchError",
    "FieldState",
    "LadderRung",
    "MatchClass",
    "Money",
    "PriceType",
    "QualityStatus",
    "ReviewState",
    "TaxStatus",
]

__version__ = "0.1.0"
