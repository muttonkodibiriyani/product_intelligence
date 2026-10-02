"""Reading invariants and exact JSON round-trips."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_capture.model import (
    READING_STATES,
    JsonValue,
    ProductCapture,
    Reading,
    ReadingError,
    ReadingState,
    capture_from_json,
    capture_to_json,
    decode_value,
    dumps,
    encode_value,
    load_lines,
    loads,
    reading_from_json,
    reading_to_json,
)
from pi_capture.registry import ATTRIBUTES, Attribute, AttributeLevel, UnknownAttributeError, get

decimals = st.decimals(allow_nan=False, allow_infinity=False, places=3)
# keys deliberately include ones that start with "$" so scraped content can collide with the tag
_keys = st.text(max_size=5) | st.sampled_from(["$decimal", "$", "$$decimal", "$$", "$x"])
json_values: st.SearchStrategy[JsonValue] = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text() | decimals,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(_keys, inner, max_size=4),
    max_leaves=12,
)
attributes = st.sampled_from(ATTRIBUTES)
states: st.SearchStrategy[ReadingState] = st.sampled_from(READING_STATES)


@st.composite
def readings(draw: st.DrawFn) -> Reading:
    a = draw(attributes)
    state = draw(states)
    if state == "observed":
        raw = draw(st.text() | st.none())
        value = draw(json_values)
        if raw is None and value is None:
            value = draw(st.text(min_size=1))
        return Reading(a.key, a.level, state, raw, value, draw(st.text() | st.none()))
    if state == "parse_failed":
        note = draw(st.text() | st.none())
        return Reading(a.key, a.level, state, draw(st.text()), None, None, note)
    return Reading(a.key, a.level, state)


@given(readings())
def test_valid_readings_round_trip(reading: Reading) -> None:
    assert reading_from_json(reading_to_json(reading)) == reading


@given(json_values)
def test_values_round_trip_exactly(value: JsonValue) -> None:
    assert decode_value(encode_value(value)) == value


@given(readings(), st.datetimes(timezones=st.timezones()))
def test_capture_round_trip(
    make_capture: Callable[..., ProductCapture], reading: Reading, when: datetime
) -> None:
    capture = make_capture(readings=(reading,), retrieved_at=when)
    again = loads(dumps(capture))
    assert again == capture
    assert again.retrieved_at.tzinfo is UTC
    assert capture_from_json(capture_to_json(capture)) == capture


@given(attributes, st.sampled_from(["not_shown", "blocked", "not_applicable", "parse_failed"]))
def test_non_observed_readings_never_carry_a_value(attr: Attribute, state: str) -> None:
    raw = "x" if state == "parse_failed" else None
    with pytest.raises(ReadingError):
        Reading(attr.key, attr.level, cast(ReadingState, state), raw, "value")


def test_scraped_tag_lookalikes_round_trip_unchanged(
    make_capture: Callable[..., ProductCapture],
) -> None:
    scraped: JsonValue = {
        "$decimal": "x",
        "$decimal2": "1",
        "$": None,
        "$$decimal": "2",
        "n": {"$decimal": "1"},
        "list": [{"$decimal": "3"}, Decimal("3")],
    }
    encoded = encode_value(scraped)
    assert encoded == {
        "$$decimal": "x",
        "$$decimal2": "1",
        "$$": None,
        "$$$decimal": "2",
        "n": {"$$decimal": "1"},
        "list": [{"$$decimal": "3"}, {"$decimal": "3"}],
    }
    assert decode_value(encoded) == scraped
    reading = Reading("structured_data", get("structured_data").level, "observed", "raw", scraped)
    capture = make_capture(readings=(reading,))
    again = loads(dumps(capture))
    assert again.readings[0].value == scraped
    assert isinstance(again.readings[0].value["list"][1], Decimal)  # type: ignore[index, call-overload]


def test_decoding_refuses_unescaped_tag_keys_and_bad_decimals() -> None:
    with pytest.raises(ReadingError, match="unescaped tag key"):
        decode_value({"$other": 1})
    with pytest.raises(ReadingError, match="unescaped tag key"):
        decode_value({"$decimal": "1", "x": 2})
    with pytest.raises(ReadingError, match="bad decimal"):
        decode_value({"$decimal": "NaN"})
    with pytest.raises(ReadingError, match="bad decimal"):
        decode_value({"$decimal": "Infinity"})
    with pytest.raises(ReadingError, match="bad decimal"):
        decode_value({"$decimal": "twelve"})
    assert decode_value({"$decimal": "-1.50"}) == Decimal("-1.50")


def test_non_finite_decimals_are_refused() -> None:
    level = get("price_minor").level
    for bad in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(ReadingError, match="NaN or infinite"):
            Reading("price_minor", level, "observed", "x", bad)
        with pytest.raises(ReadingError, match="NaN or infinite"):
            Reading("structured_data", get("structured_data").level, "observed", "x", [bad])
    with pytest.raises(ReadingError, match="not accepted"):
        loads('{"source": "s", "x": NaN}')
    with pytest.raises(ReadingError, match="not accepted"):
        loads('{"source": "s", "x": -Infinity}')


def test_currency_is_a_field_beside_the_amount(make_capture: Callable[..., ProductCapture]) -> None:
    level = get("price_minor").level
    ok = Reading("price_minor", level, "observed", "12.50 AED", 1250, "p", None, "AED")
    assert ok.currency == "AED"
    failed = Reading(
        "price_minor", level, "parse_failed", "1,299 SAR", None, "q", "ambiguous", "SAR"
    )
    assert failed.currency == "SAR"
    with pytest.raises(ReadingError, match="3-letter code"):
        Reading("price_minor", level, "observed", "x", 1, None, None, "aed")
    with pytest.raises(ReadingError, match="3-letter code"):
        Reading("price_minor", level, "observed", "x", 1, None, None, "AED ")
    with pytest.raises(ReadingError, match="cannot carry a currency"):
        Reading("price_minor", level, "not_shown", None, None, None, None, "AED")
    data = reading_to_json(ok)
    assert data["currency"] == "AED"
    assert reading_from_json(data) == ok
    assert reading_from_json({k: v for k, v in data.items() if k != "currency"}).currency is None
    capture = make_capture(readings=(ok, failed))
    assert loads(dumps(capture)) == capture


def test_looked_for_is_sorted_deduplicated_and_serialised(
    make_capture: Callable[..., ProductCapture],
) -> None:
    capture = make_capture(looked_for=("title", "gtin", "title"))
    assert capture.looked_for == ("gtin", "title")
    data = capture_to_json(capture)
    assert data["looked_for"] == ["gtin", "title"]
    assert capture_from_json(data) == capture
    assert loads(dumps(capture)) == capture
    assert capture_from_json({k: v for k, v in data.items() if k != "looked_for"}).looked_for == ()
    with pytest.raises(UnknownAttributeError):
        make_capture(looked_for=("no_such_key",))


def test_invariants_one_by_one() -> None:
    gtin = get("gtin")
    with pytest.raises(UnknownAttributeError):
        Reading("no_such_key", AttributeLevel.OFFER, "observed", "x")
    with pytest.raises(ReadingError, match="belongs to level"):
        Reading("gtin", AttributeLevel.OFFER, "observed", "x")
    with pytest.raises(ReadingError, match="unknown state"):
        Reading("gtin", gtin.level, "seen", "x")  # type: ignore[arg-type]
    with pytest.raises(ReadingError, match="needs raw text or a value"):
        Reading("gtin", gtin.level, "observed")
    with pytest.raises(ReadingError, match="must keep the raw text"):
        Reading("gtin", gtin.level, "parse_failed")
    with pytest.raises(ReadingError, match="cannot carry raw text"):
        Reading("gtin", gtin.level, "not_shown", "x")
    with pytest.raises(ReadingError, match="float"):
        Reading("price_minor", AttributeLevel.OFFER, "observed", "1.5", cast(JsonValue, 1.5))
    with pytest.raises(ReadingError, match="float"):
        Reading(
            "bulk_price_tiers",
            AttributeLevel.OFFER,
            "observed",
            None,
            [{"a": [cast(JsonValue, 1.5)]}],
        )
    with pytest.raises(ReadingError, match="keys must be strings"):
        Reading("bulk_price_tiers", AttributeLevel.OFFER, "observed", None, {1: 2})  # type: ignore[dict-item]
    with pytest.raises(ReadingError, match="not a JSON value"):
        Reading("bulk_price_tiers", AttributeLevel.OFFER, "observed", None, {"a": {1, 2}})  # type: ignore[dict-item]
    ok = Reading("price_minor", AttributeLevel.OFFER, "observed", "AED 189.00", Decimal("189.00"))
    assert ok.value == Decimal("189.00")


def test_capture_invariants(make_capture: Callable[..., ProductCapture]) -> None:
    with pytest.raises(ReadingError, match="timezone-aware"):
        make_capture(retrieved_at=datetime(2026, 10, 2))  # noqa: DTZ001
    with pytest.raises(ReadingError, match="SHA-256"):
        make_capture(page_sha256="ABC")
    with pytest.raises(ReadingError, match="must not be empty"):
        make_capture(retailer="")
    with pytest.raises(ValueError, match="locale"):
        make_capture(locale="english")
    with pytest.raises(ReadingError, match="unknown capture_state"):
        make_capture(capture_state="meh")
    r = Reading("gtin", AttributeLevel.VARIANT, "observed", "1")
    with pytest.raises(ReadingError, match="has no readings"):
        make_capture(capture_state="blocked", readings=(r,))
    with pytest.raises(ReadingError, match="duplicate reading"):
        make_capture(readings=(r, r))
    blocked = make_capture(capture_state="blocked")
    assert blocked.readings == ()
    shifted = make_capture(
        retrieved_at=datetime(2026, 10, 2, 13, 0, tzinfo=timezone(timedelta(hours=4)))
    )
    assert shifted.retrieved_at == datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
    assert shifted.page_sha256 == "a" * 64
    second = Reading("gtin", AttributeLevel.VARIANT, "observed", "2", None, "p")
    two = make_capture(readings=(r, second))
    assert len(two.by_key()["gtin"]) == 2


def test_json_decoding_refuses_floats_and_bad_decimals() -> None:
    with pytest.raises(ReadingError, match="float"):
        decode_value([1.5])
    with pytest.raises(ReadingError, match="bad decimal"):
        decode_value({"$decimal": "abc"})
    with pytest.raises(ReadingError, match="JSON object"):
        loads("[1]")
    with pytest.raises(ReadingError, match=r"untagged float 1\.5"):
        loads('{"source": "s", "rating": 1.5}')
    with pytest.raises(ReadingError, match="NaN is not accepted"):
        loads('{"source": NaN}')
    assert decode_value({"$decimal": "1.50"}) == Decimal("1.50")
    with pytest.raises(ReadingError, match="unescaped tag key"):
        decode_value({"$decimal": "1", "x": 2})
    assert decode_value({"$$decimal": "1", "x": 2}) == {"$decimal": "1", "x": 2}


def test_dumps_never_emits_floats_and_load_lines_skips_blanks(
    make_capture: Callable[..., ProductCapture],
) -> None:
    r = Reading("rating_value", AttributeLevel.COLOUR, "observed", "4.3", Decimal("4.3"))
    line = dumps(make_capture(readings=(r,)))
    assert '{"$decimal":"4.3"}' in line
    assert load_lines([line, "", "  \n", line]) == [loads(line), loads(line)]


def test_capture_from_json_defaults_capture_state(
    make_capture: Callable[..., ProductCapture],
) -> None:
    data = capture_to_json(make_capture())
    del data["capture_state"]
    del data["readings"]
    assert capture_from_json(data).capture_state == "ok"
    assert isinstance(capture_from_json(data), ProductCapture)
