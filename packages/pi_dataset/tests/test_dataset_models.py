"""Model invariants of pi.dataset/v2: money, match edges, offers and cross-field references."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pi_core import MatchClass, ReviewState
from pi_core.money import CURRENCY_EXPONENTS
from pi_dataset import Dataset, DecidedBy, MatchEdge, MoneyValue, NotObserved
from pi_dataset.examples import ae_pilot, fr_two_retailers, kw_three_retailers


def _doc() -> dict[str, Any]:
    return ae_pilot().model_dump(mode="json")


def _errors(doc: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        Dataset.model_validate(doc)
    return str(info.value)


# ------------------------------------------------------------------ money


@pytest.mark.parametrize(
    ("amount", "currency", "text", "minor"),
    [
        ("129", "AED", "129.00", 12900),
        ("3.25", "KWD", "3.250", 3250),
        ("1500", "JPY", "1500", 1500),
        ("24.9", "EUR", "24.90", 2490),
    ],
)
def test_money_of_uses_the_iso_exponent(amount: str, currency: str, text: str, minor: int) -> None:
    money = MoneyValue.of(Decimal(amount), currency)
    assert (money.amount, money.minor, money.currency) == (text, minor, currency)
    assert money.decimal() == Decimal(amount)


def test_money_of_refuses_inexact_amounts_and_unknown_currencies() -> None:
    with pytest.raises(ValueError, match="not exact"):
        MoneyValue.of(Decimal("1.005"), "AED")
    with pytest.raises(ValueError, match="unknown currency"):
        MoneyValue.of(Decimal(1), "XXY")


@pytest.mark.parametrize(
    ("amount", "minor", "currency", "message"),
    [
        ("129.0", 1290, "AED", "exactly 2 decimals"),
        ("3.25", 325, "KWD", "exactly 3 decimals"),
        ("129.00", 12901, "AED", "does not match"),
        ("129", 129, "AED", "exactly 2 decimals"),
        ("1e3", 1000, "JPY", "pattern"),
    ],
)
def test_money_rejects_inexact_forms(amount: str, minor: int, currency: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        MoneyValue(amount=amount, minor=minor, currency=currency)


@given(
    minor=st.integers(min_value=-(10**12), max_value=10**12),
    currency=st.sampled_from(sorted(CURRENCY_EXPONENTS)),
)
def test_money_round_trips_exactly(minor: int, currency: str) -> None:
    amount = Decimal(minor).scaleb(-CURRENCY_EXPONENTS[currency])
    money = MoneyValue.of(amount, currency)
    assert money.minor == minor
    assert MoneyValue.model_validate_json(money.model_dump_json()) == money


# ------------------------------------------------------------------ match edges


def _edge(**overrides: Any) -> MatchEdge:
    fields: dict[str, Any] = {
        "a": "alpha_x",
        "b": "beta_x",
        "match_class": MatchClass.EXACT,
        "review_state": ReviewState.APPROVED,
        "decided_by": DecidedBy.HUMAN,
        "confidence": "0.9",
        "method": "m",
        "stage": "s",
    } | overrides
    return MatchEdge(**fields)


def test_locked_stays_locked_on_the_wire() -> None:
    edge = _edge(review_state=ReviewState.LOCKED)
    assert edge.model_dump(mode="json")["reviewState"] == "locked"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"a": "beta_x", "b": "alpha_x"}, "ordered a < b"),
        ({"b": "alpha_x"}, "ordered a < b"),
        ({"review_state": ReviewState.PROPOSED}, "decided_by"),
        ({"decided_by": None}, "decided_by"),
        ({"confidence": "1.5"}, "outside 0..1"),
        ({"confidence": "-0.5"}, "pattern"),
        ({"review_state": ReviewState.LOCKED, "decided_by": DecidedBy.AUTO}, "locked edge"),
        ({"review_state": "accepted"}, "review_state"),
        ({"review_state": "auto_accepted"}, "review_state"),
    ],
)
def test_edge_invariants(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _edge(**overrides)


def test_proposed_edge_has_no_decider() -> None:
    edge = _edge(review_state=ReviewState.PROPOSED, decided_by=None, confidence=None)
    assert edge.decided_by is None


# ------------------------------------------------------------------ documents


@pytest.mark.parametrize("build", [ae_pilot, kw_three_retailers, fr_two_retailers])
def test_examples_are_valid_and_round_trip(build: Any) -> None:
    dataset = build()
    again = Dataset.model_validate_json(dataset.model_dump_json())
    assert again == dataset
    assert dataset.meta.test is True


def test_wire_names_are_camel_case_and_nulls_explicit() -> None:
    doc = _doc()
    assert doc["schema"] == "pi.dataset/v2"
    assert "generatedAt" in doc["meta"]
    assert "notObserved" in doc
    retailer = doc["meta"]["retailers"][0]
    assert retailer["note"] is None
    assert "earlyExamples" in retailer
    offer = doc["products"][0]["offers"]["example_south_ae"]
    assert offer["series"]["price"][1] is None


def test_market_of_resolves_the_retailer_market() -> None:
    dataset = kw_three_retailers()
    assert dataset.market_of("example_beta_kw").currency == "KWD"


def test_offer_currency_must_match_its_series() -> None:
    doc = _doc()
    offer = doc["products"][0]["offers"]["example_north_ae"]
    offer["series"]["price"][0] = {"amount": "10.00", "minor": 1000, "currency": "EUR"}
    assert "series money in ['EUR']" in _errors(doc)


def test_offer_currency_must_match_its_market() -> None:
    doc = _doc()
    offer = doc["products"][0]["offers"]["example_north_ae"]
    offer["currency"] = "EUR"
    for name in ("price", "regular"):
        offer["series"][name] = [
            None if m is None else {**m, "currency": "EUR"} for m in offer["series"][name]
        ]
    assert "currency EUR != market currency AED" in _errors(doc)


def test_series_length_must_match_dates() -> None:
    doc = _doc()
    doc["products"][0]["offers"]["example_north_ae"]["series"]["availability"].append("in_stock")
    assert "series.availability: length 4 != 3 dates" in _errors(doc)


def test_reference_errors_are_all_reported() -> None:
    doc = _doc()
    doc["products"][1]["id"] = doc["products"][0]["id"]
    doc["products"][2]["offers"]["ghost_ae"] = doc["products"][2]["offers"].pop("example_north_ae")
    doc["notObserved"] = [
        {
            "retailer": "ghost_ae",
            "start": "2026-09-28",
            "end": "2026-09-28",
            "categories": None,
            "why": {"en": "x"},
        }
    ]
    doc["meta"]["retailers"].append({**doc["meta"]["retailers"][0], "country": "FR"})
    message = _errors(doc)
    for expected in (
        "products: duplicate id p-0001",
        "offers.ghost_ae: unknown retailer",
        "notObserved: unknown retailer ghost_ae",
        "meta.retailers: duplicate id example_north_ae",
        "country FR not in markets",
    ):
        assert expected in message


def test_duplicate_markets_are_rejected() -> None:
    doc = _doc()
    doc["meta"]["markets"].append(doc["meta"]["markets"][0])
    assert "duplicate country AE" in _errors(doc)


@pytest.mark.parametrize(
    ("dates", "message"),
    [
        (["2026-09-29", "2026-09-28", "2026-09-30"], "strictly increasing"),
        (["2026-09-28", "2026-09-28", "2026-09-30"], "strictly increasing"),
        (["2026-09-29", "2026-09-30", "2026-10-01"], "after the cutoff"),
    ],
)
def test_dates_rules(dates: list[str], message: str) -> None:
    doc = _doc()
    doc["meta"]["dates"] = dates
    assert message in _errors(doc)


def test_dates_are_local_to_each_market() -> None:
    # 2026-09-30T00:00Z is still the 29th in New York, so a date of the 30th is in the future.
    doc = _doc()
    doc["meta"]["markets"][0]["timeZone"] = "America/New_York"
    assert "after the cutoff's local date 2026-09-29 in AE (America/New_York)" in _errors(doc)


@pytest.mark.parametrize("amount", [("0.00", 0), ("-1.00", -100)])
def test_prices_must_be_positive(amount: tuple[str, int]) -> None:
    doc = _doc()
    for field in ("price", "regular"):
        doc["products"][0]["offers"]["example_north_ae"]["series"][field][0] = {
            "amount": amount[0],
            "minor": amount[1],
            "currency": "AED",
        }
    assert "prices must be positive" in _errors(doc)


def test_availability_uses_null_for_not_observed() -> None:
    doc = _doc()
    doc["products"][0]["offers"]["example_north_ae"]["series"]["availability"][0] = "not_observed"
    assert "use null" in _errors(doc)


def test_generated_before_cutoff_is_rejected() -> None:
    doc = _doc()
    doc["meta"]["generatedAt"] = "2026-09-29T23:00:00Z"
    assert "generatedAt is before" in _errors(doc)


def test_match_edge_needs_both_offers() -> None:
    doc = _doc()
    del doc["products"][0]["offers"]["example_south_ae"]
    assert "without an offer" in _errors(doc)


def test_duplicate_match_edges_are_rejected() -> None:
    doc = _doc()
    edges = doc["products"][0]["matches"]
    edges.append(edges[0])
    assert "duplicate match edge" in _errors(doc)


def test_not_observed_window_must_be_ordered() -> None:
    today = date(2026, 9, 30)
    with pytest.raises(ValidationError, match="before start"):
        NotObserved(
            retailer="alpha_x",
            start=today,
            end=today - timedelta(days=1),
            categories=None,
            why={"en": "x"},
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("meta", "markets", 0, "timeZone"), "Mars/Base", "unknown time zone"),
        (("meta", "markets", 0, "currency"), "ZZZ", "currency"),
        (("meta", "markets", 0, "country"), "ZZ", "country"),
        (("meta", "retailers", 0, "id"), "Bad-Key", "pattern"),
        (("meta", "scope"), "Pilot/1", "pattern"),
        (("meta", "kind"), "delta", "snapshot"),
        (("schema",), "pi.dataset/v1", "pi.dataset/v2"),
        (("meta", "retailers", 0, "status"), "ok", "status"),
        (("products", 0, "brand"), "  ", "pattern"),
        (("products", 0, "offers", "example_north_ae", "size", "value"), "0", "must be positive"),
        (("products", 0, "offers", "example_north_ae", "size", "value"), "-50", "pattern"),
        (("products", 0, "offers", "example_north_ae", "rating", "average"), "-1", "pattern"),
        (("products", 0, "offers", "example_north_ae", "rating", "average"), "5.5", "above"),
        (("products", 0, "offers", "example_north_ae", "rating", "scale"), "0", "scale 0"),
    ],
)
def test_field_rules(path: tuple[str | int, ...], value: str, message: str) -> None:
    doc = _doc()
    target: Any = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert message in _errors(doc)


def test_unknown_keys_are_rejected() -> None:
    doc = _doc()
    doc["meta"]["extra"] = 1
    assert "Extra inputs" in _errors(doc)


def test_python_names_are_accepted_too() -> None:
    dataset = ae_pilot()
    rebuilt = Dataset.model_validate(dataset.model_dump(by_alias=False))
    assert rebuilt == dataset
