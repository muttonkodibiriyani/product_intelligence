import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import HttpUrl, ValidationError

from pi_connector_ulta._pi_fetch_stub import (
    FetchRequest,
    FetchResult,
    ListingDraft,
    OfferDraft,
    PayloadKind,
    to_canonical,
)
from pi_connector_ulta.mapping import map_product
from pi_connector_ulta.models import ProductRecord
from pi_core import (
    AvailabilityState,
    CollectionContext,
    FetchMethod,
    FieldState,
    LadderRung,
    ListingRecord,
    Locale,
    Market,
    OfferObservation,
    PriceType,
    SourceContext,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 30, 6, tzinfo=UTC)
CONTEXT = CollectionContext(
    source_context=SourceContext(
        id=1,
        source_id=2,
        country=Market.UAE,
        locale=Locale.EN,
        currency="AED",
        time_zone=Market.UAE.time_zone,
        valid_from=NOW - timedelta(days=1),
    ),
    crawl_run_id=3,
    connector_version="ulta_ae@0.1.0",
    ladder_rung_used=LadderRung.PLAIN_HTTP,
    fetch_method=FetchMethod.PLAIN_HTTP,
)


def _payload() -> dict[str, Any]:
    value: dict[str, Any] = json.loads((FIXTURES / "product_SYNTHETIC.json").read_text())
    return value


def _product(payload: dict[str, Any] | None = None) -> ProductRecord:
    return ProductRecord.model_validate(payload or _payload(), strict=False)


def _result(
    *, rung: LadderRung = LadderRung.PLAIN_HTTP, method: FetchMethod = FetchMethod.PLAIN_HTTP
) -> FetchResult:
    request = FetchRequest(
        url=HttpUrl("https://www.ulta.ae/en/product/glow-balm/P100"),
        kind=PayloadKind.JSON,
        locale=Locale.EN,
    )
    return FetchResult(
        request=request,
        final_url=request.url,
        http_status=200,
        content_type="application/json",
        body=b"{}",
        headers={},
        ladder_rung_used=rung,
        fetch_method=method,
        egress="fixture",
        retrieved_at=NOW,
        elapsed_ms=1,
        from_cache=False,
        block=None,
        evidence_uri="fixture://synthetic",
    )


def test_draft_fields_are_canonical_fields_minus_persistence_ids() -> None:
    assert set(ListingDraft.model_fields) == set(ListingRecord.model_fields) - {
        "source_id",
        "evidence_id",
    }
    assert set(OfferDraft.model_fields) - {"source_listing_key"} == set(
        OfferObservation.model_fields
    ) - {"source_listing_id", "evidence_id", "ingested_at"}


def test_mapping_is_replay_deterministic_and_uses_stable_variant_keys() -> None:
    first = map_product(_product(), _result(), CONTEXT)
    second = map_product(_product(), _result(), CONTEXT)
    assert first == second
    assert [listing.source_listing_key for listing in first.listings] == [
        "V100-ROSE",
        "V100-CLEAR",
    ]
    assert [offer.source_listing_key for offer in first.offers] == [
        "V100-ROSE",
        "V100-CLEAR",
    ]


def test_to_canonical_performs_full_validated_construction() -> None:
    output = map_product(_product(), _result(), CONTEXT)
    listing = to_canonical(output.listings[0], source_id=2, evidence_id=7)
    offer = to_canonical(
        output.offers[0],
        source_listing_id=5,
        evidence_id=7,
        ingested_at=NOW,
        context=CONTEXT,
    )
    assert isinstance(listing, ListingRecord)
    assert listing.source_id == 2
    assert isinstance(offer, OfferObservation)
    assert offer.source_listing_id == 5
    with pytest.raises(ValueError, match="requires source_id"):
        to_canonical(output.listings[0], evidence_id=7)  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="requires source_listing_id"):
        to_canonical(output.offers[0], evidence_id=7)  # type: ignore[call-overload]


def test_out_of_stock_maps_only_with_observed_availability() -> None:
    payload = _payload()
    payload["variants"][0]["stock"] = {
        "state": "out_of_stock",
        "quantity": 0,
        "source_field_observed": True,
    }
    offer = map_product(_product(payload), _result(), CONTEXT).offers[0]
    assert offer.availability_state is AvailabilityState.OUT_OF_STOCK
    assert offer.field_state["availability_state"] is FieldState.OBSERVED


@pytest.mark.parametrize("price_type", [PriceType.RANGE, PriceType.QUOTE_ONLY])
def test_non_single_prices_have_null_current_with_reason(price_type: PriceType) -> None:
    payload = _payload()
    prices = payload["variants"][0]["prices"]
    prices["price_type"] = price_type.value
    prices["current"] = {
        "amount": None,
        "currency": "AED",
        "field_state": "not_applicable",
        "reason": price_type.value,
    }
    if price_type is PriceType.RANGE:
        prices["range_min"] = {"amount": "80", "currency": "AED"}
        prices["range_max"] = {"amount": "120", "currency": "AED"}
    offer = map_product(_product(payload), _result(), CONTEXT).offers[0]
    assert offer.price_current is None
    assert offer.field_state["price_current"] is FieldState.NOT_APPLICABLE
    if price_type is PriceType.RANGE:
        assert offer.price_range_min == 80
        assert offer.price_range_max == 120


def test_zero_price_is_rejected_before_mapping() -> None:
    payload = _payload()
    payload["variants"][0]["prices"]["current"]["amount"] = "0"
    with pytest.raises(ValidationError, match="greater than 0"):
        _product(payload)


def test_missing_price_states_are_never_guessed_from_free_text() -> None:
    baseline = map_product(_product(), _result(), CONTEXT)
    assert baseline.offers[0].field_state["price_member"] is FieldState.NOT_PUBLISHED
    assert baseline.offers[1].field_state["price_promo"] is FieldState.NOT_APPLICABLE

    payload = _payload()
    payload["variants"][1]["prices"]["promo"] = {
        "amount": None,
        "currency": "AED",
        "field_state": "parse_failure",
        "reason": "could not parse price",
    }
    output = map_product(_product(payload), _result(), CONTEXT)
    assert output.offers[1].field_state["price_promo"] is FieldState.PARSE_FAILURE


def test_unknown_stock_does_not_assert_low_stock_or_available_variant_count() -> None:
    offer = map_product(_product(), _result(), CONTEXT).offers[0]
    assert offer.low_stock_flag is None
    assert offer.field_state["low_stock_flag"] is FieldState.NOT_PUBLISHED
    assert offer.available_variants is None
    assert offer.field_state["available_variants"] is FieldState.UNKNOWN


def test_available_variant_count_uses_only_observed_in_stock_variants() -> None:
    payload = _payload()
    payload["variants"][1]["stock"] = {
        "state": "out_of_stock",
        "quantity": 0,
        "source_field_observed": True,
    }
    offers = map_product(_product(payload), _result(), CONTEXT).offers
    assert all(offer.available_variants == 1 for offer in offers)


def test_all_unknown_variants_never_emit_a_false_zero_count() -> None:
    payload = _payload()
    for variant in payload["variants"]:
        variant["stock"] = {"state": "unknown", "reason": "not published"}
    offers = map_product(_product(payload), _result(), CONTEXT).offers
    assert all(offer.available_variants is None for offer in offers)
    assert all(offer.field_state["available_variants"] is FieldState.UNKNOWN for offer in offers)


def test_absent_shade_and_concentration_are_not_assumed_inapplicable() -> None:
    payload = _payload()
    payload["variants"][1]["shade"] = None
    output = map_product(_product(payload), _result(), CONTEXT)
    assert output.listings[0].field_state["concentration"] is FieldState.NOT_PUBLISHED
    assert output.listings[1].field_state["shade"] is FieldState.NOT_PUBLISHED


def test_to_canonical_checks_context_currency() -> None:
    output = map_product(_product(), _result(), CONTEXT)
    ksa = CollectionContext(
        source_context=SourceContext(
            id=1,
            source_id=2,
            country=Market.KSA,
            locale=Locale.EN,
            currency="SAR",
            time_zone=Market.KSA.time_zone,
            valid_from=NOW - timedelta(days=1),
        ),
        crawl_run_id=3,
        connector_version="ulta_ae@0.1.0",
        ladder_rung_used=LadderRung.PLAIN_HTTP,
        fetch_method=FetchMethod.PLAIN_HTTP,
    )
    with pytest.raises(ValueError, match="differs from context SAR"):
        to_canonical(
            output.offers[0],
            source_listing_id=5,
            evidence_id=7,
            ingested_at=NOW,
            context=ksa,
        )


def test_fetch_evidence_requires_a_permitted_matching_method() -> None:
    with pytest.raises(ValidationError, match="belongs to rung"):
        _result(rung=LadderRung.BROWSER, method=FetchMethod.PLAIN_HTTP)
    with pytest.raises(ValidationError, match="forbidden"):
        _result(rung=LadderRung.STEALTH_BROWSER, method=FetchMethod.PLAIN_HTTP)


def test_mapping_rejects_evidence_different_from_context() -> None:
    result = _result(rung=LadderRung.BROWSER, method=FetchMethod.PLAYWRIGHT)
    with pytest.raises(ValueError, match="differs from collection context"):
        map_product(_product(), result, CONTEXT)
