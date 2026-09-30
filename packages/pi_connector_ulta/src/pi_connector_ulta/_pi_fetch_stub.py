"""TEMPORARY mirror of ``pi_fetch`` connector interface sketch v0.1.

Delete this module and import these names from ``pi_fetch`` after that package lands. The
``pi_core`` stand-ins below exist only because its PR #6 types are not on main yet.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

INTERFACE_VERSION = "0.1"


class _TemporaryPiModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


# TEMPORARY pi_core stand-ins; names and roles match PR #6's interface sketch.
class Locale(StrEnum):
    EN = "en"
    AR = "ar"


class LadderRung(IntEnum):
    SITE_DATA = 0
    PLAIN_HTTP = 1
    BROWSER = 2
    STEALTH_BROWSER = 3  # Represented by pi_core but forbidden by collection policy.
    EGRESS_VARIATION = 4
    PAID_PROXY = 5


class FetchMethod(StrEnum):
    PLAIN_HTTP = "plain_http"
    PLAYWRIGHT = "playwright"
    SITEMAP = "sitemap"
    SITE_API = "site_api"
    EMBEDDED_JSON = "embedded_json"
    EGRESS_VARIATION = "egress_variation"
    RESIDENTIAL_PROXY = "residential_proxy"


class FieldState(StrEnum):
    NOT_PUBLISHED = "not_published"
    PARSE_FAILURE = "parse_failure"


class CollectionContext(_TemporaryPiModel):
    collection_id: str


class ListingRecord(_TemporaryPiModel):
    source_listing_key: str


class OfferObservation(_TemporaryPiModel):
    source_offer_key: str


class PayloadKind(StrEnum):
    HTML = "html"
    JSON = "json"
    XML = "xml"
    IMAGE = "image"


class BlockVendor(StrEnum):
    AKAMAI = "akamai"
    CLOUDFLARE = "cloudflare"
    PERIMETERX = "perimeterx"
    DATADOME = "datadome"
    GENERIC = "generic"


class BlockVerdict(_TemporaryPiModel):
    vendor: BlockVendor
    reason: str
    http_status: int


class FetchRequest(_TemporaryPiModel):
    url: HttpUrl
    kind: PayloadKind
    locale: Locale
    headers: Mapping[str, str] = Field(default_factory=dict)
    render: bool = False
    capture_json: bool = False


class CapturedJson(_TemporaryPiModel):
    url: HttpUrl
    status: int
    body: bytes


class FetchResult(_TemporaryPiModel):
    request: FetchRequest
    final_url: HttpUrl
    http_status: int
    content_type: str | None
    body: bytes
    headers: Mapping[str, str]
    captured_json: tuple[CapturedJson, ...] = ()
    ladder_rung_used: LadderRung
    fetch_method: FetchMethod
    egress: str
    retrieved_at: datetime
    elapsed_ms: int
    from_cache: bool
    block: BlockVerdict | None
    evidence_uri: str

    @property
    def ok(self) -> bool:
        return 200 <= self.http_status < 300 and self.block is None


class DiscoveredItem(_TemporaryPiModel):
    url: HttpUrl
    kind: PayloadKind
    locale: Locale
    source_listing_key: str | None = None
    lastmod: datetime | None = None
    render: bool = False


class ParseOutput(_TemporaryPiModel):
    listings: tuple[ListingRecord, ...]
    offers: tuple[OfferObservation, ...]
    follow: tuple[DiscoveredItem, ...] = ()
    field_gaps: Mapping[str, FieldState] = Field(default_factory=dict)


class ParseError(Exception):
    """A source payload no longer matches its expected layout."""


@runtime_checkable
class Connector(Protocol):
    source_key: ClassVar[str]
    connector_version: ClassVar[str]

    def discover(self, ctx: CollectionContext) -> Iterator[DiscoveredItem]: ...

    def requests_for(
        self, item: DiscoveredItem, ctx: CollectionContext
    ) -> Sequence[FetchRequest]: ...

    def parse(self, result: FetchResult, ctx: CollectionContext) -> ParseOutput: ...
