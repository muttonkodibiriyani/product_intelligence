"""Fetch request and result types shared by the ladder, transports and connectors.

A ``FetchResult`` is always returned, never raised: a blocked fetch carries a ``BlockVerdict`` and
``ok`` is false, so the connector does not parse it and the run records the listing as blocked or
not observed (DAT-06), never out of stock.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Self

from pydantic import Field, HttpUrl, field_validator, model_validator

from pi_core import Device, FetchMethod, LadderRung, Locale, PiModel
from pi_core.context import check_rung
from pi_core.types import NonEmptyStr, UtcDatetime

#: Headers a connector may not set: credentials, cookies (no WAF-cookie replay) and the
#: identity the fetch layer controls (no User-Agent rotation).
FORBIDDEN_REQUEST_HEADERS = frozenset(
    {"authorization", "cookie", "host", "proxy-authorization", "user-agent"}
)
TOO_MANY_REQUESTS = 429
#: Headers never kept on a result, so evidence and logs hold no session cookies.
REDACTED_RESPONSE_HEADERS = frozenset({"cookie", "set-cookie", "set-cookie2"})


class PayloadKind(StrEnum):
    """What a request expects back; picks the Accept header and the rung-0 fetch method."""

    HTML = "html"
    JSON = "json"
    XML = "xml"
    IMAGE = "image"


class BrowserEngine(StrEnum):
    """Stock Playwright browser builds. Which one a source uses is pinned by config (owner)."""

    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class BrowserProfile(PiModel):
    """The browser a source is fetched with, recorded on every browser result as evidence.

    Pinned per source by the owner (e.g. ulta.ae = webkit). The fetch layer never switches
    engine on its own: a block on the pinned engine is returned as blocked.
    """

    engine: BrowserEngine
    headless: bool = True
    #: Desktop only for now: a mobile profile would need device emulation (not built yet).
    device: Device = Device.DESKTOP
    viewport_width: int = Field(default=1366, ge=320, le=3840)
    viewport_height: int = Field(default=768, ge=320, le=2160)

    @field_validator("device")
    @classmethod
    def _check_device(cls, value: Device) -> Device:
        if value is not Device.DESKTOP:
            msg = f"browser device profile {value.value!r} is not supported yet (desktop only)"
            raise ValueError(msg)
        return value


class BlockVendor(StrEnum):
    """Who blocked a fetch. GENERIC covers a plain 403/429 or an empty payload."""

    AKAMAI = "akamai"
    CLOUDFLARE = "cloudflare"
    PERIMETERX = "perimeterx"
    DATADOME = "datadome"
    GENERIC = "generic"


class BlockKind(StrEnum):
    """What kind of refusal a verdict records.

    Only CHALLENGE and BLOCKED feed a source's blocked state, and with it the Proxy Decision
    Report and the API-route refusal. RATE_LIMITED (any 429 without a challenge) backs the host
    off and leaves its listings not observed, but never marks the source blocked.
    """

    CHALLENGE = "challenge"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"


class BlockVerdict(PiModel):
    """Why a response was refused: challenge, block or rate limit. Recorded, never solved or
    retried; ``ok`` is false for every verdict."""

    kind: BlockKind
    vendor: BlockVendor
    reason: NonEmptyStr
    http_status: int = Field(ge=100, le=599)

    @property
    def marks_source_blocked(self) -> bool:
        """True for a challenge or block; false for a rate limit."""
        return self.kind is not BlockKind.RATE_LIMITED


def redact_headers(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Lower-case names, join repeated headers with ", " and drop cookies, so a result can never
    carry a session."""
    merged: dict[str, str] = {}
    for name, value in pairs:
        key = name.lower()
        if key not in REDACTED_RESPONSE_HEADERS:
            merged[key] = f"{merged[key]}, {value}" if key in merged else value
    return merged


class FetchRequest(PiModel):
    """One URL a connector wants fetched. Connectors build these; they never fetch themselves."""

    url: HttpUrl
    kind: PayloadKind
    #: Sets Accept-Language together with the context's market.
    locale: Locale
    #: Extra non-auth headers only; see ``FORBIDDEN_REQUEST_HEADERS``.
    headers: Mapping[str, str] = Field(default_factory=dict)
    #: The page needs JavaScript: the ladder starts at the browser rung.
    render: bool = False
    #: Browser rung: keep the JSON responses the page itself loads.
    capture_json: bool = False

    @field_validator("headers")
    @classmethod
    def _check_headers(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        refused = sorted(k for k in value if k.lower() in FORBIDDEN_REQUEST_HEADERS)
        if refused:
            msg = f"headers not allowed on a fetch request: {refused}"
            raise ValueError(msg)
        return value


class CapturedJson(PiModel):
    """A JSON response the rendered page loaded by itself (browser rung only)."""

    url: HttpUrl
    status: int = Field(ge=100, le=599)
    body: bytes


class FetchResult(PiModel):
    """Outcome of one fetch, with the audit of how it was made. Never raised; check ``ok``."""

    request: FetchRequest
    final_url: HttpUrl
    http_status: int = Field(ge=100, le=599)
    content_type: str | None
    body: bytes
    #: Lower-case names, cookies removed (``redact_headers``).
    headers: Mapping[str, str]
    captured_json: tuple[CapturedJson, ...] = ()
    ladder_rung_used: LadderRung
    fetch_method: FetchMethod
    egress: NonEmptyStr
    #: The browser that made a browser-engine fetch; None for plain HTTP.
    browser: BrowserProfile | None = None
    retrieved_at: UtcDatetime
    elapsed_ms: int = Field(ge=0)
    #: True when a 304 revalidation returned the stored payload.
    from_cache: bool
    #: Set: the connector must not parse; listings become blocked / not_observed.
    block: BlockVerdict | None
    #: Where the raw payload is stored.
    evidence_uri: NonEmptyStr

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        # Refuses the forbidden rung and a method that does not belong to the rung.
        check_rung(self.ladder_rung_used, self.fetch_method)
        leaked = sorted(k for k in self.headers if k.lower() in REDACTED_RESPONSE_HEADERS)
        if leaked:
            msg = f"result headers must be redacted: {leaked}"
            raise ValueError(msg)
        if self.fetch_method is FetchMethod.PLAYWRIGHT and self.browser is None:
            msg = "a browser fetch must record its browser profile"
            raise ValueError(msg)
        if self.browser is not None and self.ladder_rung_used not in {
            LadderRung.BROWSER,
            LadderRung.EGRESS_VARIATION,
        }:
            msg = "only a browser fetch has a browser profile"
            raise ValueError(msg)
        if self.captured_json and self.browser is None:
            msg = "captured_json only comes from a browser fetch"
            raise ValueError(msg)
        if self.captured_json and self.ladder_rung_used not in {
            LadderRung.BROWSER,
            LadderRung.EGRESS_VARIATION,
        }:
            msg = "captured_json only comes from a browser fetch"
            raise ValueError(msg)
        return self

    @property
    def ok(self) -> bool:
        """2xx and not blocked: the only results a connector may parse."""
        return 200 <= self.http_status < 300 and self.block is None

    @property
    def rate_limited(self) -> bool:
        """A 429 without a challenge (``BlockKind.RATE_LIMITED``): not parsed, listings not
        observed, and the source is not marked blocked."""
        return self.block is not None and self.block.kind is BlockKind.RATE_LIMITED
