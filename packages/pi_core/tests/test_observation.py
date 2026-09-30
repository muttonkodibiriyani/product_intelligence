from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pi_core import (
    CURRENCY_EXPONENTS,
    AvailabilityState,
    CollectionContext,
    FetchMethod,
    FieldState,
    Locale,
    Market,
    Money,
    OfferObservation,
    PriceType,
    PromotionMechanic,
    PromotionRecord,
    SourceContext,
    TaxStatus,
)
from pi_core.observation import NEGATIVE_AVAILABILITY

T0 = datetime(2026, 9, 30, 6, tzinfo=UTC)
CTX_ID = 1
RUN_ID = 3


def context(market: Market = Market.KSA) -> CollectionContext:
    return CollectionContext(
        source_context=SourceContext(
            id=CTX_ID,
            source_id=2,
            country=market,
            locale=Locale.EN,
            time_zone=market.time_zone,
            valid_from=T0 - timedelta(days=30),
        ),
        crawl_run_id=RUN_ID,
        connector_version="sephora_me@0.1.0",
        ladder_rung_used=FetchMethod.SITE_API.rung,
        fetch_method=FetchMethod.SITE_API,
    )


def obs_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "crawl_run_id": RUN_ID,
        "source_context_id": CTX_ID,
        "source_listing_id": 5,
        "observed_at": T0,
        "ingested_at": T0 + timedelta(minutes=1),
        "price_current": "345.00",
        "price_regular_stated": "345.00",
        "price_promo": None,
        "price_member": None,
        "price_type": PriceType.FULL,
        "currency": "SAR",
        "installment": {"provider": "tabby", "instalment_count": 4, "instalment_amount": "86.25"},
        "tax_status": TaxStatus.INCLUDED,
        "availability_state": AvailabilityState.IN_STOCK,
        "available_variants": 3,
        "low_stock_flag": False,
        "delivery_promise": None,
        "rating_value": "4.6",
        "rating_scale": "5",
        "rating_count": 812,
        "rank_in_category": 4,
        "rank_in_search": {"perfume": 2},
        "badges_at_time": ("Bestseller",),
        "evidence_id": 7,
        "field_state": {
            "price_promo": FieldState.NOT_APPLICABLE,
            "price_member": FieldState.NOT_PUBLISHED,
            "delivery_promise": FieldState.NOT_PUBLISHED,
        },
    }
    return data | overrides


def observation(**overrides: Any) -> OfferObservation:
    return OfferObservation.model_validate(obs_data(**overrides))


def test_valid_observation_and_money() -> None:
    obs = observation()
    assert obs.money("price_current") == Money.of("345.00", "SAR")
    assert obs.money("price_promo") is None
    assert obs.instalment_money == Money.of("86.25", "SAR")
    assert (
        observation(
            installment=None,
            field_state=obs_data()["field_state"] | {"installment": FieldState.NOT_PUBLISHED},
        ).instalment_money
        is None
    )
    obs.check_context(context())


def test_check_context_rejects_foreign_currency_run_and_context() -> None:
    with pytest.raises(ValueError, match="differs from context AED"):
        observation().check_context(context(Market.UAE))
    with pytest.raises(ValueError, match="different crawl run"):
        observation(crawl_run_id=99).check_context(context())
    with pytest.raises(ValueError, match="different source context"):
        observation(source_context_id=99).check_context(context())


def test_idempotency_key_is_the_logical_key() -> None:
    base = observation()
    # A retried run re-observing the same instant is the same fact (DAT-09).
    assert observation(crawl_run_id=4).idempotency_key == base.idempotency_key
    assert observation(price_current="300.00").idempotency_key == base.idempotency_key
    # Different grain or instant is a different fact (DAT-02).
    assert observation(seller_id="seller-8").idempotency_key != base.idempotency_key
    assert observation(observed_at=T0 + timedelta(seconds=1)).idempotency_key != (
        base.idempotency_key
    )
    # A correction points at the original row id and is a new fact.
    correction = observation(correction_of=123, price_current="300.00")
    assert correction.idempotency_key != base.idempotency_key


def test_failed_crawl_is_blocked_not_out_of_stock() -> None:
    # DAT-06: a block yields blocked + reasons, never a fabricated zero or stock-out.
    reasons = dict.fromkeys(OfferObservation.TRACKED_FIELDS, FieldState.BLOCKED)
    obs = observation(
        **dict.fromkeys(OfferObservation.TRACKED_FIELDS),
        rating_scale=None,
        availability_state=AvailabilityState.BLOCKED,
        tax_status=TaxStatus.UNKNOWN,
        rank_in_search={},
        badges_at_time=(),
        field_state=reasons,
    )
    assert not obs.availability_state.is_known
    assert obs.price_current is None


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"price_current": 345.0}, "float"),
        ({"price_current": "1.23456"}, "decimal places"),
        ({"currency": "XXX"}, "unsupported currency"),
        ({"price_current": None}, "price_current is null without"),
        ({"ingested_at": T0 - timedelta(seconds=1)}, "ingested_at is before"),
        ({"recorded_at": T0}, "recorded_at is before"),
        (
            {"source_effective_from": T0, "source_effective_to": T0 - timedelta(days=1)},
            "source_effective_to is before",
        ),
        ({"unit_price_derived": "69.00"}, "unit_price_derived and unit_basis"),
        ({"price_type": PriceType.PROMOTIONAL}, "requires price_promo"),
        ({"price_type": PriceType.MEMBER}, "requires price_member"),
        ({"price_type": PriceType.QUOTE_ONLY}, "quote_only offer has no single current price"),
        ({"rating_value": "-1"}, "greater than or equal"),
        ({"rating_value": "4.567"}, "decimal places"),
        ({"rating_value": "5.5"}, "exceeds rating_scale"),
        ({"rating_scale": None}, "rating_value and rating_scale"),
        ({"rating_scale": "0"}, "greater than 0"),
        ({"unit_price_derived": "-1", "unit_basis": "100ml"}, "greater than 0"),
        ({"price_type": PriceType.RANGE}, "no single current price"),
        ({"price_range_min": "10"}, "only set for price_type range"),
        ({"availability_state": AvailabilityState.LOW_STOCK}, "must agree"),
        ({"low_stock_flag": True}, "must agree"),
        ({"rating_value": 4.5}, "float"),
        ({"source_listing_id": 0}, "greater than or equal"),
        ({"rank_in_search": {"perfume": 0}}, "greater than or equal"),
        (
            {"installment": {"provider": "tabby", "instalment_count": 1, "instalment_amount": "1"}},
            "greater than or equal",
        ),
        ({"observed_at": "2026-09-30T06:00:00"}, "timezone"),
    ],
)
def test_observation_invariants(overrides: dict[str, Any], error: str) -> None:
    with pytest.raises((ValidationError, TypeError), match=error):
        observation(**overrides)


def test_installment_price_type_requires_plan() -> None:
    fs = obs_data()["field_state"] | {"installment": FieldState.NOT_PUBLISHED}
    with pytest.raises(ValidationError, match="requires installment"):
        observation(price_type=PriceType.INSTALLMENT, installment=None, field_state=fs)


currencies = st.sampled_from(sorted(CURRENCY_EXPONENTS))
amounts = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("99999.9999"), places=4, allow_nan=False
)


@given(
    currency=currencies,
    current=amounts,
    regular=amounts,
    offset=st.integers(min_value=-12, max_value=14),
)
def test_observation_round_trip_and_money_consistency(
    currency: str, current: Decimal, regular: Decimal, offset: int
) -> None:
    observed = T0.astimezone(timezone(timedelta(hours=offset)))
    obs = observation(
        currency=currency,
        price_current=current,
        price_regular_stated=regular,
        observed_at=observed,
        ingested_at=observed + timedelta(minutes=5),
    )
    again = OfferObservation.model_validate_json(obs.model_dump_json())
    assert again == obs
    assert again.idempotency_key == obs.idempotency_key
    assert again.idempotency_key == observation().idempotency_key  # same instant, any offset
    for field in ("price_current", "price_regular_stated"):
        money = again.money(field)
        assert money is not None
        assert money.currency == currency
        assert money.amount.as_tuple() == getattr(obs, field).as_tuple()


def promotion(**overrides: Any) -> PromotionRecord:
    data: dict[str, Any] = {
        "source_context_id": CTX_ID,
        "mechanic": PromotionMechanic.PERCENT_OFF,
        "terms_original": "20% off fragrance, min spend SAR 300",
        "rule": {"percent": 20, "scope": ["fragrance"]},
        "min_spend": "300",
        "min_spend_currency": "SAR",
        "advertised_from": T0,
        "advertised_to": T0 + timedelta(days=7),
        "first_seen_at": T0,
        "last_seen_at": T0 + timedelta(days=1),
        "evidence_id": 7,
    }
    return PromotionRecord.model_validate(data | overrides)


def test_promotion() -> None:
    promo = promotion()
    assert promo.min_spend_money == Money.of("300", "SAR")
    assert promotion(min_spend=None, min_spend_currency=None).min_spend_money is None
    assert PromotionRecord.model_validate_json(promo.model_dump_json()) == promo


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"min_spend_currency": None}, "min_spend and min_spend_currency"),
        ({"last_seen_at": T0 - timedelta(seconds=1)}, "last_seen_at is before"),
        ({"advertised_to": T0 - timedelta(days=1)}, "advertised_to is before"),
        ({"min_qty": 0}, "greater than or equal"),
        ({"min_spend": "0"}, "greater than 0"),
        ({"min_spend": "-1"}, "greater than 0"),
    ],
)
def test_promotion_invariants(overrides: dict[str, Any], error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        promotion(**overrides)


PRICE_FIELDS = ("price_current", "price_regular_stated", "price_promo", "price_member")


@pytest.mark.parametrize("field", PRICE_FIELDS)
@pytest.mark.parametrize("value", ["0", "0.00", "-10.00"])
def test_prices_are_strictly_positive(field: str, value: str) -> None:
    # Missing is never zero (DQ-02): a price is None plus a reason, or > 0.
    fs = {k: v for k, v in obs_data()["field_state"].items() if k != field}
    with pytest.raises(ValidationError, match="greater than 0"):
        observation(**{field: value}, field_state=fs)


def test_range_price() -> None:
    fs = obs_data()["field_state"] | {"price_current": FieldState.NOT_APPLICABLE}
    obs = observation(
        price_type=PriceType.RANGE,
        price_current=None,
        price_range_min="120",
        price_range_max="345",
        field_state=fs,
    )
    assert obs.money("price_range_min") == Money.of("120", "SAR")
    with pytest.raises(ValidationError, match="requires price_range_min"):
        observation(price_type=PriceType.RANGE, price_current=None, field_state=fs)
    with pytest.raises(ValidationError, match="exceeds price_range_max"):
        observation(
            price_type=PriceType.RANGE,
            price_current=None,
            price_range_min="400",
            price_range_max="345",
            field_state=fs,
        )


def test_low_stock_agrees_with_flag() -> None:
    obs = observation(availability_state=AvailabilityState.LOW_STOCK, low_stock_flag=True)
    assert obs.low_stock_flag is True
    unknown_flag = obs_data()["field_state"] | {"low_stock_flag": FieldState.NOT_PUBLISHED}
    assert observation(low_stock_flag=None, field_state=unknown_flag).low_stock_flag is None


@given(
    reason=st.none() | st.sampled_from(FieldState),
    state=st.sampled_from([s for s in AvailabilityState if s is not AvailabilityState.LOW_STOCK]),
)
def test_no_false_stock_outs(reason: FieldState | None, state: AvailabilityState) -> None:
    # DAT-06: a negative availability claim is recorded only when it was observed on the page.
    fs = dict(obs_data()["field_state"])
    if reason is not None:
        fs["availability_state"] = reason
    if state in NEGATIVE_AVAILABILITY and reason is not FieldState.OBSERVED:
        with pytest.raises(ValidationError, match=f"cannot record {state}"):
            observation(availability_state=state, field_state=fs)
    else:
        assert observation(availability_state=state, field_state=fs).availability_state is state


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (AvailabilityState.REMOVED, FieldState.BLOCKED),
        (AvailabilityState.NOT_DELIVERABLE, FieldState.UNKNOWN),
        (AvailabilityState.OUT_OF_STOCK, FieldState.PARSE_FAILURE),
        (AvailabilityState.OUT_OF_STOCK, None),
    ],
)
def test_negative_availability_needs_observation(
    state: AvailabilityState, reason: FieldState | None
) -> None:
    fs = dict(obs_data()["field_state"])
    if reason is not None:
        fs["availability_state"] = reason
    with pytest.raises(ValidationError, match=f"availability not observed \\({reason}\\)"):
        observation(availability_state=state, field_state=fs)


def test_blocked_price_with_observed_stock_out_is_accepted() -> None:
    # The page loaded and showed "out of stock"; only the price widget failed.
    fs = obs_data()["field_state"] | {
        "price_current": FieldState.BLOCKED,
        "availability_state": FieldState.OBSERVED,
    }
    obs = observation(
        price_current=None, availability_state=AvailabilityState.OUT_OF_STOCK, field_state=fs
    )
    assert obs.availability_state is AvailabilityState.OUT_OF_STOCK
    assert obs.price_current is None


def test_observed_is_not_a_null_reason() -> None:
    fs = obs_data()["field_state"] | {"price_current": FieldState.OBSERVED}
    with pytest.raises(ValidationError, match="observed is not a null reason"):
        observation(price_current=None, field_state=fs)


def test_availability_qualifier_is_the_only_extra_field_state_key() -> None:
    with pytest.raises(ValidationError, match="untracked"):
        observation(field_state=obs_data()["field_state"] | {"tax_status": FieldState.UNKNOWN})
