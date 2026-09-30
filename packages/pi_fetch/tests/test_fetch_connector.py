import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import HttpUrl, ValidationError

import pi_fetch
from fetch_helpers import NOW, make_ctx
from pi_core import (
    AvailabilityState,
    FetchMethod,
    FieldState,
    LadderRung,
    ListingFields,
    ListingRecord,
    Locale,
    OfferFields,
    OfferObservation,
    PriceType,
)
from pi_fetch import (
    Connector,
    DiscoveredItem,
    FetchRequest,
    FetchResult,
    ListingDraft,
    OfferDraft,
    ParseError,
    ParseOutput,
    PayloadKind,
    to_canonical,
)
from pi_fetch.connector import PIPELINE_OWNED_OFFER_FIELDS
from sample_connector import SampleConnector

CTX = make_ctx(LadderRung.SITE_DATA)
PRODUCT = {
    "id": "2583611",
    "name": "Rouge Lipstick",
    "brand": "Maison",
    "price": "129.00",
    "in_stock": True,
    "observed_at": "2026-09-30T22:00:00+04:00",
}


def fetched(body: dict[str, Any] | bytes = PRODUCT) -> FetchResult:
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    url = HttpUrl("https://shop.example/api/p/2583611")
    return FetchResult(
        request=FetchRequest(url=url, kind=PayloadKind.JSON, locale=Locale.EN),
        final_url=url,
        http_status=200,
        content_type="application/json",
        body=payload,
        headers={"content-type": "application/json"},
        ladder_rung_used=LadderRung.SITE_DATA,
        fetch_method=FetchMethod.SITE_API,
        egress="direct",
        retrieved_at=NOW,
        elapsed_ms=4,
        from_cache=False,
        block=None,
        evidence_uri="file:///evidence/ab/abcd",
    )


def drafts() -> tuple[ListingDraft, OfferDraft]:
    out = SampleConnector().parse(fetched(), CTX)
    return out.listings[0], out.offers[0]


def offer_fields(**changes: Any) -> dict[str, Any]:
    _, offer = drafts()
    values = {n: getattr(offer, n) for n in type(offer).model_fields}
    values = {n: v for n, v in values.items() if n not in PIPELINE_OWNED_OFFER_FIELDS}
    values.update(changes)
    return values


def test_interface_version() -> None:
    assert pi_fetch.INTERFACE_VERSION == "0.2"


def test_drafts_share_pi_core_bases() -> None:
    assert issubclass(ListingDraft, ListingFields)
    assert issubclass(OfferDraft, OfferFields)
    assert not issubclass(ListingDraft, ListingRecord)
    assert not issubclass(OfferDraft, OfferObservation)


def test_listing_draft_fields_are_canonical_minus_ids() -> None:
    assert set(ListingDraft.model_fields) == set(ListingRecord.model_fields) - {
        "source_id",
        "evidence_id",
    }


def test_offer_draft_fields_are_canonical_minus_pipeline_values_plus_key() -> None:
    assert set(OfferDraft.model_fields) == (
        set(OfferObservation.model_fields) - {"source_listing_id", "evidence_id", "ingested_at"}
    ) | {"source_listing_key"}


def test_sample_connector_satisfies_protocol() -> None:
    assert isinstance(SampleConnector(), Connector)
    items = list(SampleConnector().discover(CTX))
    assert [r.kind for r in SampleConnector().requests_for(items[0], CTX)] == [PayloadKind.JSON]


@pytest.mark.parametrize(
    "key",
    [
        "https://shop.example/p/1",
        "/p/1",
        "?id=1",
        "d41d8cd98f00b204e9800998ecf8427e",
        "a" * 64,
        " ",
    ],
)
def test_source_listing_key_is_the_sites_own_id(key: str) -> None:
    with pytest.raises(ValidationError):
        OfferDraft.model_validate(offer_fields(source_listing_key=key))
    with pytest.raises(ValidationError):
        DiscoveredItem(
            url=HttpUrl("https://s.example/"),
            kind=PayloadKind.XML,
            locale=Locale.EN,
            source_listing_key=key,
        )


def test_drafts_enforce_pi_core_money_rules() -> None:
    with pytest.raises(ValidationError):
        OfferDraft.model_validate(offer_fields(price_current=Decimal(0)))
    with pytest.raises(ValidationError, match="without a field_state reason"):
        OfferDraft.model_validate(offer_fields(price_current=None))
    with pytest.raises((ValidationError, TypeError), match="float is not accepted"):
        OfferDraft.model_validate(offer_fields(price_current=1.5))


def test_drafts_enforce_availability_rules() -> None:
    gaps = {**offer_fields()["field_state"], "availability_state": FieldState.BLOCKED}
    with pytest.raises(ValidationError, match="DAT-06"):
        OfferDraft.model_validate(
            offer_fields(availability_state=AvailabilityState.OUT_OF_STOCK, field_state=gaps)
        )
    with pytest.raises(ValidationError, match="low_stock"):
        OfferDraft.model_validate(offer_fields(availability_state=AvailabilityState.LOW_STOCK))


def test_drafts_enforce_range_and_rating_rules() -> None:
    with pytest.raises(ValidationError, match="PRC-13"):
        OfferDraft.model_validate(offer_fields(price_type=PriceType.QUOTE_ONLY))
    gaps = {k: v for k, v in offer_fields()["field_state"].items() if k != "rating_value"}
    with pytest.raises(ValidationError, match="rating_scale"):
        OfferDraft.model_validate(offer_fields(rating_value=Decimal("4.5"), field_state=gaps))


@pytest.mark.parametrize("name", sorted(PIPELINE_OWNED_OFFER_FIELDS | {"ingested_at"}))
def test_offer_draft_refuses_pipeline_owned_fields(name: str) -> None:
    value: Any = {"promotion_ids": (1,), "recorded_at": NOW, "ingested_at": NOW}.get(name, 1)
    if name == "quality_status":
        value = "accepted"
    # ingested_at is not an OfferDraft field at all, so extra="forbid" refuses it.
    with pytest.raises(ValidationError, match=r"pipeline-owned|Extra inputs"):
        OfferDraft.model_validate(offer_fields(**{name: value}))


def test_parse_output_links_offers_to_listings() -> None:
    listing, offer = drafts()
    ParseOutput(listings=(listing,), offers=(offer,))
    ParseOutput(listings=(), offers=(offer,), existing_listing_keys=frozenset({"2583611"}))
    with pytest.raises(ValidationError, match="not in this output"):
        ParseOutput(listings=(), offers=(offer,))
    with pytest.raises(ValidationError, match="duplicate"):
        ParseOutput(listings=(listing, listing), offers=())


def test_to_canonical_listing() -> None:
    listing, _ = drafts()
    record = to_canonical(listing, source_id=3, evidence_id=99)
    assert isinstance(record, ListingRecord)
    assert record.natural_key == (3, "2583611")
    assert record.evidence_id == 99


def test_to_canonical_offer_takes_pipeline_ingested_at_and_checks_context() -> None:
    _, offer = drafts()
    ingested = offer.observed_at + timedelta(minutes=5)
    obs = to_canonical(
        offer, source_listing_id=41, evidence_id=99, ingested_at=ingested, context=CTX
    )
    assert isinstance(obs, OfferObservation)
    assert (obs.source_listing_id, obs.evidence_id, obs.ingested_at) == (41, 99, ingested)
    assert obs.price_current == Decimal("129.00")
    assert obs.currency == "AED"


def test_to_canonical_offer_revalidates() -> None:
    _, offer = drafts()
    with pytest.raises(ValidationError, match="ingested_at is before"):
        to_canonical(
            offer,
            source_listing_id=41,
            evidence_id=99,
            ingested_at=offer.observed_at - timedelta(seconds=1),
            context=CTX,
        )
    with pytest.raises(ValidationError):
        to_canonical(offer, source_listing_id=0, evidence_id=99, ingested_at=NOW, context=CTX)


def test_to_canonical_offer_refuses_another_context() -> None:
    _, offer = drafts()
    other = CTX.model_copy(update={"crawl_run_id": 12})
    with pytest.raises(ValueError, match="crawl run"):
        to_canonical(offer, source_listing_id=41, evidence_id=99, ingested_at=NOW, context=other)


def test_to_canonical_refuses_wrong_ids() -> None:
    listing, offer = drafts()
    with pytest.raises(ValueError, match="source_id"):
        to_canonical(listing, source_id=3, evidence_id=1, source_listing_id=4)  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="source_listing_id"):
        to_canonical(offer, source_id=3, evidence_id=1)  # type: ignore[call-overload]


@given(price=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(99999), places=2))
def test_replaying_a_result_gives_identical_drafts(price: Decimal) -> None:
    result = fetched({**PRODUCT, "price": str(price)})
    first = SampleConnector().parse(result, CTX)
    again = SampleConnector().parse(result.model_copy(), CTX)
    assert first == again
    assert first.model_dump_json() == again.model_dump_json()


def test_layout_drift_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        SampleConnector().parse(fetched(b'{"unexpected": true}'), CTX)
