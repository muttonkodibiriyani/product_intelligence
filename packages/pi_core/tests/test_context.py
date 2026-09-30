from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pi_core import (
    CollectionContext,
    Evidence,
    FetchMethod,
    LadderRung,
    Locale,
    Market,
    Source,
    SourceContext,
    SourceKind,
    content_hash_of,
)

T0 = datetime(2026, 9, 30, tzinfo=UTC)


def source_context(**overrides: Any) -> SourceContext:
    data: dict[str, Any] = {
        "id": UUID(int=1),
        "source_id": UUID(int=2),
        "country": Market.KSA,
        "locale": Locale.EN,
        "time_zone": "Asia/Riyadh",
        "valid_from": T0,
    }
    return SourceContext.model_validate(data | overrides)


def collection_context(method: FetchMethod = FetchMethod.SITE_API, **ctx: Any) -> CollectionContext:
    return CollectionContext(
        source_context=source_context(**ctx),
        crawl_run_id=UUID(int=3),
        connector_version="sephora_me@0.1.0",
        ladder_rung_used=method.rung,
        fetch_method=method,
    )


def test_every_method_has_a_rung_and_every_rung_a_method() -> None:
    assert {m.rung for m in FetchMethod} == set(LadderRung)


@pytest.mark.parametrize(("market", "currency"), [(Market.KSA, "SAR"), (Market.UAE, "AED")])
def test_currency_comes_from_market(market: Market, currency: str) -> None:
    ctx = source_context(country=market, time_zone=market.time_zone)
    assert ctx.currency == currency
    assert collection_context(country=market).currency == currency


def test_locale_direction() -> None:
    assert Locale.AR.is_rtl
    assert not Locale.EN.is_rtl


def test_context_defaults_forbid_paid_rung() -> None:
    ctx = source_context()
    assert ctx.ladder_rung_max_allowed is LadderRung.EGRESS_VARIATION
    with pytest.raises(ValidationError, match="exceeds the context's allowed"):
        collection_context(FetchMethod.RESIDENTIAL_PROXY)


def test_paid_rung_allowed_only_when_owner_raised_the_cap() -> None:
    ctx = collection_context(
        FetchMethod.RESIDENTIAL_PROXY, ladder_rung_max_allowed=LadderRung.PAID_PROXY
    )
    assert ctx.ladder_rung_used.is_paid
    assert ctx.market is Market.KSA
    assert ctx.locale is Locale.EN


def test_method_must_match_rung() -> None:
    with pytest.raises(ValidationError, match="belongs to rung"):
        CollectionContext(
            source_context=source_context(),
            crawl_run_id=uuid4(),
            connector_version="x",
            ladder_rung_used=LadderRung.SITE_DATA,
            fetch_method=FetchMethod.PLAYWRIGHT,
        )


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"ladder_rung_current": LadderRung.PAID_PROXY}, "exceeds ladder_rung_max_allowed"),
        ({"valid_to": T0}, "valid_to must be after"),
        ({"fallback_of": UUID(int=1)}, "own fallback"),
        ({"time_zone": "Mars/Olympus"}, "unknown time zone"),
        ({"valid_from": datetime(2026, 1, 1)}, "timezone"),  # noqa: DTZ001
        ({"currency": "SAR"}, "Extra inputs"),
    ],
)
def test_source_context_invariants(overrides: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        source_context(**overrides)


def test_uae_fallback_context() -> None:
    uae = source_context(
        id=UUID(int=9), country=Market.UAE, time_zone="Asia/Dubai", fallback_of=UUID(int=1)
    )
    assert uae.currency == "AED"


def test_datetimes_normalised_to_utc() -> None:
    ctx = source_context(valid_from="2026-09-30T03:00:00+03:00")
    assert ctx.valid_from.tzinfo is UTC
    assert ctx.valid_from == datetime(2026, 9, 30, 0, tzinfo=UTC)


def test_models_are_frozen() -> None:
    ctx = source_context()
    with pytest.raises(ValidationError, match="frozen"):
        ctx.locale = Locale.AR  # type: ignore[misc]


def test_source() -> None:
    src = Source(id=uuid4(), name="Sephora ME", kind=SourceKind.WEB, base_url="https://sephora.me")  # type: ignore[arg-type]
    assert str(src.base_url) == "https://sephora.me/"


@given(
    market=st.sampled_from(Market),
    locale=st.sampled_from(Locale),
    method=st.sampled_from([m for m in FetchMethod if not m.rung.is_paid]),
)
def test_collection_context_round_trip(market: Market, locale: Locale, method: FetchMethod) -> None:
    ctx = collection_context(method, country=market, locale=locale, time_zone=market.time_zone)
    again = CollectionContext.model_validate_json(ctx.model_dump_json())
    assert again == ctx
    assert again.currency == market.currency


def evidence(**overrides: Any) -> Evidence:
    return Evidence.from_payload(
        collection_context(FetchMethod.CURL_CFFI),
        url="https://www.sephora.me/sa-en/p/P123",
        payload=b"<html>ok</html>",
        storage_uri="gs://bucket/raw/abc",
        retrieved_at=T0,
        http_status=200,
    ).model_copy(update=overrides)


def test_evidence_from_payload() -> None:
    ev = evidence()
    assert ev.content_hash == content_hash_of(b"<html>ok</html>")
    assert ev.ladder_rung_used is LadderRung.IMPERSONATED_HTTP
    assert ev.fetch_method is FetchMethod.CURL_CFFI
    assert Evidence.model_validate_json(ev.model_dump_json()) == ev
    assert Evidence.model_validate_json(ev.model_dump_json()).id == ev.id


def test_evidence_id_depends_on_content() -> None:
    assert evidence().id != evidence(content_hash="0" * 64).id


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"content_hash": "ABC"}, "String should match"),
        ({"http_status": 42}, "greater than or equal"),
        ({"fetch_method": FetchMethod.PLAYWRIGHT}, "belongs to rung"),
        ({"retention_until": T0}, "retention_until must be after"),
    ],
)
def test_evidence_invariants(overrides: dict[str, Any], error: str) -> None:
    data = evidence().model_dump() | overrides
    with pytest.raises(ValidationError, match=error):
        Evidence.model_validate(data)
