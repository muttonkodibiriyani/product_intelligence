"""The 154-slot contract and its fail-closed projection semantics."""

from __future__ import annotations

import pytest

from pi_api.attributes import (
    AttributeFact,
    AttributeFieldEvidence,
    AttributeKind,
    AttributeProjectionError,
    AttributeState,
    AttributeTarget,
    AttributeTargetLevel,
    UnknownAttributeError,
    attribute_manifest,
    project_target,
)


def test_manifest_is_the_reviewed_154_unique_definitions() -> None:
    definitions = attribute_manifest()
    keys = [definition.key for definition in definitions]
    assert len(definitions) == 154
    assert len(keys) == len(set(keys))
    assert keys[0] == "style_id"
    assert keys[-1] == "variant_relationships"


def test_manifest_keeps_types_levels_currency_and_bilingual_profile_labels() -> None:
    definitions = {definition.key: definition for definition in attribute_manifest()}
    assert definitions["price_minor"].kind is AttributeKind.MONEY
    assert definitions["price_minor"].currency_from == "offer.currency"
    assert definitions["price_minor"].level is AttributeTargetLevel.OFFER
    assert definitions["gtin"].level is AttributeTargetLevel.VARIANT
    assert definitions["skinTypes"].kind is AttributeKind.LIST
    assert definitions["skinTypes"].label.ar == "أنواع البشرة"


def test_required_states_remain_distinct_and_not_applicable_is_explicit() -> None:
    required = {
        "observed",
        "not_published",
        "not_observed",
        "unknown",
        "conflict",
        "invalid",
    }
    assert required < {state.value for state in AttributeState}
    assert AttributeState.NOT_APPLICABLE.value == "not_applicable"


def evidence(field: str) -> tuple[AttributeFieldEvidence, ...]:
    return (AttributeFieldEvidence(source="page", field=field, excerpt="fixture"),)


def test_projection_keeps_every_state_without_substitution() -> None:
    target = AttributeTarget(id="shop_a:offer", level="offer", label="Shop A", retailer="shop_a")
    facts = (
        AttributeFact(
            key="price_minor",
            raw={"amount": "12.00", "minor": 1200, "currency": "AED"},
            evidence=evidence("series.price[-1]"),
        ),
        AttributeFact(key="returnable", raw=True, evidence=evidence("isReturnable")),
        AttributeFact(key="returnable", raw=False, evidence=evidence("returns.disabled")),
        AttributeFact(
            key="shipping_fee_minor", raw="free", evidence=evidence("shippingFee")
        ),
    )
    slots = {
        slot.definition.key: slot
        for slot in project_target(
            target,
            facts,
            missing={
                "coupon_available": AttributeState.NOT_PUBLISHED,
                "page_url": AttributeState.NOT_OBSERVED,
            },
        )
    }

    assert len(slots) == 154
    assert slots["price_minor"].state is AttributeState.OBSERVED
    assert slots["price_minor"].value is not None
    assert slots["returnable"].state is AttributeState.CONFLICT
    assert len(slots["returnable"].alternatives) == 2
    assert slots["shipping_fee_minor"].state is AttributeState.INVALID
    assert slots["shipping_fee_minor"].raw_value == '"free"'
    assert slots["coupon_available"].state is AttributeState.NOT_PUBLISHED
    assert slots["page_url"].state is AttributeState.NOT_OBSERVED
    assert slots["listing_id"].state is AttributeState.UNKNOWN
    assert slots["brand"].state is AttributeState.NOT_APPLICABLE


def test_projection_rejects_unknown_wrong_level_and_evidence_free_facts() -> None:
    target = AttributeTarget(id="offer", level="offer", label="Offer")
    with pytest.raises(UnknownAttributeError):
        project_target(
            target,
            (AttributeFact(key="invented", raw="x", evidence=evidence("invented")),),
        )
    with pytest.raises(AttributeProjectionError, match="belongs to"):
        project_target(
            target,
            (AttributeFact(key="brand", raw="X", evidence=evidence("brand")),),
        )
    with pytest.raises(AttributeProjectionError, match="no field evidence"):
        project_target(target, (AttributeFact(key="returnable", raw=True, evidence=()),))
