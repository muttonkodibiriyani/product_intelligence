"""The connector contract (interface v0.2): discover, map to requests, parse. No network I/O.

A connector's ``parse`` is a pure, deterministic function of one ``FetchResult``: the same result
always yields equal drafts. It returns source-keyed drafts, not database records. The drafts
share pi_core's field definitions and validators (``ListingFields`` / ``OfferFields``), so a draft
that constructs is valid except for the ids the pipeline assigns later (``pi_fetch.mapping``).
Connectors never see or make up a database id.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Annotated, ClassVar, Protocol, Self, runtime_checkable

from pydantic import AfterValidator, Field, HttpUrl, model_validator

from pi_core import CollectionContext, FieldState, ListingFields, LocaleTag, OfferFields, PiModel
from pi_core.types import NonEmptyStr, UtcDatetime
from pi_fetch.types import FetchRequest, FetchResult, PayloadKind

# A URL or path, or a bare md5/sha1/sha256 digest: things that are not a site's own product id.
_NOT_A_SITE_KEY = re.compile(r"://|^[/?#]|^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})$")


def _check_source_listing_key(value: str) -> str:
    if _NOT_A_SITE_KEY.search(value):
        msg = (
            f"source_listing_key {value!r} must be the site's own stable product/variant id, "
            "not a URL, path or hash"
        )
        raise ValueError(msg)
    return value


#: The site's own stable product or variant id; never a URL, position, hash or invented id.
SourceListingKey = Annotated[NonEmptyStr, AfterValidator(_check_source_listing_key)]


class ListingDraft(ListingFields):
    """A ``ListingRecord`` without ``source_id``/``evidence_id``, keyed by the site's own id."""

    source_listing_key: SourceListingKey


#: ``OfferFields`` the pipeline fills later (matching, promotions, correction, row write, quality
#: gate). A draft leaves them at their defaults so it never carries an invented database id.
PIPELINE_OWNED_OFFER_FIELDS = frozenset(
    {"variant_id", "promotion_ids", "correction_of", "recorded_at", "quality_status"}
)


class OfferDraft(OfferFields):
    """An ``OfferObservation`` without ``source_listing_id``/``evidence_id``, linked to its listing
    by the site's own key."""

    source_listing_key: SourceListingKey

    @model_validator(mode="after")
    def _check_no_pipeline_ids(self) -> Self:
        set_fields = sorted(PIPELINE_OWNED_OFFER_FIELDS & self.model_fields_set)
        if set_fields:
            msg = f"a connector draft may not set pipeline-owned fields: {set_fields}"
            raise ValueError(msg)
        return self


class DiscoveredItem(PiModel):
    """Something ``discover`` found (sitemap entry, category tree node) to fetch later."""

    url: HttpUrl
    kind: PayloadKind
    locale: LocaleTag
    #: Stable product key when the discovery source publishes one.
    source_listing_key: SourceListingKey | None = None
    lastmod: UtcDatetime | None = None
    render: bool = False


class ParseOutput(PiModel):
    """Everything parsed from one ``FetchResult``.

    Every offer links to a listing by ``source_listing_key``: either a listing in this output or
    one declared in ``existing_listing_keys`` (e.g. a variant JSON parsed apart from its page).
    """

    #: One per product per locale.
    listings: tuple[ListingDraft, ...]
    #: One per variant, or per product when there are no variants.
    offers: tuple[OfferDraft, ...]
    #: More to fetch: pagination, variant JSON, image URLs.
    follow: tuple[DiscoveredItem, ...] = ()
    #: Fields not published or not parsed (SCP-08).
    field_gaps: Mapping[str, FieldState] = Field(default_factory=dict)
    #: Listing keys the offers may refer to without a listing draft in this output.
    existing_listing_keys: frozenset[SourceListingKey] = frozenset()

    @model_validator(mode="after")
    def _check_links(self) -> Self:
        keys = [listing.source_listing_key for listing in self.listings]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            msg = f"duplicate listing drafts for {duplicates}"
            raise ValueError(msg)
        known = set(keys) | self.existing_listing_keys
        orphans = sorted({o.source_listing_key for o in self.offers} - known)
        if orphans:
            msg = f"offers refer to listings not in this output or existing_listing_keys: {orphans}"
            raise ValueError(msg)
        return self


class ParseError(Exception):
    """The payload no longer matches the expected layout. The run records ``parse_failure``,
    never out of stock."""


@runtime_checkable
class Connector(Protocol):
    """One source's collection logic. Implementations import no network library (guarded)."""

    #: e.g. ``"ulta_ae"``, ``"sephora_me"``.
    source_key: ClassVar[str]
    #: Semver, recorded on the ``CollectionContext``.
    connector_version: ClassVar[str]

    def discover(self, ctx: CollectionContext) -> Iterator[DiscoveredItem]:
        """Yield items from rung-0 sources (robots, sitemaps, category trees)."""
        ...

    def requests_for(self, item: DiscoveredItem, ctx: CollectionContext) -> Sequence[FetchRequest]:
        """Map an item to one or more requests (e.g. page HTML plus its product JSON). No I/O."""
        ...

    def parse(self, result: FetchResult, ctx: CollectionContext) -> ParseOutput:
        """Parse an ``ok`` result: pure, deterministic, no I/O. Raise ``ParseError`` on drift."""
        ...
