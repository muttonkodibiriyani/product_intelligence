"""The 154-slot contract and its fail-closed projection semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from api_fixture import bearer, make_client, own_keys, served_dataset, write
from pi_api.attributes import (
    AttributeFact,
    AttributeFieldEvidence,
    AttributeKind,
    AttributeProjectionError,
    AttributeQuery,
    AttributeState,
    AttributeTarget,
    AttributeTargetLevel,
    UnknownAttributeError,
    attribute_manifest,
    attribute_page,
    coverage_rows,
    product_attribute_slots,
    project_target,
)
from pi_api.catalog import InvalidQueryError, StaleCursorError
from pi_dataset import AttributeEvidence, AttributeSource, ContentField, OfferContent, OfferVariant


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
    target = AttributeTarget(
        id="shop_a:offer",
        level=AttributeTargetLevel.OFFER,
        label="Shop A",
        retailer="shop_a",
    )
    facts = (
        AttributeFact(
            key="price_minor",
            raw={"amount": "12.00", "minor": 1200, "currency": "AED"},
            evidence=evidence("series.price[-1]"),
        ),
        AttributeFact(key="returnable", raw=True, evidence=evidence("isReturnable")),
        AttributeFact(key="returnable", raw=False, evidence=evidence("returns.disabled")),
        AttributeFact(key="shipping_fee_minor", raw="free", evidence=evidence("shippingFee")),
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
    target = AttributeTarget(id="offer", level=AttributeTargetLevel.OFFER, label="Offer")
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


def test_saved_product_projects_exactly_154_slots_for_every_entity() -> None:
    dataset = own_keys(served_dataset())
    product = next(item for item in dataset.products if item.id == "p01")
    projected = product_attribute_slots(dataset, product)
    by_target = {target.id: slots for target, slots in projected}

    assert by_target
    assert all(len(slots) == 154 for slots in by_target.values())
    assert (
        next(slot for slot in by_target["p01:master"] if slot.definition.key == "brand").state
        is AttributeState.OBSERVED
    )
    offer = by_target["p01:offer:shop_a"]
    price = next(slot for slot in offer if slot.definition.key == "price_minor")
    assert price.state is AttributeState.OBSERVED
    assert price.evidence[0].context == "shop_a"
    assert all(row["slots"] == 154 for row in coverage_rows(dataset))
    assert coverage_rows(dataset) == coverage_rows(dataset)


def test_variant_shade_does_not_cross_the_product_level_contract() -> None:
    dataset = own_keys(served_dataset())
    product = next(item for item in dataset.products if item.id == "p01")
    offer = product.offers["shop_a"].model_copy(
        update={
            "content": OfferContent(
                captured=(ContentField.SHADE,),
                variants=(OfferVariant(sku="shop-a-ruby", shade="Ruby", gtin=None),),
            )
        }
    )
    product = product.model_copy(
        update={
            "offers": {**product.offers, "shop_a": offer},
            "attributes": {**product.attributes, "shade_name": "Catalog Ruby"},
            "attribute_evidence": {
                **product.attribute_evidence,
                "shade_name": AttributeEvidence(
                    source=AttributeSource.PAGE,
                    field="attributes.shadeName",
                    excerpt="Catalog Ruby",
                    rule=None,
                ),
            },
        }
    )
    dataset = dataset.model_copy(
        update={
            "products": tuple(
                product if item.id == product.id else item for item in dataset.products
            )
        }
    )

    by_target = {
        target.id: {slot.definition.key: slot for slot in slots}
        for target, slots in product_attribute_slots(dataset, product)
    }

    product_shade = by_target["p01:product"]["shade_name"]
    variant_shade = by_target["p01:variant:shop_a:0"]["shade_name"]
    assert product_shade.state is AttributeState.OBSERVED
    assert product_shade.value is not None
    assert product_shade.value.kind == "text"
    assert product_shade.value.text == "Catalog Ruby"
    assert variant_shade.state is AttributeState.NOT_APPLICABLE
    assert by_target["p01:variant:shop_a:0"]["retailer_sku"].state is AttributeState.OBSERVED


def test_saved_value_without_field_evidence_is_withheld_as_unknown() -> None:
    dataset = own_keys(served_dataset())
    product = next(item for item in dataset.products if item.id == "p01").model_copy(
        update={"attributes": {"concentration": "edp"}}
    )
    dataset = dataset.model_copy(
        update={
            "products": tuple(
                product if item.id == product.id else item for item in dataset.products
            )
        }
    )

    by_target = {
        target.id: {slot.definition.key: slot for slot in slots}
        for target, slots in product_attribute_slots(dataset, product)
    }

    concentration = by_target["p01:master"]["concentration"]
    assert concentration.state is AttributeState.UNKNOWN
    assert concentration.value is None
    assert concentration.evidence == ()
    assert concentration.raw_value is None


def test_attribute_page_is_bounded_filter_bound_and_generation_bound() -> None:
    dataset = own_keys(served_dataset())
    product = next(item for item in dataset.products if item.id == "p01")
    query = AttributeQuery(target="p01:offer:shop_a", limit=10)
    first = attribute_page(dataset, product, "generation-1", query).data
    assert first is not None
    assert len(first.items) == 10
    assert first.slot_total == 154
    assert first.definition_count == 154
    assert first.next_cursor is not None

    second = attribute_page(
        dataset,
        product,
        "generation-1",
        query.model_copy(update={"cursor": first.next_cursor}),
    ).data
    assert second is not None
    assert {item.definition.key for item in first.items}.isdisjoint(
        item.definition.key for item in second.items
    )
    with pytest.raises(StaleCursorError):
        attribute_page(
            dataset,
            product,
            "generation-2",
            query.model_copy(update={"cursor": first.next_cursor}),
        )
    with pytest.raises(InvalidQueryError, match="different filters"):
        attribute_page(
            dataset,
            product,
            "generation-1",
            query.model_copy(
                update={"cursor": first.next_cursor, "state": AttributeState.OBSERVED}
            ),
        )


def test_authenticated_attribute_route_is_additive_and_paged(tmp_path: Path) -> None:
    dataset = own_keys(served_dataset())
    write(tmp_path, dataset)
    client, _ = make_client(tmp_path)
    response = client.get(
        "/api/v1/products/p01/attributes?target=p01%3Aoffer%3Ashop_a&limit=10",
        headers=bearer(),
    )
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["meta"]["apiVersion"] == "1.26.0"
    assert document["data"]["definitionCount"] == 154
    assert len(document["data"]["items"]) == 10
    assert document["data"]["nextCursor"] is not None
    assert client.get("/api/v1/products/p01/attributes").status_code == 401
