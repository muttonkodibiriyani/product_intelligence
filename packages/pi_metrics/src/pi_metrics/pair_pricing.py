"""Rule-based pair price suggestions: where a subject retailer can beat a rival on price.

**Rule-based, not ML.** The cohort rules in ``pi_metrics.pricing`` place one offer against
market peers; this module works on **matched pairs**: the same item at a subject context (the
retailer being advised) and a rival context. It reuses ``compare``'s pair ladder and
``pricing``'s guardrails and allowed price endings, and adds no demand, volume, revenue, margin,
elasticity or uplift field (ANL-16, UAT-31).

* **Eligible pair.** ``compare``'s ladder: both offered, not early, one currency, the pair's
  own edge exact and approved or locked, the same size. A pair whose sides are a blocked
  retailer, a retailer that is not ``supported``, or two market currencies gives no suggestion
  at all (the row says why).
* **Observed prices.** Each side's price is its price on the last date its context was
  collected, on or before the as-of date. A side whose observation is more than ``STALE_DAYS``
  old is ``stale_observation``. The one exemption is a **subject** whose source is a one-off
  import (``imported``): it is served as that import's snapshot, with ``basis =
  imported_snapshot``, ``observedOn`` = the import date and its age in days. A rival is never
  exempt, so nothing is ever advised against a stale rival.
* **Rule (down only).** ``aim = beat`` wants a price strictly below the rival's, ``aim = match``
  one at or below it. A subject already there is ``already_competitive`` (the gap is still
  returned as data, never as advice to raise). Otherwise: cut at most ``maxChangePct``, at least
  ``minChangePct``, to an allowed ending; the highest such price that meets the aim, or, if the
  clamp stops short, the lowest allowed price in the clamp (``reachesRival = false``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pi_core import MatchClass, ReviewState
from pi_core.money import CURRENCY_EXPONENTS
from pi_dataset import ContractModel, DatasetV3, MoneyValue, ProductV3
from pi_dataset.models import RetailerStatus
from pi_dataset.text import SourceText
from pi_metrics import view
from pi_metrics.compare import Gap, _exclusion, gap
from pi_metrics.model import (
    EVERY_PROFILE,
    Cohort,
    Excluded,
    Metric,
    Pct,
    ProductFilter,
    Reason,
    Status,
)
from pi_metrics.pricing import (
    RULE_LABEL,
    Guardrails,
    Label,
    _endings,
    _money_text,
    _pct,
    _pct_text,
    allowed_prices,
)

#: A crawled side observed more than this many days before the as-of date is stale.
STALE_DAYS: Final = 7
PROFILES = EVERY_PROFILE
COHORT_DESCRIPTION: Final = (
    f"{RULE_LABEL}: exact approved/locked pairs, same size, both priced, rival observed within "
    f"{STALE_DAYS} days, supported retailers"
)


class PairAim(StrEnum):
    BEAT = "beat"
    MATCH = "match"


class PairOutcome(StrEnum):
    SUGGESTED = "suggested"
    ALREADY_COMPETITIVE = "already_competitive"
    BELOW_MIN_CHANGE = "below_min_change"
    NO_ALLOWED_PRICE = "no_allowed_price"


class NoSuggestion(StrEnum):
    """Why a row has no outcome. Every such row carries exactly one."""

    NOT_OFFERED = "not_offered"
    EARLY = "early"
    NO_MATCH = "no_match"
    MATCH_REJECTED = "match_rejected"
    MATCH_UNREVIEWED = "match_unreviewed"
    MATCH_NOT_EXACT = "match_not_exact"
    UNPRICED = "unpriced"
    CURRENCY_MISMATCH = "currency_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    SIZE_UNKNOWN = "size_unknown"
    STALE_OBSERVATION = "stale_observation"
    NOT_OBSERVED = "not_observed"
    RETAILER_BLOCKED = "retailer_blocked"
    RETAILER_PARTIAL = "retailer_partial"


class PairRationaleCode(StrEnum):
    CURRENT_GAP = "current_gap"
    ALREADY_COMPETITIVE = "already_competitive"
    TARGET = "target"
    CLAMPED = "clamped"
    ROUNDED = "rounded"
    BEATS_RIVAL = "beats_rival"
    MATCHES_RIVAL = "matches_rival"
    SHORT_OF_RIVAL = "short_of_rival"
    BELOW_MIN_CHANGE = "below_min_change"
    NO_ALLOWED_PRICE = "no_allowed_price"


class PairRationale(ContractModel):
    """One step of the reasoning; ``params`` are strings and numbers stay digits."""

    code: PairRationaleCode
    params: dict[str, str]


class SideBasis(StrEnum):
    #: Observed by collection on ``observedOn``.
    OBSERVED = "observed"
    #: A one-off import's snapshot; ``observedOn`` is the import date (subject side only).
    IMPORTED_SNAPSHOT = "imported_snapshot"


class PairSide(ContractModel):
    """One side of a pair. ``age_days`` is the as-of date minus ``observed_on``; an import's
    local day can fall after the view's last date, so a snapshot's age can be negative."""

    context: str
    price: MoneyValue | None
    observed_on: date | None
    age_days: int | None
    basis: SideBasis | None


class PairMatch(ContractModel):
    match_class: MatchClass
    review_state: ReviewState
    confidence: str | None


class SuggestionRow(ContractModel):
    id: str
    name: SourceText
    brand: SourceText
    category: tuple[SourceText, ...]
    subject: PairSide
    rival: PairSide
    match: PairMatch | None
    #: rival - subject, in percent of the subject price; data, never advice to raise.
    gap: Gap | None
    outcome: PairOutcome | None
    suggested: MoneyValue | None
    change_pct: Pct | None
    reaches_rival: bool
    reason: NoSuggestion | None
    rationale: tuple[PairRationale, ...]


class PriceSuggestions(ContractModel):
    label: Label = RULE_LABEL
    subject: str
    rival: str
    aim: PairAim
    guardrails: Guardrails
    stale_days: int = STALE_DAYS
    rows: tuple[SuggestionRow, ...]
    total: int
    truncated: bool = False
    #: Rows per outcome and per no-suggestion reason, over every row (never a page).
    outcomes: dict[str, int]
    reasons: dict[str, int]


# ---- pure rule -------------------------------------------------------------------------------


def undercut(
    current: Decimal,
    rival: Decimal,
    *,
    aim: PairAim,
    guardrails: Guardrails,
    currency: str,
) -> tuple[PairOutcome, Decimal | None, bool, list[PairRationale]]:
    """The down-only pair rule. Returns outcome, price, reaches_rival and the steps."""

    def meets(price: Decimal) -> bool:
        return price < rival if aim is PairAim.BEAT else price <= rival

    steps = [
        PairRationale(
            code=PairRationaleCode.CURRENT_GAP,
            params={
                "subject": _money_text(current, currency),
                "rival": _money_text(rival, currency),
                "gapPct": _pct_text(_pct(rival - current, current)),
            },
        )
    ]
    if meets(current):
        steps.append(
            PairRationale(code=PairRationaleCode.ALREADY_COMPETITIVE, params={"aim": aim.value})
        )
        return PairOutcome.ALREADY_COMPETITIVE, None, True, steps
    steps.append(
        PairRationale(
            code=PairRationaleCode.TARGET,
            params={"aim": aim.value, "point": _money_text(rival, currency)},
        )
    )
    low = current - current * guardrails.max_change_pct / 100
    if not meets(low):
        steps.append(
            PairRationale(
                code=PairRationaleCode.CLAMPED,
                params={"maxChangePct": _pct_text(guardrails.max_change_pct)},
            )
        )
    quantum = Decimal(1).scaleb(-CURRENCY_EXPONENTS[currency])

    def allowed(high: Decimal, near: Decimal) -> list[Decimal]:
        return [
            p
            for p in allowed_prices(low, high, near, guardrails.endings)
            if p != current and p == p.quantize(quantum)
        ]

    if not allowed(current, rival):
        steps.append(PairRationale(code=PairRationaleCode.NO_ALLOWED_PRICE, params={}))
        return PairOutcome.NO_ALLOWED_PRICE, None, False, steps
    # Only prices at least minChangePct below the current one; anchored at the rival (or at the
    # cap when the rival is above it) so the highest allowed price that meets the aim is found.
    cap = current - current * guardrails.min_change_pct / 100
    big = allowed(cap, min(rival, cap)) if cap >= low else []
    if not big:
        steps.append(
            PairRationale(
                code=PairRationaleCode.BELOW_MIN_CHANGE,
                params={"minChangePct": _pct_text(guardrails.min_change_pct)},
            )
        )
        return PairOutcome.BELOW_MIN_CHANGE, None, False, steps
    landing = [p for p in big if meets(p)]
    chosen = max(landing) if landing else min(big)
    steps.append(
        PairRationale(
            code=PairRationaleCode.ROUNDED,
            params={"price": _money_text(chosen, currency), "endings": _endings(guardrails)},
        )
    )
    if landing:
        code = (
            PairRationaleCode.BEATS_RIVAL
            if aim is PairAim.BEAT
            else PairRationaleCode.MATCHES_RIVAL
        )
    else:
        code = PairRationaleCode.SHORT_OF_RIVAL
    steps.append(PairRationale(code=code, params={"rival": _money_text(rival, currency)}))
    return PairOutcome.SUGGESTED, chosen, bool(landing), steps


# ---- dataset adapter -------------------------------------------------------------------------


def _last_collected(ds: DatasetV3, context_id: str, i: int) -> int | None:
    """The last date index on or before ``i`` on which any offer of the context was seen."""
    found: int | None = None
    for product in ds.products:
        offer = product.offers.get(context_id)
        if offer is None:
            continue
        for j in range(i, -1 if found is None else found, -1):
            if view.seen(offer, j):
                found = j
                break
        if found == i:
            return i
    return found


def _last_priced(product: ProductV3, context_id: str, i: int) -> int | None:
    offer = product.offers[context_id]
    return next((j for j in range(i, -1, -1) if offer.series.price[j] is not None), None)


def _pair_block(
    ds: DatasetV3, subject: str, rival: str, imported: Mapping[str, date]
) -> NoSuggestion | None:
    """A reason no row between the two contexts gets a suggestion, whatever the rows."""
    statuses = {c: view.status(ds, c) for c in (subject, rival)}
    if RetailerStatus.BLOCKED in statuses.values():
        return NoSuggestion.RETAILER_BLOCKED
    # An imported subject is a snapshot, not a crawl: its collection status doesn't apply.
    crawled = [c for c in (subject, rival) if not (c == subject and c in imported)]
    if any(statuses[c] is not RetailerStatus.SUPPORTED for c in crawled):
        return NoSuggestion.RETAILER_PARTIAL
    shops = view.context(ds, subject).retailer, view.context(ds, rival).retailer
    if view.market_currency(ds, shops[0]) != view.market_currency(ds, shops[1]):
        return NoSuggestion.CURRENCY_MISMATCH
    return None


class _Pair:
    """The two contexts on the as-of date, with each side's last collection date."""

    def __init__(
        self, ds: DatasetV3, subject: str, rival: str, i: int, imported: Mapping[str, date]
    ) -> None:
        self.ds, self.subject, self.rival, self.i = ds, subject, rival, i
        self.as_of = ds.meta.dates[i]
        self.import_date = imported.get(subject)
        self.rival_imported = rival in imported
        self.collected = {c: _last_collected(ds, c, i) for c in (subject, rival)}

    def side(self, product: ProductV3, cid: str) -> tuple[PairSide, int | None]:
        """The side as served, and the date index its price is read at (None: no price)."""
        offer = product.offers.get(cid)
        blank = PairSide(context=cid, price=None, observed_on=None, age_days=None, basis=None)
        if offer is None:
            return blank, None
        if cid == self.subject and self.import_date is not None:
            j = _last_priced(product, cid, self.i)
            on: date | None = self.import_date
            basis = SideBasis.IMPORTED_SNAPSHOT
        else:
            j = self.collected[cid]
            on = None if j is None else self.ds.meta.dates[j]
            basis = SideBasis.OBSERVED
        price = None if j is None else view.price_on(offer, j)
        if price is None or on is None:
            return blank, None
        age = (self.as_of - on).days
        return PairSide(context=cid, price=price, observed_on=on, age_days=age, basis=basis), j

    def row(
        self, product: ProductV3, aim: PairAim, rails: Guardrails, block: NoSuggestion | None
    ) -> SuggestionRow:
        subject, js = self.side(product, self.subject)
        rival, jr = self.side(product, self.rival)
        edge = view.edge_between(
            product,
            view.context(self.ds, self.subject).retailer,
            view.context(self.ds, self.rival).retailer,
        )
        reason = block or self._reason(product, subject, rival, js, jr)
        both = subject.price is not None and rival.price is not None
        same_currency = both and subject.price.currency == rival.price.currency  # type: ignore[union-attr]
        row = SuggestionRow(
            id=product.id,
            name=product.name,
            brand=product.brand,
            category=product.category,
            subject=subject,
            rival=rival,
            match=None
            if edge is None
            else PairMatch(
                match_class=edge.match_class,
                review_state=edge.review_state,
                confidence=edge.confidence,
            ),
            gap=gap(subject.price, rival.price)  # type: ignore[arg-type]
            if reason is None and same_currency
            else None,
            outcome=None,
            suggested=None,
            change_pct=None,
            reaches_rival=False,
            reason=reason,
            rationale=(),
        )
        if reason is not None or subject.price is None or rival.price is None:
            return row
        current, currency = subject.price.decimal(), subject.price.currency
        outcome, chosen, reaches, steps = undercut(
            current, rival.price.decimal(), aim=aim, guardrails=rails, currency=currency
        )
        return row.model_copy(
            update={
                "outcome": outcome,
                "suggested": None if chosen is None else MoneyValue.of(chosen, currency),
                "change_pct": None if chosen is None else _pct(chosen - current, current),
                "reaches_rival": reaches,
                "rationale": tuple(steps),
            }
        )

    def _reason(
        self,
        product: ProductV3,
        subject: PairSide,
        rival: PairSide,
        js: int | None,
        jr: int | None,
    ) -> NoSuggestion | None:
        excluded, _ = _exclusion(self.ds, product, self.subject, self.rival, self.i)
        # compare's ladder reads both prices on one date; here each side has its own.
        if excluded is not None and excluded is not Excluded.UNPRICED:
            return NoSuggestion(excluded.value)
        if js is None or jr is None:
            return NoSuggestion.UNPRICED
        if self.rival_imported or (rival.age_days or 0) > STALE_DAYS:
            return NoSuggestion.STALE_OBSERVATION
        if subject.basis is SideBasis.OBSERVED and (subject.age_days or 0) > STALE_DAYS:
            return NoSuggestion.STALE_OBSERVATION
        if view.not_observed(self.ds, self.rival, product, jr) or (
            subject.basis is SideBasis.OBSERVED
            and view.not_observed(self.ds, self.subject, product, js)
        ):
            return NoSuggestion.NOT_OBSERVED
        return None


def _envelope_reason(block: NoSuggestion | None, n: int, rival_imported: bool) -> Reason | None:
    """The metric's own reason: a pair block, an imported rival (never collected by PI, so
    every row is ``stale_observation``), or no eligible row at all."""
    if block is not None:
        return Reason(block.value)
    if n:
        return None
    return Reason.RETAILER_PARTIAL if rival_imported else Reason.NO_MATCH


_RANK = {
    PairOutcome.SUGGESTED: 0,
    PairOutcome.ALREADY_COMPETITIVE: 1,
    PairOutcome.BELOW_MIN_CHANGE: 2,
    PairOutcome.NO_ALLOWED_PRICE: 3,
}


def _order(row: SuggestionRow) -> tuple[int, Decimal, str]:
    """Suggestions first, the subject's largest overprice (most negative gap) first; then id."""
    rank = 4 if row.outcome is None else _RANK[row.outcome]
    return rank, row.gap.pct if row.gap else Decimal(0), row.id


def _counts(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def price_suggestions(  # noqa: PLR0913 -- the endpoint's inputs; the knobs are keyword-only
    dataset: view.AnyDataset,
    subject: str,
    rival: str,
    where: ProductFilter,
    *,
    on: date | None = None,
    aim: PairAim = PairAim.BEAT,
    guardrails: Guardrails | None = None,
    imported: Mapping[str, date] | None = None,
) -> Metric[PriceSuggestions]:
    """One row per product the subject offers, ordered by ``_order``; never a forecast.

    ``subject`` and ``rival`` are context ids of two different retailers. ``imported`` maps the
    context ids served from a one-off import to the import's local date.
    """
    ds = view.as_v3(dataset)
    rails = guardrails or Guardrails()
    shops = view.context(ds, subject).retailer, view.context(ds, rival).retailer
    if shops[0] == shops[1]:
        msg = "subject and rival must be contexts of different retailers"
        raise view.UnknownInput(msg)
    i = view.date_index(ds, on)
    imports = dict(imported or {})
    offered = [p for p in view.products(ds, where) if subject in p.offers]
    block = _pair_block(ds, subject, rival, imports)
    if not view.applies(ds, PROFILES):
        rows: tuple[SuggestionRow, ...] = ()
        reason: Reason | None = Reason.NOT_APPLICABLE
    else:
        pair = _Pair(ds, subject, rival, i, imports)
        rows = tuple(sorted((pair.row(p, aim, rails, block) for p in offered), key=_order))
        n = sum(r.outcome is not None for r in rows)
        reason = _envelope_reason(block, n, rival in imports)
    return Metric[PriceSuggestions](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=PriceSuggestions(
            subject=subject,
            rival=rival,
            aim=aim,
            guardrails=rails,
            rows=rows,
            total=len(rows),
            outcomes=_counts([r.outcome.value for r in rows if r.outcome is not None]),
            reasons=_counts([r.reason.value for r in rows if r.reason is not None]),
        ),
        reason=reason,
        cohort=Cohort(description=COHORT_DESCRIPTION, n=sum(r.outcome is not None for r in rows)),
        as_of=ds.meta.dates[i],
    )
