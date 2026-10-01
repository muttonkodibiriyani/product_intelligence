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
    """Why a field is null. Missing is data, never zero (DQ-02).

    ``OBSERVED`` is the one positive member: it qualifies a never-null field (availability) as
    actually read from the page. It is never a reason for a null.
    """

    NOT_PUBLISHED = "not_published"
    NOT_APPLICABLE = "not_applicable"
    RESTRICTED = "restricted"
    PARSE_FAILURE = "parse_failure"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    OBSERVED = "observed"


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
    """Collection escalation ladder (blueprint section 6.3). Higher rungs cost more.

    Values are persisted and never change. STEALTH_BROWSER (3) is forbidden by the owner's
    guardrail: it stays for audit and history but no context, run or evidence may use it, so
    escalation goes 2 -> 4. PLAIN_HTTP (1) is plain HTTP with normal headers; TLS/JA3/HTTP2
    fingerprint impersonation is not allowed (owner ruling). If a real browser (2) from Gulf egress
    (4) is still blocked, the source is marked blocked and a Proxy Decision Report is written.
    """

    SITE_DATA = 0
    PLAIN_HTTP = 1
    BROWSER = 2
    STEALTH_BROWSER = 3
    EGRESS_VARIATION = 4
    PAID_PROXY = 5

    @property
    def is_paid(self) -> bool:
        """Paid rungs require an explicit owner decision before use."""
        return self is LadderRung.PAID_PROXY

    @property
    def is_permitted(self) -> bool:
        """False for rungs the program forbids outright, whatever a context's cap says."""
        return self not in FORBIDDEN_RUNGS


#: Rungs no collection may use (owner guardrail): stealth browsers, fingerprint rotation, cookie
#: reuse. Mirrored by CHECK constraints in pi_db.
FORBIDDEN_RUNGS: frozenset[LadderRung] = frozenset({LadderRung.STEALTH_BROWSER})


class FetchMethod(StrEnum):
    """Concrete collection method, recorded for audit on every evidence row (ADR-0003).

    Each method belongs to exactly one ladder rung, so the rung can never contradict the method.
    There is deliberately no method for the forbidden STEALTH_BROWSER rung.
    """

    SITE_API = "site_api"
    EMBEDDED_JSON = "embedded_json"
    SITEMAP = "sitemap"
    # Plain HTTP (httpx), normal headers.
    PLAIN_HTTP = "plain_http"
    PLAYWRIGHT = "playwright"
    EGRESS_VARIATION = "egress_variation"
    RESIDENTIAL_PROXY = "residential_proxy"
    # A catalogue feed (CSV/XLSX/JSON) handed to us by a customer or partner and imported
    # offline (tools/offline_import). Nothing is fetched from the source's site, so no ladder
    # rung is climbed and no evasion is involved: it sits on SITE_DATA (0) with the other
    # first-party data methods. Added by pi_db migration 0003.
    OFFLINE_IMPORT = "offline_import"

    @property
    def rung(self) -> LadderRung:
        """The ladder rung this method belongs to."""
        return _METHOD_RUNG[self]


_METHOD_RUNG: dict[FetchMethod, LadderRung] = {
    FetchMethod.SITE_API: LadderRung.SITE_DATA,
    FetchMethod.EMBEDDED_JSON: LadderRung.SITE_DATA,
    FetchMethod.SITEMAP: LadderRung.SITE_DATA,
    FetchMethod.PLAIN_HTTP: LadderRung.PLAIN_HTTP,
    FetchMethod.PLAYWRIGHT: LadderRung.BROWSER,
    FetchMethod.EGRESS_VARIATION: LadderRung.EGRESS_VARIATION,
    FetchMethod.RESIDENTIAL_PROXY: LadderRung.PAID_PROXY,
    FetchMethod.OFFLINE_IMPORT: LadderRung.SITE_DATA,
}


class Market(StrEnum):
    """Deprecated (ADR-0007): the pilot's two markets. Use ``CountryCode`` plus the context's own
    ``currency`` and ``time_zone``; members still validate as country codes."""

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
    """Deprecated (ADR-0007): the pilot's two locales. Use ``LocaleTag`` (BCP 47) and
    ``pi_core.markets.is_rtl``; members still validate as locale tags."""

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
