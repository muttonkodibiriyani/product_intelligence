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


class FetchMethod(StrEnum):
    """Concrete collection method, recorded for audit on every evidence row (ADR-0003).

    Each method belongs to exactly one ladder rung, so the rung can never contradict the method.
    """

    SITE_API = "site_api"
    EMBEDDED_JSON = "embedded_json"
    SITEMAP = "sitemap"
    CURL_CFFI = "curl_cffi"
    PLAYWRIGHT = "playwright"
    SCRAPLING = "scrapling"
    CAMOUFOX = "camoufox"
    PATCHRIGHT = "patchright"
    EGRESS_VARIATION = "egress_variation"
    RESIDENTIAL_PROXY = "residential_proxy"

    @property
    def rung(self) -> LadderRung:
        """The ladder rung this method belongs to."""
        return _METHOD_RUNG[self]


_METHOD_RUNG: dict[FetchMethod, LadderRung] = {
    FetchMethod.SITE_API: LadderRung.SITE_DATA,
    FetchMethod.EMBEDDED_JSON: LadderRung.SITE_DATA,
    FetchMethod.SITEMAP: LadderRung.SITE_DATA,
    FetchMethod.CURL_CFFI: LadderRung.IMPERSONATED_HTTP,
    FetchMethod.PLAYWRIGHT: LadderRung.BROWSER,
    FetchMethod.SCRAPLING: LadderRung.STEALTH_BROWSER,
    FetchMethod.CAMOUFOX: LadderRung.STEALTH_BROWSER,
    FetchMethod.PATCHRIGHT: LadderRung.STEALTH_BROWSER,
    FetchMethod.EGRESS_VARIATION: LadderRung.EGRESS_VARIATION,
    FetchMethod.RESIDENTIAL_PROXY: LadderRung.PAID_PROXY,
}


class Market(StrEnum):
    """Markets a source context can target (ADR-0004). Values are ISO 3166-1 alpha-2 codes."""

    KSA = "SA"
    UAE = "AE"

    @property
    def currency(self) -> str:
        """ISO 4217 currency every price in this market is stated in."""
        return _MARKET_CURRENCY[self]

    @property
    def time_zone(self) -> str:
        """IANA time zone used for the market's local day (SRC-06)."""
        return _MARKET_TIME_ZONE[self]


_MARKET_CURRENCY: dict[Market, str] = {Market.KSA: "SAR", Market.UAE: "AED"}
_MARKET_TIME_ZONE: dict[Market, str] = {Market.KSA: "Asia/Riyadh", Market.UAE: "Asia/Dubai"}


class Locale(StrEnum):
    """Collection and content locales (SCP-06, CAT-06). Both are collected for every source."""

    EN = "en"
    AR = "ar"

    @property
    def is_rtl(self) -> bool:
        """True for right-to-left scripts."""
        return self is Locale.AR


class SourceKind(StrEnum):
    """How a source is reached (blueprint 5.1 ``source.kind``)."""

    WEB = "web"
    APP = "app"
    FEED = "feed"
    AGGREGATOR = "aggregator"
    OFFLINE = "offline"


class Device(StrEnum):
    """Device profile a context is collected as (SRC-02)."""

    DESKTOP = "desktop"
    MOBILE = "mobile"
    APP = "app"


class ImageRole(StrEnum):
    """Role of an image on a listing (blueprint 5.1 ``listing_image.role``)."""

    MAIN = "main"
    ALT = "alt"
    SWATCH = "swatch"
    MODEL = "model"
    TEXTURE = "texture"


class Concentration(StrEnum):
    """Fragrance concentration. Different concentrations are never an exact match (8.4, MAT-02)."""

    EXTRAIT = "extrait"
    PARFUM = "parfum"
    EDP = "edp"
    EDT = "edt"
    COLOGNE = "cologne"


class PromotionMechanic(StrEnum):
    """Normalised promotion mechanic (PRC-09). Anything unparsed is UNCLASSIFIED, never guessed."""

    PERCENT_OFF = "percent_off"
    AMOUNT_OFF = "amount_off"
    FIXED_PRICE = "fixed_price"
    MULTIBUY = "multibuy"
    BUY_X_GET_Y = "buy_x_get_y"
    GIFT_WITH_PURCHASE = "gift_with_purchase"
    FREE_SHIPPING = "free_shipping"
    COUPON = "coupon"
    UNCLASSIFIED = "unclassified"
