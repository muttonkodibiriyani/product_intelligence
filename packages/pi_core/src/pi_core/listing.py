"""Listing records: what a connector's ``parse`` returns for each source SKU (blueprint 6.2).

A listing is variant-level: one record per source SKU, so variant walking yields one record per
shade/size. Matching to canonical variants happens later and never edits these records.

| Field | Blueprint 5.1 | Requirements |
|---|---|---|
| ``source_id``, ``source_listing_key`` (natural key) | ``source_listing`` | CAT-01, DAT-09 |
| ``source_sku``, ``gtin``, ``mpn`` | ``source_listing.source_sku``, ``variant.gtin/mpn`` | CAT-02 |
| ``name_original``, ``name_ar``, ``lang`` | ``source_listing`` | CAT-06, SCP-06 |
| ``brand`` | ``brand.name`` (raw, unresolved) | CAT-01 |
| ``shade(_code)``, ``size_value/unit``, ``pack_count``, ``concentration`` | ``variant`` | CAT-03 |
| ``category_path_source`` | ``source_listing.category_path_source`` | CAT-07 |
| ``images`` | ``listing_image`` | SRC-13 |
| ``attributes`` | ``variant.attributes`` | CAT-05 |
| ``field_state`` | null reasons | DQ-02 |
| ``evidence_id``, ``observed_at`` | ``evidence``, ``first_seen_at/last_seen_at`` | DAT-04 |
"""

from typing import Annotated, ClassVar, Self

from pydantic import AfterValidator, Field, HttpUrl, model_validator

from pi_core.base import FieldStateModel, PiModel
from pi_core.enums import Concentration, ImageRole
from pi_core.types import DbId, LocaleTag, NonEmptyStr, Size, UtcDatetime

GTIN_LENGTHS = frozenset({8, 12, 13, 14})


def gtin_check_digit(body: str) -> str:
    """GS1 mod-10 check digit for the digits of a GTIN without its last digit."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def is_valid_gtin(code: str) -> bool:
    """True for a GTIN-8/12/13/14 whose check digit is correct."""
    if not code.isascii() or not code.isdigit() or len(code) not in GTIN_LENGTHS:
        return False
    return gtin_check_digit(code[:-1]) == code[-1]


def gtin14(code: str) -> str:
    """Zero-pad a valid GTIN to 14 digits, the form identity comparisons use."""
    if not is_valid_gtin(code):
        msg = f"invalid GTIN {code!r}"
        raise ValueError(msg)
    return code.zfill(14)


def _check_gtin(value: str) -> str:
    if not is_valid_gtin(value):
        msg = f"invalid GTIN {value!r}"
        raise ValueError(msg)
    return value


#: A GTIN as published (original length kept); must pass the GS1 check digit.
Gtin = Annotated[str, AfterValidator(_check_gtin)]


class ImageRef(PiModel):
    """An image URL as published on the listing; bytes are fetched and deduped separately."""

    source_url: HttpUrl
    role: ImageRole
    position: int = Field(ge=0)


class ListingFields(FieldStateModel):
    """Shared validated listing fields before persistence IDs are assigned."""

    TRACKED_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "source_sku",
            "brand",
            "name_ar",
            "gtin",
            "mpn",
            "shade",
            "shade_code",
            "size_value",
            "pack_count",
            "concentration",
            "category_path_source",
            "images",
        }
    )

    source_listing_key: NonEmptyStr
    source_sku: NonEmptyStr | None
    url: HttpUrl
    lang: LocaleTag
    name_original: NonEmptyStr
    name_ar: NonEmptyStr | None
    brand: NonEmptyStr | None
    gtin: Gtin | None
    mpn: NonEmptyStr | None
    shade: NonEmptyStr | None
    shade_code: NonEmptyStr | None
    size_value: Size | None
    size_unit: NonEmptyStr | None = None
    pack_count: Annotated[int, Field(ge=1)] | None
    concentration: Concentration | None
    category_path_source: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)] | None
    images: Annotated[tuple[ImageRef, ...], Field(min_length=1)] | None
    attributes: dict[str, str] = Field(default_factory=dict)
    observed_at: UtcDatetime

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if (self.size_value is None) != (self.size_unit is None):
            msg = "size_value and size_unit must be given together"
            raise ValueError(msg)
        if self.images is not None:
            positions = [(img.role, img.position) for img in self.images]
            if len(positions) != len(set(positions)):
                msg = "duplicate image (role, position)"
                raise ValueError(msg)
        return self


class ListingRecord(ListingFields):
    """One persisted source SKU parsed from one piece of evidence."""

    source_id: DbId
    evidence_id: DbId

    @property
    def natural_key(self) -> tuple[int, str]:
        """``UNIQUE (source_id, source_listing_key)``: independent of locale, market and time."""
        return (self.source_id, self.source_listing_key)
