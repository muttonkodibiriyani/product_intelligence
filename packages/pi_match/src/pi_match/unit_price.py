"""Price per 100 ml, per 100 g or per unit, derived from a price and a published size.

Pure functions: no I/O, no source names. Derivation refuses rather than guesses: a missing or
ambiguous size, a multi-pack (the per-item size is not the pack size) and a size that is both a
volume or mass and a piece count all give None.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from pi_match.normalise import Size, is_listed, list_groups, parse_size

#: Unit prices are rounded half-even to this quantum; callers round further for display.
UNIT_PRICE_Q = Decimal("0.0001")
#: Volume and mass are quoted per 100 base units (the usual shelf-label basis).
PER = Decimal(100)

_PACK_RES = (
    re.compile(r"(?<![\w.])(\d+)\s*[x\u00d7]\s*\d", re.IGNORECASE),  # "2 x 50 ml", "3x15ml"
    re.compile(r"\b(?:pack|set|box) of (\d+)\b", re.IGNORECASE),
    re.compile(r"\b(\d+)[\s-]*(?:pack|pk)\b", re.IGNORECASE),
)
_PACK_WORDS = re.compile(r"\b(duo|trio)\b", re.IGNORECASE)
_COUNT_RE = re.compile(
    r"(?<![\w.])(\d+)\s*(?:pcs?|pieces?|capsules?|sheets?|wipes?|pads?|patches|count|ct)\b",
    re.IGNORECASE,
)


class Basis(StrEnum):
    """What a unit price is quoted per."""

    PER_100_ML = "100ml"
    PER_100_G = "100g"
    PER_UNIT = "unit"


@dataclass(frozen=True, slots=True)
class BasePrice:
    """A price per ``basis``, in the currency of the price it came from."""

    amount: Decimal
    basis: Basis


def pack_count(text: str | None) -> int | None:
    """The item count of a multi-pack in ``text`` ("2 x 50 ml", "pack of 3"), else None.

    A list (see ``list_groups``) is read item by item; any item naming a pack counts.
    """
    for item in _texts(text):
        for pattern in _PACK_RES:
            match = pattern.search(item)
            if match is not None:
                return int(match.group(1))
        word = _PACK_WORDS.search(item)
        if word is not None:
            return 2 if word.group(1).lower() == "duo" else 3
    return None


def parse_count(text: str | None) -> int | None:
    """A piece count written in ``text`` ("60 capsules", "30 pcs"), else None. Several: None."""
    counts = {int(m.group(1)) for item in _texts(text) for m in _COUNT_RE.finditer(item)}
    return counts.pop() if len(counts) == 1 else None


def price_per_base(
    price: Decimal | None,
    size: Size | None = None,
    *,
    count: int | None = None,
    pack: int | None = None,
) -> BasePrice | None:
    """``price`` per 100 ml / 100 g (from ``size``) or per unit (from ``count``), else None.

    None when the price is missing or not positive, ``pack`` is more than one item, both a size and
    a count are given (which one is the price per?), or neither is.
    """
    if price is None or price <= 0 or (pack is not None and pack != 1):
        return None
    if size is not None and count is not None:
        return None
    if size is not None and size.amount > 0:
        basis = Basis.PER_100_ML if size.unit == "ml" else Basis.PER_100_G
        return BasePrice(_q(price * PER / size.amount), basis)
    if count is not None and count > 0:
        return BasePrice(_q(price / count), Basis.PER_UNIT)
    return None


def derive_unit_price(price: Decimal | None, size_text: str | None) -> BasePrice | None:
    """``price_per_base`` from a published size label, parsed here.

    The label gives a size (``parse_size``: an ambiguous list gives none) or a piece count; both
    at once, or a multi-pack, give None.
    """
    size, count = parse_size(size_text), parse_count(size_text)
    return price_per_base(price, size, count=count, pack=pack_count(size_text))


def _texts(text: str | None) -> tuple[str, ...]:
    if not text:
        return ()
    if not is_listed(text):
        return (text,)
    return tuple(item for group in list_groups(text) or () for item in group)


def _q(value: Decimal) -> Decimal:
    return value.quantize(UNIT_PRICE_Q, rounding=ROUND_HALF_EVEN)
