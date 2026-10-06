"""Records in and out of the image signal. The pair row is the contract with ``pi_match``."""

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from pi_core.base import PiModel


class ImageRef(PiModel):
    """The primary (packshot) image of one retailer listing."""

    source: str = Field(min_length=1)  # e.g. "ulta_ae", "sephora_me", "faces_ae"
    source_key: str = Field(min_length=1)  # the listing's id in the published dataset
    brand_key: str | None = None
    image_url: str | None = None


class FetchStatus(StrEnum):
    """What fetching one image URL gave. Only ``ok`` has bytes in the cache."""

    OK = "ok"
    NOT_ALLOWED_HOST = "not_allowed_host"
    HTTP_ERROR = "http_error"
    BLOCKED = "blocked"  # a challenge or refusal: the host is stopped for the run
    NOT_IMAGE = "not_image"
    TOO_LARGE = "too_large"
    TRANSPORT_ERROR = "transport_error"
    NOT_FETCHED = "not_fetched"  # cache-only run, or the host was stopped earlier in the run


class ImageStatus(StrEnum):
    """Why a listing does, or does not, carry an image signal."""

    OK = "ok"
    MISSING_IMAGE = "missing_image"  # the listing publishes no image URL
    FETCH_FAILED = "fetch_failed"
    UNREADABLE = "unreadable"  # bytes that Pillow cannot decode
    PLACEHOLDER = "placeholder"  # blank, "coming soon", or one picture shared across brands


class ListingImage(PiModel):
    """Per-listing outcome: hashes when the image is usable, else the reason it is not."""

    source: str
    source_key: str
    brand_key: str | None
    image_url: str | None
    status: ImageStatus
    #: Why: the fetch status, or the placeholder rule that fired.
    detail: str | None = None
    phash: str | None = None  # 16 hex digits
    dhash: str | None = None
    #: SHA-256 of the image bytes: a changed image changes it (the matcher re-scores the pair).
    image_sha: str | None = None

    @model_validator(mode="after")
    def _hashes_only_when_hashed(self) -> Self:
        hashed = self.status in {ImageStatus.OK, ImageStatus.PLACEHOLDER}
        if self.status is ImageStatus.OK and None in (self.phash, self.dhash, self.image_sha):
            msg = "an ok image carries both hashes and its SHA-256"
            raise ValueError(msg)
        if not hashed and (self.phash is not None or self.dhash is not None):
            msg = f"a {self.status} image carries no hashes"
            raise ValueError(msg)
        return self


class Via(StrEnum):
    """Which generator proposed the pair."""

    PHASH = "phash"  # perceptual near-duplicate
    ANN = "ann"  # top-k by embedding cosine
    BOTH = "both"


class ImageSignal(PiModel):
    """One cross-retailer pair with its image evidence (``left_source < right_source``).

    Written to ``image_signals.jsonl`` when the brands agree (or one is unknown), and to
    ``alias_suggestions.jsonl`` when both brand keys are known and differ: those are for human
    brand-alias review only, never match candidates (the brand rule is hard).

    Supporting evidence and a candidate source only: it never overrides a hard rule. The same
    packshot is reused across sizes, EDP vs EDT, minis and refills, so equal images say "same
    product line", never "same item".
    """

    left_source: str
    left_key: str
    right_source: str
    right_key: str
    left_brand: str | None = None
    right_brand: str | None = None
    phash_distance: int = Field(ge=0, le=64)
    dhash_distance: int = Field(ge=0, le=64)
    #: Embedding cosine, 4 dp; None when the run had no embedder.
    cosine: Decimal | None
    #: Best rank of either side within the other's top-k by cosine; None when only pHash found it.
    rank: int | None = Field(default=None, ge=1)
    via: Via
    left_image_sha: str
    right_image_sha: str

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.left_source >= self.right_source:
            msg = "left_source must sort before right_source (a cross-retailer pair)"
            raise ValueError(msg)
        return self
