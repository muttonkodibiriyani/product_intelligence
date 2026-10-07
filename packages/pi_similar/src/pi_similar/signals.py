"""The per-pair signals and how they combine (design: docs/design/similar-products.md §3.2).

Each signal is a ``Decimal`` in ``[0, 1]`` or ``None`` (absent). An absent signal is never
imputed: the score is a weighted mean over the present ones only.
"""

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pi_match.unit_price import Basis
from pi_similar.items import Department, Item

ONE = Decimal(1)
HALF = Decimal("0.5")
ZERO = Decimal(0)
PLACES = Decimal("0.0001")


class Signal(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    PRICE = "price"
    ATTRIBUTES = "attributes"


#: Bump ``WEIGHTS_VERSION`` (and add a decision-log row) whenever a weight or rule here changes.
WEIGHTS_VERSION = "2026-10-06.1"
WEIGHTS: Mapping[Signal, Decimal] = {
    Signal.TEXT: Decimal("0.4"),
    Signal.IMAGE: Decimal("0.3"),
    Signal.PRICE: Decimal("0.2"),
    Signal.ATTRIBUTES: Decimal("0.1"),
}
#: A pair is emitted only with at least this many present signals, one of them text or image.
MIN_SIGNALS = 2
#: Price bands per (department, basis, currency): quintiles over every retailer's items.
BANDS = 5

Signals = Mapping[Signal, Decimal | None]
BandKey = tuple[Department | None, Basis, str]


def q(value: Decimal) -> Decimal:
    """Four decimal places, the precision every score is published at."""
    return value.quantize(PLACES)


def cosine(value: float) -> Decimal:
    """A cosine of unit vectors as a ``[0, 1]`` signal; an opposite direction is 0, not negative."""
    return q(min(ONE, max(ZERO, Decimal(repr(float(value))))))


def combine(signals: Signals) -> Decimal | None:
    """The weighted mean over the present signals, or None when the pair can't be emitted."""
    present = {name: value for name, value in signals.items() if value is not None}
    if len(present) < MIN_SIGNALS or not ({Signal.TEXT, Signal.IMAGE} & present.keys()):
        return None
    total = sum((WEIGHTS[name] for name in present), ZERO)
    return q(sum((WEIGHTS[name] * value for name, value in present.items()), ZERO) / total)


@dataclass(frozen=True, slots=True)
class PriceBands:
    """Band edges per (department, basis, currency), shared by every retailer."""

    edges: Mapping[BandKey, tuple[Decimal, ...]]

    @classmethod
    def of(cls, found: Iterable[Item]) -> "PriceBands":
        amounts: defaultdict[BandKey, list[Decimal]] = defaultdict(list)
        for it in found:
            if it.unit_price is not None:
                key = (it.department, it.unit_price.basis, it.currency)
                amounts[key].append(it.unit_price.amount)
        edges: dict[BandKey, tuple[Decimal, ...]] = {}
        for key, values in amounts.items():
            if len(values) < BANDS:
                continue  # too few prices for bands: the price signal stays absent
            ordered = sorted(values)
            edges[key] = tuple(ordered[len(ordered) * i // BANDS] for i in range(1, BANDS))
        return cls(edges)

    def band(self, it: Item) -> int | None:
        if it.unit_price is None:
            return None
        edges = self.edges.get((it.department, it.unit_price.basis, it.currency))
        return None if edges is None else bisect_right(edges, it.unit_price.amount)


def price(a: Item, b: Item, bands: PriceBands) -> tuple[Decimal | None, str | None]:
    """Same band 1, adjacent 0.5, else 0; absent unless both are priced on the same basis."""
    if a.unit_price is None or b.unit_price is None or a.currency != b.currency:
        return None, None
    if a.unit_price.basis is not b.unit_price.basis:
        return None, None
    band_a, band_b = bands.band(a), bands.band(b)
    if band_a is None or band_b is None:
        return None, None
    gap = abs(band_a - band_b)
    if gap == 0:
        return ONE, "price_band:same"
    if gap == 1:
        return HALF, "price_band:adjacent"
    return ZERO, "price_band:far"


class ConflictError(Exception):
    """Two known attributes that differ: the pair is not a competitor at all."""


def attributes(a: Item, b: Item) -> tuple[Decimal | None, tuple[str, ...]]:
    """Agreement over form, concentration and gender: known on both sides and equal 1, otherwise
    0.5. Absent unless at least one is known on both sides. Raises ``ConflictError`` on a mismatch.
    """
    pairs = (
        ("form", a.form, b.form),
        ("concentration", a.concentration, b.concentration),
        ("gender", a.gender, b.gender),
    )
    scores: list[Decimal] = []
    reasons: list[str] = []
    for name, left, right in pairs:
        if left is not None and right is not None:
            if left != right:
                raise ConflictError(name)
            scores.append(ONE)
            reasons.append(f"same_{name}:{left}")
        else:
            scores.append(HALF)
            if left is not None or right is not None:
                reasons.append(f"{name}_unknown_one_side")
    if ONE not in scores:
        return None, tuple(reasons)
    return q(sum(scores, ZERO) / len(scores)), tuple(reasons)
