"""Pack-size labels ("30 ml", "1,000 g", "0,750 l") read into a number and a unit.

Shared by the retailer extractors so every shop's size reads the same way: a comma followed by
exactly three digits after a non-zero lead is a thousands separator, any other comma is a decimal
comma, and a thousands-shaped comma beside litres or kilograms is ambiguous (1,500 l may be 1.5 l
or 1500 l) and is refused rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from pi_capture.generic import _Emitter

__all__ = ["Size", "emit_size", "read_size"]

_SIZE = re.compile(r"^(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:[.,]\d+)?)\s*(?P<unit>[^\d\s].*?)$")
_THOUSANDS = re.compile(r"^[1-9]\d{0,2}(?:,\d{3})+$")  # 1,000 is a thousand; 0,750 is not
_AMBIGUOUS_THOUSANDS_UNITS: Final = frozenset({"l", "kg"})  # 1,500 l may be 1.5 l or 1500 l
_UNITS: Final[dict[str, str]] = {
    "ml": "ml",
    "g": "g",
    "gm": "g",
    "gr": "g",
    "l": "l",
    "kg": "kg",
    "pcs": "count",
    "pc": "count",
    "pieces": "count",
    "piece": "count",
    "مل": "ml",
    "جم": "g",
    "غ": "g",
    "لتر": "l",
    "كجم": "kg",
    "قطعة": "count",
    "قطع": "count",
}


@dataclass(frozen=True, slots=True)
class Size:
    """What a label said. A ``None`` value or unit carries its reason in the matching note."""

    value: Decimal | None
    unit: str | None
    value_note: str | None = None
    unit_note: str | None = None


def read_size(label: str) -> Size:
    """Read ``label`` without guessing; the notes say why a part could not be read."""
    m = _SIZE.match(label)
    if m is None:
        return Size(None, None, "no leading number", "no unit after a number")
    unit = _UNITS.get(m.group("unit").strip().lower().rstrip("."))
    if unit is None:
        return Size(
            None,
            None,
            "unit not normalised, value kept with the label",
            f"unit {m.group('unit')!r} outside ml|g|l|kg|count",
        )
    num = m.group("num")
    note: str | None = None
    if _THOUSANDS.match(num):
        num, note = num.replace(",", ""), "comma read as a thousands separator"
    else:
        num = num.replace(",", ".")
    try:
        value = Decimal(num)
    except InvalidOperation:
        # "0,750,000 ml": a leading zero group with more than one comma is neither reading
        return Size(None, unit, "more than one comma: neither a decimal nor a thousand", None)
    if note is not None and unit in _AMBIGUOUS_THOUSANDS_UNITS:
        reason = f"comma ambiguous with {unit}: {m.group('num')} may be a decimal or a thousand"
        return Size(None, unit, reason, None)
    return Size(value, unit, note, None)


def emit_size(em: _Emitter, label: str, path: str) -> None:
    """``size_label`` as shown, then ``size_value`` and ``size_unit`` observed or parse_failed."""
    em.observed("size_label", label, label, path)
    size = read_size(label)
    if size.value is None:
        em.failed("size_value", label, path, size.value_note or "could not read size")
    else:
        em.observed("size_value", label, size.value, path, size.value_note)
    if size.unit is None:
        em.failed("size_unit", label, path, size.unit_note or "could not read unit")
    else:
        em.observed("size_unit", label, size.unit, path)
