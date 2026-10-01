"""Rule-based price position and reprice suggestions (docs/design/price-suggestions.md).

**Rule-based, not ML.** Every output carries ``label = "rule-based, not ML"``. The rules only
place an observed price against observed peer prices and, if asked, move it towards a target
band within guardrails. Nothing here estimates demand, volume, revenue, elasticity or uplift
(ANL-16, UAT-31), and no output has a field that could hold one.

* **Peers.** One value per collected offer priced on the date, in the subject's market
  currency, excluding the subject product itself. ``PeerScope.MARKET`` (the default) takes every
  context in the market; ``PeerScope.COMPETITORS`` drops the subject's own retailer.
* **Cohorts.** ``category``: peers whose leaf category equals the subject's. ``brand``: peers of
  the subject's brand within its top-level category (a brand median across unrelated categories
  says nothing). Matching uses ``view.fold``.
* **Basis.** Unit price (price / pack measure) when the subject has a measure and at least
  ``MIN_COHORT`` peers share its unit; otherwise ticket price over same-size peers
  (``view.same_size``). Peers that fit neither are reported as ``excluded``, never guessed.
* **Bands.** p25 / median / p75 by linear interpolation between closest ranks, in ``Decimal``.
  ``entry`` is below p25, ``premium`` above p75, ``mid`` is p25..p75 inclusive. A cohort under
  ``MIN_COHORT`` has no band: ``not_enough_data`` / ``cohort_too_small``.
* **Suggestion.** Aim at the nearest edge of the target band (or its median, ``Aim.MEDIAN``,
  for ``mid``), move only towards it, clamp to ``max_change_pct``, round to an allowed price
  ending inside the clamp, and suggest nothing below ``min_change_pct``. Prefer a price that
  lands in the band; otherwise the allowed price that gets closest (``reaches_band = false``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field

from pi_core.money import CURRENCY_EXPONENTS
from pi_dataset import ContractModel, DatasetV3, MoneyValue, ProductV3
from pi_metrics import view
from pi_metrics.model import EVERY_PROFILE, MIN_COHORT, Cohort, Metric, Pct, Reason, Status

RULE_LABEL: Final = "rule-based, not ML"
#: Pricing applies to every profile; a menu item or a garment has a price like a cream does.
PROFILES = EVERY_PROFILE
#: Unit prices are carried exactly; this is only the wire rendering (4 dp, e.g. per ml).
UNIT_PLACES = 4

Label = Literal["rule-based, not ML"]


class Band(StrEnum):
    ENTRY = "entry"
    MID = "mid"
    PREMIUM = "premium"


class CohortScope(StrEnum):
    CATEGORY = "category"
    BRAND = "brand"


class PeerScope(StrEnum):
    MARKET = "market"
    COMPETITORS = "competitors"


class Basis(StrEnum):
    UNIT_PRICE = "unit_price"
    TICKET_PRICE = "ticket_price"


class Aim(StrEnum):
    EDGE = "edge"
    MEDIAN = "median"


class Ending(StrEnum):
    """Allowed price endings. ``x9`` is a whole amount ending in 9 (49.00, 129.00)."""

    WHOLE = ".00"
    HALF = ".50"
    NINE = "x9.00"


class Outcome(StrEnum):
    SUGGESTED = "suggested"
    ALREADY_IN_BAND = "already_in_band"
    BELOW_MIN_CHANGE = "below_min_change"
    NO_ALLOWED_PRICE = "no_allowed_price"


class RationaleCode(StrEnum):
    CURRENT_BAND = "current_band"
    TARGET = "target"
    CLAMPED = "clamped"
    ROUNDED = "rounded"
    REACHES_BAND = "reaches_band"
    SHORT_OF_BAND = "short_of_band"
    BELOW_MIN_CHANGE = "below_min_change"
    NO_ALLOWED_PRICE = "no_allowed_price"


class Rationale(ContractModel):
    """One step of the reasoning; ``params`` are strings and numbers stay digits (design §5)."""

    code: RationaleCode
    params: dict[str, str]


class Guardrails(ContractModel):
    max_change_pct: Decimal = Field(default=Decimal(10), gt=0, le=50)
    min_change_pct: Decimal = Field(default=Decimal(1), ge=0)
    endings: tuple[Ending, ...] = Field(
        default=(Ending.WHOLE, Ending.HALF, Ending.NINE), min_length=1
    )


class BandStats(ContractModel):
    """A cohort's band thresholds on one basis (``Decimal``; unit prices are quotients)."""

    n: int
    p25: Decimal
    median: Decimal
    p75: Decimal


class CohortPosition(ContractModel):
    label: Label = RULE_LABEL
    scope: CohortScope
    #: The folded category leaf, or ``"<brand> / <top category>"``.
    key: str
    basis: Basis | None
    #: Peers priced on the date that fit the basis (the cohort n).
    n: int
    #: Peers priced on the date that fit neither basis (no measure in the unit, other size).
    excluded: int
    p25: str | None
    median: str | None
    p75: str | None
    #: The subject's value on the basis, at the same precision as the thresholds.
    value: str | None
    band: Band | None
    vs_median_pct: Pct | None
    reason: Reason | None


class PricePosition(ContractModel):
    label: Label = RULE_LABEL
    product: str
    context: str
    price: MoneyValue | None
    peers: PeerScope
    cohorts: tuple[CohortPosition, ...]


class PriceSuggestion(ContractModel):
    label: Label = RULE_LABEL
    product: str
    context: str
    cohort: CohortScope
    target_band: Band
    current: MoneyValue | None
    suggested: MoneyValue | None
    change_pct: Pct | None
    reaches_band: bool
    outcome: Outcome | None
    rationale: tuple[Rationale, ...]
    guardrails: Guardrails


# ---- pure rules ----------------------------------------------------------------------------


def percentile(sorted_values: Sequence[Decimal], p: Decimal) -> Decimal:
    """Linear interpolation between closest ranks (Hyndman-Fan type 7)."""
    if not sorted_values:
        msg = "percentile of an empty cohort"
        raise ValueError(msg)
    h = (len(sorted_values) - 1) * p
    lo = math.floor(h)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (h - lo) * (sorted_values[hi] - sorted_values[lo])


def band_stats(values: Sequence[Decimal]) -> BandStats | None:
    """p25 / median / p75, or ``None`` under ``MIN_COHORT`` members."""
    if len(values) < MIN_COHORT:
        return None
    ordered = sorted(values)
    return BandStats(
        n=len(ordered),
        p25=percentile(ordered, Decimal("0.25")),
        median=percentile(ordered, Decimal("0.5")),
        p75=percentile(ordered, Decimal("0.75")),
    )


_ORDER = (Band.ENTRY, Band.MID, Band.PREMIUM)


def band_of(value: Decimal, stats: BandStats) -> Band:
    if value < stats.p25:
        return Band.ENTRY
    if value > stats.p75:
        return Band.PREMIUM
    return Band.MID


def scaled(stats: BandStats, factor: Decimal) -> BandStats:
    """Thresholds in ticket-price terms for a subject whose unit price is ``price / factor``."""
    return BandStats(
        n=stats.n, p25=stats.p25 * factor, median=stats.median * factor, p75=stats.p75 * factor
    )


def _grid(ending: Ending, near: Decimal) -> tuple[Decimal, ...]:
    """The allowed prices with ``ending`` around ``near``: two below it and two above it.

    ``near`` itself counts on both sides when it is on the grid. The extra step matters when a
    band edge is an allowed price: ``entry`` is strictly below p25 and ``premium`` strictly above
    p75, so the best landing price is the step past the edge, not the edge.
    """
    step, offset = {
        Ending.WHOLE: (Decimal(1), Decimal(0)),
        Ending.HALF: (Decimal(1), Decimal("0.5")),
        Ending.NINE: (Decimal(10), Decimal(9)),
    }[ending]
    k = math.floor((near - offset) / step)
    below = offset + k * step
    above = below if below == near else below + step
    return below - step, below, above, above + step


def allowed_prices(
    low: Decimal, high: Decimal, near: Decimal, endings: Sequence[Ending]
) -> list[Decimal]:
    """Allowed-ending prices in ``[low, high]`` next to ``near``, which may lie outside."""
    anchors = {min(max(near, low), high), low, high}
    found = {
        price
        for ending in endings
        for anchor in anchors
        for price in _grid(ending, anchor)
        if low <= price <= high and price > 0
    }
    return sorted(found)


def in_band(price: Decimal, band: Band, stats: BandStats) -> bool:
    return band_of(price, stats) is band


def aim_point(current: Band, target: Band, stats: BandStats, aim: Aim) -> Decimal:
    """The nearest edge of ``target`` seen from ``current``, or the median for ``mid``."""
    if target is Band.ENTRY:
        return stats.p25
    if target is Band.PREMIUM:
        return stats.p75
    if aim is Aim.MEDIAN:
        return stats.median
    return stats.p25 if current is Band.ENTRY else stats.p75


def _pct(change: Decimal, base: Decimal) -> Decimal:
    return change / base * 100


def suggest_price(  # noqa: PLR0913 -- the rule's inputs, all keyword
    current: Decimal,
    *,
    stats: BandStats,
    target: Band,
    guardrails: Guardrails,
    aim: Aim = Aim.EDGE,
    currency: str = "AED",
) -> tuple[Outcome, Decimal | None, bool, list[Rationale]]:
    """The reprice rule on ticket-price thresholds. Returns outcome, price, reaches_band, steps."""
    current_band = band_of(current, stats)
    steps = [Rationale(code=RationaleCode.CURRENT_BAND, params={"band": current_band.value})]
    if current_band is target:
        return Outcome.ALREADY_IN_BAND, None, True, steps
    point = aim_point(current_band, target, stats, aim)
    steps.append(
        Rationale(
            code=RationaleCode.TARGET,
            params={"band": target.value, "aim": aim.value, "point": _money_text(point, currency)},
        )
    )
    # The band order, not the point, says which way to move: the point can equal the price.
    up = _ORDER.index(target) > _ORDER.index(current_band)
    limit = current * guardrails.max_change_pct / 100
    low, high = (current, current + limit) if up else (current - limit, current)
    if (up and point > high) or (not up and point < low):
        steps.append(
            Rationale(
                code=RationaleCode.CLAMPED,
                params={"maxChangePct": _pct_text(guardrails.max_change_pct)},
            )
        )
    exponent = CURRENCY_EXPONENTS[currency]
    candidates = [
        price
        for price in allowed_prices(low, high, point, guardrails.endings)
        if price != current and price == price.quantize(Decimal(1).scaleb(-exponent))
    ]
    if not candidates:
        steps.append(Rationale(code=RationaleCode.NO_ALLOWED_PRICE, params={}))
        return Outcome.NO_ALLOWED_PRICE, None, False, steps
    landing = [price for price in candidates if in_band(price, target, stats)]
    pool = landing or candidates
    chosen = min(pool, key=lambda price: (abs(price - point), price))
    change = abs(_pct(chosen - current, current))
    if change < guardrails.min_change_pct:
        steps.append(
            Rationale(
                code=RationaleCode.BELOW_MIN_CHANGE,
                params={
                    "changePct": _pct_text(change),
                    "minChangePct": _pct_text(guardrails.min_change_pct),
                },
            )
        )
        return Outcome.BELOW_MIN_CHANGE, None, False, steps
    steps.append(
        Rationale(
            code=RationaleCode.ROUNDED,
            params={"price": _money_text(chosen, currency), "endings": _endings(guardrails)},
        )
    )
    reaches = bool(landing)
    steps.append(
        Rationale(
            code=RationaleCode.REACHES_BAND if reaches else RationaleCode.SHORT_OF_BAND,
            params={"band": target.value},
        )
    )
    return Outcome.SUGGESTED, chosen, reaches, steps


def _money_text(value: Decimal, currency: str) -> str:
    exponent = CURRENCY_EXPONENTS[currency]
    return str(value.quantize(Decimal(1).scaleb(-exponent)))


def _pct_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1")))


def _endings(guardrails: Guardrails) -> str:
    return ",".join(e.value for e in guardrails.endings)


# ---- dataset adapter -----------------------------------------------------------------------

#: One peer value: the product, the context id and its price on the date.
_Row = tuple[ProductV3, str, Decimal]


@dataclass(frozen=True, slots=True)
class _Subject:
    ds: DatasetV3
    product: ProductV3
    context_id: str
    i: int
    currency: str
    price: MoneyValue | None

    @classmethod
    def resolve(
        cls, dataset: view.AnyDataset, product_id: str, context_id: str, on: date | None
    ) -> _Subject:
        ds = view.as_v3(dataset)
        retailer = view.context(ds, context_id).retailer
        i = view.date_index(ds, on)
        product = next((p for p in ds.products if p.id == product_id), None)
        if product is None:
            msg = f"unknown product {product_id!r}"
            raise view.UnknownInput(msg)
        currency = view.market_currency(ds, retailer)
        offer = view.collected(product, context_id)
        price = None if offer is None else view.price_on(offer, i)
        if price is not None and price.currency != currency:
            price = None
        return cls(ds, product, context_id, i, currency, price)

    @property
    def as_of(self) -> date:
        return self.ds.meta.dates[self.i]

    def peers(self, scope: PeerScope) -> list[_Row]:
        """Every other product's collected offer priced on the date in the market currency."""
        ds = self.ds
        own = view.context(ds, self.context_id).retailer
        market = ds.market_of(own)
        rows = []
        for product in ds.products:
            if product.id == self.product.id:
                continue
            for cid in product.offers:
                retailer = view.context(ds, cid).retailer
                if ds.market_of(retailer) != market:
                    continue
                if scope is PeerScope.COMPETITORS and retailer == own:
                    continue
                offer = view.collected(product, cid)
                price = None if offer is None else view.price_on(offer, self.i)
                if price is not None and price.currency == self.currency:
                    rows.append((product, cid, price.decimal()))
        return rows

    def members(self, rows: list[_Row], scope: CohortScope) -> tuple[str, list[_Row]]:
        leaf, top = view.fold(self.product.category[-1]), view.fold(self.product.category[0])
        if scope is CohortScope.CATEGORY:
            return leaf, [r for r in rows if view.fold(r[0].category[-1]) == leaf]
        brand = view.fold(self.product.brand)
        return f"{brand} / {top}", [
            r for r in rows if view.fold(r[0].brand) == brand and view.fold(r[0].category[0]) == top
        ]

    def basis(self, members: list[_Row]) -> tuple[Basis | None, list[Decimal], Decimal]:
        """The cohort's basis, its values and the subject's scale (pack measure, or 1)."""
        mine = _measure(self.product, self.context_id)
        if mine is not None:
            unit_values = []
            for product, cid, price in members:
                theirs = _measure(product, cid)
                if theirs is not None and theirs[1] == mine[1]:
                    unit_values.append(price / theirs[0])
            if len(unit_values) >= MIN_COHORT:
                return Basis.UNIT_PRICE, unit_values, mine[0]
        size = self.product.offers[self.context_id].size
        comparable = self.ds.meta.profile.size_labels_comparable
        same = [
            price
            for product, cid, price in members
            if view.same_size(size, product.offers[cid].size, labels_comparable=comparable)
            in {view.SizeMatch.EQUAL, view.SizeMatch.LABELS_DIFFER}
        ]
        return (Basis.TICKET_PRICE if same else None), same, Decimal(1)

    def cohort(
        self, rows: list[_Row], scope: CohortScope
    ) -> tuple[CohortPosition, BandStats | None, Decimal]:
        key, members = self.members(rows, scope)
        empty = CohortPosition(
            scope=scope,
            key=key,
            basis=None,
            n=0,
            excluded=len(members),
            p25=None,
            median=None,
            p75=None,
            value=None,
            band=None,
            vs_median_pct=None,
            reason=Reason.NOT_IN_SCOPE,
        )
        if self.price is None:
            return empty, None, Decimal(1)
        basis, values, factor = self.basis(members)
        stats = band_stats(values)
        counts = {"basis": basis, "n": len(values), "excluded": len(members) - len(values)}
        if stats is None:
            update = counts | {"reason": Reason.COHORT_TOO_SMALL}
            return empty.model_copy(update=update), None, factor
        places = UNIT_PLACES if basis is Basis.UNIT_PRICE else CURRENCY_EXPONENTS[self.currency]
        quantum = Decimal(1).scaleb(-places)
        value = self.price.decimal() / factor
        position = empty.model_copy(
            update=counts
            | {
                "p25": str(stats.p25.quantize(quantum)),
                "median": str(stats.median.quantize(quantum)),
                "p75": str(stats.p75.quantize(quantum)),
                "value": str(value.quantize(quantum)),
                "band": band_of(value, stats),
                "vs_median_pct": _pct(value - stats.median, stats.median),
                "reason": None,
            }
        )
        return position, stats, factor

    def reason(self, has_band: bool) -> Reason | None:
        if not view.applies(self.ds, PROFILES):
            return Reason.NOT_APPLICABLE
        if self.price is None:
            return Reason.NOT_IN_SCOPE
        return None if has_band else Reason.COHORT_TOO_SMALL


def _measure(product: ProductV3, cid: str) -> tuple[Decimal, str] | None:
    size = product.offers[cid].size
    if size is None or size.value is None or size.unit is None:
        return None
    return Decimal(size.value), view.fold(size.unit)


def _described(scope: str, position: CohortPosition) -> Cohort:
    basis = position.basis.value if position.basis else "no"
    return Cohort(
        description=f"{RULE_LABEL}: {scope} cohort {position.key!r}, {basis} basis, "
        "market offers priced on the date",
        n=position.n,
    )


def price_position(
    dataset: view.AnyDataset,
    product_id: str,
    context_id: str,
    *,
    peers: PeerScope = PeerScope.MARKET,
    on: date | None = None,
) -> Metric[PricePosition]:
    """The subject offer's place in its category and brand cohorts on the date."""
    subject = _Subject.resolve(dataset, product_id, context_id, on)
    rows = subject.peers(peers)
    cohorts = tuple(subject.cohort(rows, scope)[0] for scope in CohortScope)
    reason = subject.reason(any(c.band is not None for c in cohorts))
    return Metric[PricePosition](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=PricePosition(
            product=product_id,
            context=context_id,
            price=subject.price,
            peers=peers,
            cohorts=cohorts,
        ),
        reason=reason,
        cohort=_described(CohortScope.CATEGORY.value, cohorts[0]),
        as_of=subject.as_of,
    )


def price_suggestion(  # noqa: PLR0913 -- the rule's knobs, all keyword
    dataset: view.AnyDataset,
    product_id: str,
    context_id: str,
    target: Band,
    *,
    cohort: CohortScope = CohortScope.CATEGORY,
    guardrails: Guardrails | None = None,
    aim: Aim = Aim.EDGE,
    peers: PeerScope = PeerScope.MARKET,
    on: date | None = None,
) -> Metric[PriceSuggestion]:
    """A reprice towards ``target`` in one cohort, within ``guardrails``. Never a forecast."""
    rails = guardrails or Guardrails()
    subject = _Subject.resolve(dataset, product_id, context_id, on)
    position, stats, factor = subject.cohort(subject.peers(peers), cohort)
    reason = subject.reason(stats is not None)
    blank = PriceSuggestion(
        product=product_id,
        context=context_id,
        cohort=cohort,
        target_band=target,
        current=subject.price,
        suggested=None,
        change_pct=None,
        reaches_band=False,
        outcome=None,
        rationale=(),
        guardrails=rails,
    )
    summary = _described(cohort.value, position)
    if reason is not None or subject.price is None or stats is None:
        return Metric[PriceSuggestion](
            status=Status.NOT_ENOUGH_DATA,
            data=blank,
            reason=reason,
            cohort=summary,
            as_of=subject.as_of,
        )
    current = subject.price.decimal()
    outcome, chosen, reaches, steps = suggest_price(
        current,
        stats=scaled(stats, factor),
        target=target,
        guardrails=rails,
        aim=aim,
        currency=subject.currency,
    )
    return Metric[PriceSuggestion](
        status=Status.OK,
        data=blank.model_copy(
            update={
                "suggested": None if chosen is None else MoneyValue.of(chosen, subject.currency),
                "change_pct": None if chosen is None else _pct(chosen - current, current),
                "reaches_band": reaches,
                "outcome": outcome,
                "rationale": tuple(steps),
            }
        ),
        cohort=summary,
        as_of=subject.as_of,
    )
