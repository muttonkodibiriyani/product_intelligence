"""Wire-safe comparison records.

These are additive projections over ``pi.dataset/v3`` and ``pi.matches/v1``. They never replace
source product, offer, variant, image or evidence records.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, HttpUrl, JsonValue, StringConstraints, model_validator

from pi_core.enums import AvailabilityState, MatchClass, ReviewState
from pi_core.types import NonEmptyStr, UtcDatetime
from pi_dataset.models import ContractModel, DecimalText, MoneyValue
from pi_dataset.profiles import AttributeDef, AttributeKey

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Confidence = Annotated[str, StringConstraints(pattern=r"^0(\.\d+)?$|^1(\.0+)?$")]


class ValueState(StrEnum):
    """Why a comparison value is present or missing."""

    OBSERVED = "observed"
    UNKNOWN = "unknown"
    NOT_OBSERVED = "not_observed"
    CONFLICT = "conflict"
    INVALID = "invalid"


class MatrixState(StrEnum):
    """A retailer's state in a canonical family; deliberately not boolean."""

    PRESENT = "present"
    ABSENT = "absent"
    NOT_OBSERVED = "not_observed"
    AMBIGUOUS = "ambiguous"


class CaptureCompleteness(ContractModel):
    """The caller's explicit basis for permitting (or refusing) an absence claim."""

    complete: bool
    basis: NonEmptyStr


class Axis(StrEnum):
    SIZE = "size"
    VOLUME = "volume"
    PACK = "pack"
    SHADE = "shade"
    COLOR = "color"


class NormalisationMethod(StrEnum):
    PAGE = "page"
    DECLARED_UNIT = "declared_unit"
    DETERMINISTIC_CONVERSION = "deterministic_conversion"
    TEXT_RULE = "text_rule"
    NONE = "none"


class AxisEvidence(ContractModel):
    field: NonEmptyStr
    method: NormalisationMethod
    rule_version: NonEmptyStr | None = None
    factor: DecimalText | None = None

    @model_validator(mode="after")
    def _check_rule(self) -> Self:
        ruled = self.method in {
            NormalisationMethod.DETERMINISTIC_CONVERSION,
            NormalisationMethod.TEXT_RULE,
        }
        if ruled != (self.rule_version is not None):
            msg = "ruleVersion is required exactly for converted or text-rule values"
            raise ValueError(msg)
        if (self.factor is not None) != (
            self.method is NormalisationMethod.DETERMINISTIC_CONVERSION
        ):
            msg = "factor is set exactly for a deterministic conversion"
            raise ValueError(msg)
        return self


class AxisValue(ContractModel):
    axis: Axis
    raw: JsonValue
    canonical: str | tuple[str, ...] | None
    canonical_unit: NonEmptyStr | None
    state: ValueState
    evidence: AxisEvidence
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check_state(self) -> Self:
        if self.state is ValueState.OBSERVED and self.canonical is None:
            msg = "an observed axis needs a canonical value"
            raise ValueError(msg)
        if self.canonical is None and self.reason is None:
            msg = "an axis without a canonical value needs a reason"
            raise ValueError(msg)
        return self


class MatchEvidence(ContractModel):
    left_listing_key: NonEmptyStr
    right_listing_key: NonEmptyStr
    match_class: MatchClass
    review_state: ReviewState
    confidence: Confidence | None
    method: NonEmptyStr
    reasons: tuple[NonEmptyStr, ...]
    left_fingerprint: NonEmptyStr | None
    right_fingerprint: NonEmptyStr | None


class VariantIdentityBasis(StrEnum):
    CONTENT_VARIANT = "content_variant"
    OFFER_SKU = "offer_sku"
    LISTING_TOKEN = "listing_token"  # noqa: S105 - identity basis, not a credential


class ListingTokenState(StrEnum):
    KEYED = "keyed"
    UNKEYED = "unkeyed"


class LaunchBasis(StrEnum):
    FIRST_OBSERVED = "first_observed"
    RETAILER_BADGE = "retailer_badge"


class LaunchEvidence(ContractModel):
    state: ValueState
    observed_on: date | None
    basis: LaunchBasis | None

    @model_validator(mode="after")
    def _check_observed(self) -> Self:
        present = self.observed_on is not None and self.basis is not None
        if (self.state is ValueState.OBSERVED) != present:
            msg = "an observed launch needs both date and basis"
            raise ValueError(msg)
        return self


class CommercialSnapshot(ContractModel):
    context: NonEmptyStr
    current: MoneyValue | None
    regular: MoneyValue | None
    discount: DiscountResult
    availability: AvailabilityState | None
    availability_state: ValueState
    launch: LaunchEvidence
    captured_at: UtcDatetime
    not_observed_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check_availability(self) -> Self:
        if self.availability_state is ValueState.OBSERVED and self.availability is None:
            msg = "observed availability needs a value"
            raise ValueError(msg)
        if self.availability_state is ValueState.NOT_OBSERVED and self.not_observed_reason is None:
            msg = "not-observed availability needs its source reason"
            raise ValueError(msg)
        return self


class VariantRef(ContractModel):
    """One retailer SKU. Equal axes never collapse two instances of this record."""

    key: NonEmptyStr
    retailer_sku: NonEmptyStr
    identity_basis: VariantIdentityBasis
    contexts: tuple[NonEmptyStr, ...]
    gtins: tuple[NonEmptyStr, ...] = ()
    axes: tuple[AxisValue, ...] = ()


class ListingRef(ContractModel):
    retailer: NonEmptyStr
    contexts: tuple[NonEmptyStr, ...]
    token: NonEmptyStr
    token_state: ListingTokenState
    source_product_id: NonEmptyStr
    variants: tuple[VariantRef, ...]
    commercial: tuple[CommercialSnapshot, ...]

    @model_validator(mode="after")
    def _distinct_skus(self) -> Self:
        keys = [v.key for v in self.variants]
        if len(keys) != len(set(keys)):
            msg = f"listing {self.token}: duplicate variant keys"
            raise ValueError(msg)
        return self


class RetailerCell(ContractModel):
    retailer: NonEmptyStr
    state: MatrixState
    as_of: date
    generation: NonEmptyStr
    listing_tokens: tuple[NonEmptyStr, ...] = ()
    ambiguous_tokens: tuple[NonEmptyStr, ...] = ()
    completeness_basis: NonEmptyStr

    @model_validator(mode="after")
    def _check_members(self) -> Self:
        if (self.state is MatrixState.PRESENT) != bool(self.listing_tokens):
            msg = "present is set exactly when accepted listing tokens exist"
            raise ValueError(msg)
        if (self.state is MatrixState.AMBIGUOUS) != bool(self.ambiguous_tokens):
            msg = "ambiguous is set exactly when ambiguous listing tokens exist"
            raise ValueError(msg)
        return self


class RetailerFamilyEvidence(ContractModel):
    retailer: NonEmptyStr
    retailer_family_id: NonEmptyStr
    listing_keys: tuple[NonEmptyStr, ...]


class ProductFamily(ContractModel):
    id: NonEmptyStr
    brand_key: NonEmptyStr
    name: NonEmptyStr
    category: tuple[NonEmptyStr, ...]
    listings: tuple[ListingRef, ...]
    matrix: tuple[RetailerCell, ...]
    evidence: tuple[MatchEvidence, ...]
    suggestions: tuple[MatchEvidence, ...] = ()
    exclusions: tuple[MatchEvidence, ...] = ()
    retailer_family_evidence: tuple[RetailerFamilyEvidence, ...] = ()


class Discount(ContractModel):
    amount: MoneyValue
    percent: DecimalText

    @model_validator(mode="after")
    def _check_percent(self) -> Self:
        if not Decimal(0) <= Decimal(self.percent) <= Decimal(100):
            msg = "discount percent is outside 0..100"
            raise ValueError(msg)
        return self


class DiscountResult(ContractModel):
    state: ValueState
    value: Discount | None
    reason: NonEmptyStr | None

    @model_validator(mode="after")
    def _check_value(self) -> Self:
        if (self.state is ValueState.OBSERVED) != (self.value is not None):
            msg = "only an observed discount has a value"
            raise ValueError(msg)
        if (self.value is None) != (self.reason is not None):
            msg = "a missing discount needs one reason"
            raise ValueError(msg)
        return self


CommercialSnapshot.model_rebuild()


class EvidencePointer(ContractModel):
    source: NonEmptyStr
    field: NonEmptyStr
    excerpt: NonEmptyStr
    rule: NonEmptyStr | None = None
    source_hash: Sha256 | None = None
    model_name: NonEmptyStr | None = None
    model_version: NonEmptyStr | None = None
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def _check_model(self) -> Self:
        model_values = (self.model_name, self.model_version, self.confidence)
        if any(v is not None for v in model_values) and not all(
            v is not None for v in model_values
        ):
            msg = "model name, version and confidence are set together"
            raise ValueError(msg)
        return self


class AttributeSpec(ContractModel):
    definition: AttributeDef
    allowed_units: tuple[NonEmptyStr, ...] = ()
    allowed_currencies: tuple[NonEmptyStr, ...] = ()


class AttributeObservation(ContractModel):
    raw: JsonValue
    evidence: EvidencePointer


class AttributeCell(ContractModel):
    key: AttributeKey
    definition: AttributeDef
    state: ValueState
    raw: tuple[JsonValue, ...]
    canonical: tuple[JsonValue, ...]
    evidence: tuple[EvidencePointer, ...]
    errors: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _check_observed(self) -> Self:
        if self.state is ValueState.OBSERVED and not self.canonical:
            msg = f"attribute {self.key}: observed without a canonical value"
            raise ValueError(msg)
        if self.state in {ValueState.UNKNOWN, ValueState.NOT_OBSERVED} and (
            self.raw or self.canonical or self.evidence
        ):
            msg = f"attribute {self.key}: missing state carries no values"
            raise ValueError(msg)
        return self


class AttributeIssue(ContractModel):
    key: NonEmptyStr
    code: NonEmptyStr


class AttributeReport(ContractModel):
    cells: tuple[AttributeCell, ...]
    completeness: DecimalText
    counts: dict[ValueState, int]
    issues: tuple[AttributeIssue, ...] = ()

    @model_validator(mode="after")
    def _check_counts(self) -> Self:
        if sum(self.counts.values()) != len(self.cells):
            msg = "attribute counts do not cover every cell"
            raise ValueError(msg)
        if not Decimal(0) <= Decimal(self.completeness) <= Decimal(1):
            msg = "attribute completeness is outside 0..1"
            raise ValueError(msg)
        return self


class ImageDescription(ContractModel):
    """Append-only generated text keyed to immutable source image bytes."""

    retailer: NonEmptyStr
    listing_key: NonEmptyStr
    source_url: HttpUrl
    source_image_sha256: Sha256
    description: NonEmptyStr
    locale: NonEmptyStr
    confidence: Confidence
    model_provider: NonEmptyStr
    model_name: NonEmptyStr
    model_version: NonEmptyStr
    prompt_version: NonEmptyStr
    generated_at: UtcDatetime
    run_id: NonEmptyStr
    evidence_generation: NonEmptyStr


class ImageDescriptionFile(ContractModel):
    schema_id: Literal["pi.image-descriptions/v1"] = Field(
        default="pi.image-descriptions/v1", alias="schema"
    )
    records: tuple[ImageDescription, ...]

    @model_validator(mode="after")
    def _append_only_key(self) -> Self:
        keys = [
            (
                r.retailer,
                r.listing_key,
                r.source_image_sha256,
                r.model_provider,
                r.model_name,
                r.model_version,
                r.prompt_version,
                r.locale,
            )
            for r in self.records
        ]
        if len(keys) != len(set(keys)):
            msg = "image description file repeats an immutable generation key"
            raise ValueError(msg)
        return self


class ProjectionIssue(ContractModel):
    code: NonEmptyStr
    listing_keys: tuple[NonEmptyStr, ...] = ()
    detail: NonEmptyStr


class ComparisonProjection(ContractModel):
    schema_id: Literal["pi.comparison/v1"] = Field(default="pi.comparison/v1", alias="schema")
    generation: NonEmptyStr
    as_of: date
    families: tuple[ProductFamily, ...]
    issues: tuple[ProjectionIssue, ...] = ()
    unkeyed_listings: int = 0
