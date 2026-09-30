"""Controlled vocabularies used across the platform.

These values are persisted, so members may be added but never renamed or
removed without a migration (see docs/adr).
"""

from enum import IntEnum, StrEnum


class AvailabilityState(StrEnum):
    """Observed availability of an offer. A failed crawl is never OUT_OF_STOCK (DAT-06)."""

    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    NOT_DELIVERABLE = "not_deliverable"
    REMOVED = "removed"
    NOT_OBSERVED = "not_observed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"

    @property
    def is_known(self) -> bool:
        """True when the state is an actual observation of stock, usable as a denominator."""
        return self in {
            AvailabilityState.IN_STOCK,
            AvailabilityState.LOW_STOCK,
            AvailabilityState.OUT_OF_STOCK,
        }


class FieldState(StrEnum):
    """Why a field is null. Missing is data, never zero (DQ-02)."""

    NOT_PUBLISHED = "not_published"
    NOT_APPLICABLE = "not_applicable"
    RESTRICTED = "restricted"
    PARSE_FAILURE = "parse_failure"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class PriceType(StrEnum):
    """Kinds of price kept strictly separate (PRC-01)."""

    FULL = "full"
    PROMOTIONAL = "promotional"
    MEMBER = "member"
    SUBSCRIPTION = "subscription"
    INSTALLMENT = "installment"
    RANGE = "range"
    QUOTE_ONLY = "quote_only"

    @property
    def rankable(self) -> bool:
        """Only full or promotional single prices may be ranked as selling prices (UAT-04)."""
        return self in {PriceType.FULL, PriceType.PROMOTIONAL}


class TaxStatus(StrEnum):
    """Tax basis of a displayed price (PRC-04). UNKNOWN is never treated as tax-free."""

    INCLUDED = "included"
    EXCLUDED = "excluded"
    EXEMPT = "exempt"
    UNKNOWN = "unknown"


class Channel(StrEnum):
    """Commercial channel of an observation (PRC-14). Pickup is never dine-in."""

    ONLINE = "online"
    MARKETPLACE = "marketplace"
    DELIVERY = "delivery"
    PICKUP = "pickup"
    DINE_IN_EVIDENCED = "dine_in_evidenced"
    OFFLINE_AUDIT = "offline_audit"


class MatchClass(StrEnum):
    """Relationship classes between variants (MAT-01)."""

    EXACT = "exact"
    FAMILY = "family"
    SIZE_NORMALIZED = "size_normalized"
    SUBSTITUTE = "substitute"


class ReviewState(StrEnum):
    """Lifecycle of a match edge (MAT-05, MAT-07)."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    LOCKED = "locked"


class QualityStatus(StrEnum):
    """Quality gate outcome of a record (DQ-05)."""

    ACCEPTED = "accepted"
    WARNING = "warning"
    QUARANTINED = "quarantined"
    CORRECTED = "corrected"


class CoverageStatus(StrEnum):
    """Coverage state of a source context (SCP-02)."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    PENDING = "pending"
    PAUSED = "paused"
    UNSUPPORTED = "unsupported"
    RETIRED = "retired"


class LadderRung(IntEnum):
    """Collection escalation ladder (blueprint section 6.3). Higher rungs cost more."""

    SITE_DATA = 0
    IMPERSONATED_HTTP = 1
    BROWSER = 2
    STEALTH_BROWSER = 3
    EGRESS_VARIATION = 4
    PAID_PROXY = 5

    @property
    def is_paid(self) -> bool:
        """Paid rungs require an explicit owner decision before use."""
        return self is LadderRung.PAID_PROXY
