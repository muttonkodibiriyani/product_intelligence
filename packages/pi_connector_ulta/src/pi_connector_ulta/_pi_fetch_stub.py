"""TEMPORARY mirror of ``pi_fetch`` connector interface sketch v0.1.

Delete this module and import these names from ``pi_fetch`` after that package lands. The
``pi_core`` stand-ins below exist only because its PR #6 types are not on main yet.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Protocol, overload, runtime_checkable

from pydantic import Field, HttpUrl, model_validator

from pi_core import (
    CollectionContext,
    FetchMethod,
    FieldState,
    LadderRung,
    ListingFields,
    ListingRecord,
    Locale,
    OfferFields,
    OfferObservation,
    PiModel,
)
from pi_core.context import check_rung
from pi_core.types import DbId, NonEmptyStr, UtcDatetime

INTERFACE_VERSION = "0.2"

__all__ = [
    "INTERFACE_VERSION",
    "BlockVendor",
    "BlockVerdict",
    "CapturedJson",
    "CollectionContext",
    "Connector",
    "DiscoveredItem",
    "FetchMethod",
    "FetchRequest",
    "FetchResult",
    "FieldState",
    "LadderRung",
    "ListingDraft",
    "Locale",
    "OfferDraft",
    "ParseError",
    "ParseOutput",
    "PayloadKind",
    "to_canonical",
]


class _TemporaryPiModel(PiModel):
    """TEMPORARY base only for pi_fetch-owned transport records."""


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

    @model_validator(mode="after")
    def validate_fetch_audit(self) -> FetchResult:
        check_rung(self.ladder_rung_used, self.fetch_method)
        return self

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


class ListingDraft(ListingFields):
    """Source-keyed listing without persistence-assigned IDs (v0.2)."""


class OfferDraft(OfferFields):
    """Source-keyed observation without persistence-assigned IDs (v0.2)."""

    source_listing_key: NonEmptyStr


@overload
def to_canonical(
    draft: ListingDraft,
    *,
    source_id: DbId,
    evidence_id: DbId,
    source_listing_id: None = None,
    ingested_at: None = None,
    context: None = None,
) -> ListingRecord: ...


@overload
def to_canonical(
    draft: OfferDraft,
    *,
    source_id: None = None,
    evidence_id: DbId,
    source_listing_id: DbId,
    ingested_at: UtcDatetime,
    context: CollectionContext,
) -> OfferObservation: ...


def to_canonical(  # noqa: PLR0913 - one typed adapter for both v0.2 draft variants
    draft: ListingDraft | OfferDraft,
    *,
    source_id: DbId | None = None,
    evidence_id: DbId,
    source_listing_id: DbId | None = None,
    ingested_at: UtcDatetime | None = None,
    context: CollectionContext | None = None,
) -> ListingRecord | OfferObservation:
    """Pipeline-only validated conversion after evidence/listing persistence."""
    values = draft.model_dump(mode="python")
    if isinstance(draft, ListingDraft):
        if (
            source_id is None
            or source_listing_id is not None
            or ingested_at is not None
            or context is not None
        ):
            raise ValueError("listing conversion requires source_id only")
        return ListingRecord.model_validate(
            values | {"source_id": source_id, "evidence_id": evidence_id}
        )
    if source_id is not None or source_listing_id is None or ingested_at is None or context is None:
        raise ValueError("offer conversion requires source_listing_id, ingested_at, and context")
    values.pop("source_listing_key")
    observation = OfferObservation.model_validate(
        values
        | {
            "source_listing_id": source_listing_id,
            "evidence_id": evidence_id,
            "ingested_at": ingested_at,
        }
    )
    observation.check_context(context)
    return observation


class ParseOutput(_TemporaryPiModel):
    listings: tuple[ListingDraft, ...]
    offers: tuple[OfferDraft, ...]
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
