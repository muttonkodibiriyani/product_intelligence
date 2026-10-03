"""Shared size-label reading used by every beauty extractor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pi_capture._size import Size, emit_size, read_size
from pi_capture.generic import _Emitter
from pi_capture.model import Reading


def _emit(label: str) -> dict[str, Reading]:
    em = _Emitter()
    emit_size(em, label, "test.path")
    return {r.key: r for r in em.readings}


@pytest.mark.parametrize(
    ("label", "value", "unit"),
    [
        ("50 ml", Decimal(50), "ml"),
        ("50ML", Decimal(50), "ml"),
        ("1.7 l", Decimal("1.7"), "l"),
        ("12,5 g", Decimal("12.5"), "g"),
        ("0,750 l", Decimal("0.750"), "l"),
        ("1,500 ml", Decimal(1500), "ml"),
        ("2 pcs", Decimal(2), "count"),
        ("٣ قطع", Decimal(3), "count"),  # Arabic-Indic digits read as digits
        ("30 مل", Decimal(30), "ml"),
    ],
)
def test_read_size_values(label: str, value: Decimal | None, unit: str | None) -> None:
    size = read_size(label)
    assert (size.value, size.unit) == (value, unit)


def test_a_thousands_comma_is_noted_and_ambiguous_with_litres_or_kilograms() -> None:
    assert read_size("1,500 ml") == Size(Decimal(1500), "ml", "comma read as a thousands separator")
    size = read_size("1,500 kg")
    assert (size.value, size.unit) == (None, "kg")
    assert size.value_note == "comma ambiguous with kg: 1,500 may be a decimal or a thousand"


def test_more_than_one_comma_is_neither_a_decimal_nor_a_thousand_and_keeps_the_unit() -> None:
    size = read_size("0,750,000 ml")
    assert (size.value, size.unit) == (None, "ml")
    assert size.value_note == "more than one comma: neither a decimal nor a thousand"
    r = _emit("0,750,000 ml")
    assert r["size_label"].value == "0,750,000 ml"
    assert (r["size_value"].state, r["size_value"].raw_text) == ("parse_failed", "0,750,000 ml")
    assert (r["size_unit"].state, r["size_unit"].value) == ("observed", "ml")


def test_an_unknown_unit_keeps_the_label_and_fails_both_parts() -> None:
    r = _emit("3 oz")
    assert r["size_label"].value == "3 oz"
    assert r["size_value"].state == "parse_failed"
    assert r["size_value"].note == "unit not normalised, value kept with the label"
    assert r["size_unit"].state == "parse_failed"
    assert r["size_unit"].note == "unit 'oz' outside ml|g|l|kg|count"


def test_a_label_without_a_leading_number_fails_both_parts() -> None:
    r = _emit("Travel size")
    assert r["size_label"].value == "Travel size"
    assert r["size_value"].note == "no leading number"
    assert r["size_unit"].note == "no unit after a number"
    assert {r["size_value"].state, r["size_unit"].state} == {"parse_failed"}


def test_emit_size_observes_value_and_unit_on_a_clean_label() -> None:
    r = _emit("1,500 ml")
    assert (r["size_value"].value, r["size_value"].note) == (
        Decimal(1500),
        "comma read as a thousands separator",
    )
    assert (r["size_unit"].value, r["size_unit"].note) == ("ml", None)
