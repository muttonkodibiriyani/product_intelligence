"""Tests for comparison contract models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pi_compare import Discount, ImageDescription, ImageDescriptionFile, ValueState
from pi_compare.models import (
    AttributeCell,
    AttributeReport,
    Axis,
    AxisEvidence,
    AxisValue,
    DiscountResult,
    EvidencePointer,
    ListingRef,
    ListingTokenState,
    MatrixState,
    NormalisationMethod,
    RetailerCell,
    VariantIdentityBasis,
    VariantRef,
)
from pi_dataset.models import MoneyValue
from pi_dataset.profiles import AttributeDef


def image_description(**changes: object) -> ImageDescription:
    values: dict[str, object] = {
        "retailer": "faces_ae",
        "listingKey": "faces_ae:item-1",
        "sourceUrl": "https://example.com/image.jpg",
        "sourceImageSha256": "a" * 64,
        "description": "Front-facing product packshot on a white background.",
        "locale": "en",
        "confidence": "0.93",
        "modelProvider": "provider",
        "modelName": "vision-model",
        "modelVersion": "2026-10-01",
        "promptVersion": "image-description/1",
        "generatedAt": datetime(2026, 10, 9, tzinfo=UTC),
        "runId": "run-1",
        "evidenceGeneration": "generation-1",
    }
    values.update(changes)
    return ImageDescription.model_validate(values)


def test_image_description_keeps_source_hash_and_model_provenance() -> None:
    row = image_description()
    assert row.source_image_sha256 == "a" * 64
    assert row.model_version == "2026-10-01"
    assert row.confidence == "0.93"
    assert ImageDescriptionFile(records=(row,)).schema_id == "pi.image-descriptions/v1"


def test_image_description_rejects_bad_hash_or_confidence() -> None:
    with pytest.raises(ValidationError):
        image_description(sourceImageSha256="not-a-hash")
    with pytest.raises(ValidationError):
        image_description(confidence="1.01")


def test_description_sidecar_rejects_duplicate_immutable_key() -> None:
    row = image_description()
    with pytest.raises(ValidationError, match="repeats an immutable generation key"):
        ImageDescriptionFile(records=(row, row))


def test_distinct_skus_remain_distinct_even_with_equal_axes() -> None:
    first = VariantRef(
        key="listing:sku-1",
        retailer_sku="sku-1",
        identity_basis=VariantIdentityBasis.OFFER_SKU,
        contexts=("faces_ae",),
    )
    second = VariantRef(
        key="listing:sku-2",
        retailer_sku="sku-2",
        identity_basis=VariantIdentityBasis.OFFER_SKU,
        contexts=("faces_ae",),
    )
    listing = ListingRef.model_validate(
        {
            "retailer": "faces_ae",
            "contexts": ["faces_ae"],
            "token": "item-1",
            "tokenState": ListingTokenState.KEYED,
            "sourceProductId": "item-1",
            "variants": (first, second),
            "commercial": [],
        }
    )
    assert [variant.retailer_sku for variant in listing.variants] == ["sku-1", "sku-2"]


def test_duplicate_variant_identity_is_rejected() -> None:
    variant = VariantRef(
        key="listing:sku-1",
        retailer_sku="sku-1",
        identity_basis=VariantIdentityBasis.OFFER_SKU,
        contexts=("faces_ae",),
    )
    with pytest.raises(ValidationError, match="duplicate variant keys"):
        ListingRef.model_validate(
            {
                "retailer": "faces_ae",
                "contexts": ["faces_ae"],
                "token": "item-1",
                "tokenState": ListingTokenState.KEYED,
                "sourceProductId": "item-1",
                "variants": (variant, variant),
                "commercial": [],
            }
        )


def test_axis_contract_rejects_incomplete_provenance_and_state() -> None:
    with pytest.raises(ValidationError, match="ruleVersion is required"):
        AxisEvidence(field="size", method=NormalisationMethod.TEXT_RULE)
    with pytest.raises(ValidationError, match="factor is set exactly"):
        AxisEvidence(field="size", method=NormalisationMethod.PAGE, factor="1")
    evidence = AxisEvidence(field="size", method=NormalisationMethod.PAGE)
    with pytest.raises(ValidationError, match="observed axis needs"):
        AxisValue(
            axis=Axis.SIZE,
            raw=None,
            canonical=None,
            canonical_unit=None,
            state=ValueState.OBSERVED,
            evidence=evidence,
            reason="missing",
        )
    with pytest.raises(ValidationError, match="needs a reason"):
        AxisValue(
            axis=Axis.SIZE,
            raw=None,
            canonical=None,
            canonical_unit=None,
            state=ValueState.UNKNOWN,
            evidence=evidence,
        )


def test_matrix_contract_rejects_tokens_that_disagree_with_state() -> None:
    values = {
        "retailer": "faces_ae",
        "state": MatrixState.ABSENT,
        "asOf": "2026-10-09",
        "generation": "g1",
        "listingTokens": ["item-1"],
        "completenessBasis": "complete",
    }
    with pytest.raises(ValidationError, match="present is set exactly"):
        RetailerCell.model_validate(values)
    values["listingTokens"] = []
    values["ambiguousTokens"] = ["item-2"]
    with pytest.raises(ValidationError, match="ambiguous is set exactly"):
        RetailerCell.model_validate(values)


def test_discount_and_evidence_contracts_reject_inconsistent_state() -> None:
    with pytest.raises(ValidationError, match=r"outside 0\.\.100"):
        Discount(amount=MoneyValue(amount="1.00", minor=100, currency="AED"), percent="101")
    with pytest.raises(ValidationError, match="only an observed discount"):
        DiscountResult(state=ValueState.OBSERVED, value=None, reason="missing")
    with pytest.raises(ValidationError, match="needs one reason"):
        DiscountResult(state=ValueState.UNKNOWN, value=None, reason=None)
    with pytest.raises(ValidationError, match="set together"):
        EvidencePointer(
            source="model",
            field="description",
            excerpt="matte",
            model_name="reader",
        )


def test_attribute_contract_rejects_inconsistent_counts_and_missing_cells() -> None:
    definition = AttributeDef.model_validate(
        {
            "key": "finish",
            "level": "product",
            "type": "text",
            "values": None,
            "label": {"en": "Finish"},
            "facet": False,
            "block": "summary",
            "capability": True,
        }
    )
    with pytest.raises(ValidationError, match="observed without"):
        AttributeCell(
            key="finish",
            definition=definition,
            state=ValueState.OBSERVED,
            raw=(),
            canonical=(),
            evidence=(),
        )
    evidence = EvidencePointer(source="page", field="name", excerpt="matte")
    with pytest.raises(ValidationError, match="missing state carries no values"):
        AttributeCell(
            key="finish",
            definition=definition,
            state=ValueState.UNKNOWN,
            raw=("matte",),
            canonical=(),
            evidence=(evidence,),
        )
    with pytest.raises(ValidationError, match="do not cover"):
        AttributeReport(cells=(), completeness="1", counts={ValueState.OBSERVED: 1})
    with pytest.raises(ValidationError, match=r"outside 0\.\.1"):
        AttributeReport(cells=(), completeness="2", counts={})
