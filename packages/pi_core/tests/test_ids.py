from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from pi_core import content_hash_of, logical_key
from pi_core.types import Amount, Size

parts = st.lists(st.one_of(st.none(), st.text(), st.integers(), st.uuids()), max_size=4)


@given(st.text(), parts)
def test_logical_key_is_deterministic(kind: str, values: list[object]) -> None:
    assert logical_key(kind, *values) == logical_key(kind, *values)


@given(st.text(), st.text())
def test_part_boundaries_cannot_collide(a: str, b: str) -> None:
    # "ab" + "" must not equal "a" + "b": parts are length-prefixed.
    if b:
        assert logical_key("k", a, b) != logical_key("k", a + b, "")


def test_none_differs_from_empty_string() -> None:
    assert logical_key("k", None) != logical_key("k", "")
    assert logical_key("k", None) != logical_key("k", "-")


@given(st.integers(min_value=-14, max_value=14))
def test_same_instant_same_id_in_any_offset(hours: int) -> None:
    instant = datetime(2026, 9, 30, 12, tzinfo=UTC)
    shifted = instant.astimezone(timezone(timedelta(hours=hours)))
    assert logical_key("k", instant) == logical_key("k", shifted)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        logical_key("k", datetime(2026, 1, 1))  # noqa: DTZ001


def test_id_is_pinned() -> None:
    # Guards the encoding: changing either would re-key all stored history.
    assert logical_key("offer_observation", 1, 5, None) == (
        "264dfd9eb188d8120ec68bfd35bf71bfc43a6af083bb42f6d5b181c5b22cd6c2"
    )


def test_content_hash() -> None:
    assert content_hash_of(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


amount = TypeAdapter(Amount)
size = TypeAdapter(Size)


@pytest.mark.parametrize("value", ["12.5", 12, Decimal("0.0001"), "-3", "99999999999999.9999"])
def test_amount_accepts_exact_values(value: object) -> None:
    assert amount.validate_python(value) == Decimal(str(value))


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (1.5, "float is not accepted"),
        (True, "bool is not accepted"),
        ("1.23456", "more than 4 decimal places"),
        ("100000000000000", "does not fit"),
        ("1E+40", "does not fit"),
        ("Infinity", "finite"),
        ("NaN", "finite"),
    ],
)
def test_amount_rejects(value: object, error: str) -> None:
    with pytest.raises((ValidationError, TypeError), match=error):
        amount.validate_python(value)


def test_amount_json_round_trip_keeps_precision() -> None:
    value = amount.validate_python("1.250")
    assert amount.validate_json(amount.dump_json(value)).as_tuple() == value.as_tuple()


def test_amount_json_number_is_refused() -> None:
    with pytest.raises((ValidationError, TypeError), match="float"):
        amount.validate_json("1.5")


def test_size_rejects_float_and_non_positive() -> None:
    assert size.validate_python("50") == Decimal(50)
    with pytest.raises((ValidationError, TypeError)):
        size.validate_python(50.0)
    with pytest.raises(ValidationError):
        size.validate_python("0")
