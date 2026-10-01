"""Pair rows and the price-gap summary (design §6 ``POST /v1/compare``, §7.2, §7.4, §7.5).

A pair is two **contexts** (ADR-0008 §2). Contexts of different retailers need that retailer
pair's exact, approved or locked edge; two contexts of one retailer need the same
``evidence.itemKey`` on both offers and no edge. Sizes follow the symmetric rule in
``view.same_size``.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pi_core import MatchClass, ReviewState
from pi_dataset import ContractModel, DatasetV3, MoneyValue, ProductV3
from pi_dataset.models import RetailerStatus
from pi_metrics import view
from pi_metrics.model import (
    COUNTED_STATES,
    EVERY_PROFILE,
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Cheaper,
    Cohort,
    Excluded,
    Metric,
    Pct,
    ProductFilter,
    Reason,
    Status,
)

#: Shipped on every gap-bearing response so no client infers direction from a sign (§7.5).
GAP_CONVENTION = (
    "gapAmount = other - base; gapPct = (other - base) / base x 100. "
    "A positive gap means other is dearer than base; see cheaper."
)
COHORT_DESCRIPTION = "exact approved/locked pairs, same size, both priced, not early"
#: The profiles compare and the index apply to (ADR-0008 §3).
PROFILES = EVERY_PROFILE
#: The published size labels of a counted pair whose equal measures carry different labels.
LabelPair = tuple[str, str]


class Gap(ContractModel):
    amount: MoneyValue
    pct: Pct
    cheaper: Cheaper


class GroupBy(StrEnum):
    CATEGORY = "category"  # the top-level category slug in v1
    BRAND = "brand"


class PairRow(ContractModel):
    id: str
    name: str
    brand: str
    category: tuple[str, ...]
    base_price: MoneyValue | None
    other_price: MoneyValue | None
    gap: Gap | None
    counted: bool
    excluded_reason: Excluded | None


class Basket(ContractModel):
    base: MoneyValue
    other: MoneyValue


class CompareSummary(ContractModel):
    n: int
    median_gap_pct: Pct
    mean_gap_pct: Pct
    cheaper_counts: dict[str, int]
    equal_count: int
    basket: Basket


class Side(ContractModel):
    """One context's state in a comparison, so a client can say which side is short.

    ``retailer`` holds the context id: a retailer's sole context has the retailer's id.
    """

    retailer: str
    status: RetailerStatus
    reason: Reason | None
    #: Collected (non-early) offers priced on the date.
    observed: int
    #: Rows counted in the comparison (the same for both sides).
    counted: int
    #: Products offered here and not at the other retailer.
    only_here: int


class Sides(ContractModel):
    base: Side
    other: Side


class Group(ContractModel):
    """The summary for one ``groupBy`` key, with the cohort rule applied per group."""

    key: str
    n: int
    status: Status
    reason: Reason | None
    summary: CompareSummary | None


class Comparison(ContractModel):
    base: str
    other: str
    sides: Sides
    rows: tuple[PairRow, ...]
    summary: CompareSummary | None
    #: Rows before any ``limit``; ``truncated`` says the list was cut to it (pi_api).
    total: int
    truncated: bool = False
    group_by: GroupBy | None = None
    groups: tuple[Group, ...] = ()
    convention: str = GAP_CONVENTION


def gap(base: MoneyValue, other: MoneyValue) -> Gap:
    """Signed gap in one currency; the caller guarantees both are the same currency."""
    difference = other.decimal() - base.decimal()
    cheaper = (
        Cheaper.EQUAL if difference == 0 else Cheaper.BASE if difference > 0 else Cheaper.OTHER
    )
    return Gap(
        amount=MoneyValue.of(difference, base.currency),
        pct=difference / base.decimal() * 100,
        cheaper=cheaper,
    )


def _identity(  # noqa: PLR0911 -- one ordered decision ladder, first match wins
    ds: DatasetV3, product: ProductV3, base: str, other: str
) -> Excluded | None:
    """Why the two contexts' offers aren't known to be one item, or None (ADR-0008 §2)."""
    a_shop, b_shop = view.context(ds, base).retailer, view.context(ds, other).retailer
    if a_shop == b_shop:
        # One retailer: only its own stable item key groups contexts, with no edge.
        key = product.offers[base].evidence.item_key
        same = key is not None and key == product.offers[other].evidence.item_key
        return (
            None if same and not view.identity_unclear(ds, product, a_shop) else Excluded.NO_MATCH
        )
    if view.identity_unclear(ds, product, a_shop) or view.identity_unclear(ds, product, b_shop):
        return Excluded.NO_MATCH
    edge = view.edge_between(product, a_shop, b_shop)
    if edge is None:
        return Excluded.NO_MATCH
    if edge.review_state is ReviewState.REJECTED:
        return Excluded.MATCH_REJECTED
    if edge.review_state not in COUNTED_STATES:
        return Excluded.MATCH_UNREVIEWED
    if edge.match_class is not MatchClass.EXACT:
        return Excluded.MATCH_NOT_EXACT
    return None


def _exclusion(  # noqa: PLR0911 -- one ordered decision ladder, first match wins
    ds: DatasetV3, product: ProductV3, base: str, other: str, i: int
) -> tuple[Excluded | None, LabelPair | None]:
    """The first reason the pair is not counted on date ``i``, in a fixed order; else None.

    The second value is set on a counted pair whose equal measures carry different labels.
    """
    a, b = product.offers.get(base), product.offers.get(other)
    if a is None or b is None:
        return Excluded.NOT_OFFERED, None
    if a.early or b.early:
        return Excluded.EARLY, None
    if a.currency != b.currency:
        return Excluded.CURRENCY_MISMATCH, None
    identity = _identity(ds, product, base, other)
    if identity is not None:
        return identity, None
    size = view.same_size(a.size, b.size, labels_comparable=ds.meta.profile.size_labels_comparable)
    if size is view.SizeMatch.UNKNOWN:
        return Excluded.SIZE_UNKNOWN, None
    if size is view.SizeMatch.MISMATCH:
        return Excluded.SIZE_MISMATCH, None
    if a.series.price[i] is None or b.series.price[i] is None:
        return Excluded.UNPRICED, None
    if size is view.SizeMatch.LABELS_DIFFER and a.size and b.size and a.size.label and b.size.label:
        return None, (a.size.label, b.size.label)
    return None, None


def pair_with_labels(
    ds: DatasetV3, product: ProductV3, base: str, other: str, i: int
) -> tuple[PairRow, LabelPair | None]:
    """``pair_row`` plus, for a counted row, the size labels that differ on equal measures."""
    a, b = product.offers.get(base), product.offers.get(other)
    base_price = None if a is None else view.price_on(a, i)
    other_price = None if b is None else view.price_on(b, i)
    excluded, labels = _exclusion(ds, product, base, other, i)
    counted = excluded is None and base_price is not None and other_price is not None
    row = PairRow(
        id=product.id,
        name=product.name,
        brand=product.brand,
        category=product.category,
        base_price=base_price,
        other_price=other_price,
        gap=gap(base_price, other_price) if counted and base_price and other_price else None,
        counted=counted,
        excluded_reason=excluded,
    )
    return row, labels if counted else None


def pair_row(ds: DatasetV3, product: ProductV3, base: str, other: str, i: int) -> PairRow:
    """One product's row for an ordered context pair on date index ``i``.

    Only this pair's own edge (or, within one retailer, its own item key) makes it comparable;
    nothing is inferred through a third retailer or context.
    """
    return pair_with_labels(ds, product, base, other, i)[0]


def pair_caveats(ds: DatasetV3, base: str, other: str, labels: list[LabelPair]) -> list[Caveat]:
    """``channel_differs`` and one ``size_labels_differ`` per distinct label pair (ADR-0008)."""
    caveats = []
    channels = view.context(ds, base).channel, view.context(ds, other).channel
    if channels[0] != channels[1]:
        caveats.append(
            Caveat(
                code=CaveatCode.CHANNEL_DIFFERS,
                params={"base": str(channels[0]), "other": str(channels[1])},
            )
        )
    counts = Counter(labels)
    for (base_label, other_label), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        caveats.append(
            Caveat(
                code=CaveatCode.SIZE_LABELS_DIFFER,
                params={"base": base_label, "other": other_label, "count": str(n)},
            )
        )
    return caveats


def summarise(rows: tuple[PairRow, ...], base: str, other: str) -> CompareSummary | None:
    """Median/mean gap and basket over counted rows; ``None`` below the cohort minimum."""
    counted = [r for r in rows if r.gap is not None and r.base_price and r.other_price]
    if len(counted) < MIN_COHORT:
        return None
    # Sorted, so the inexact Decimal sum doesn't depend on row order.
    pcts = sorted(r.gap.pct for r in counted if r.gap is not None)
    currency = counted[0].base_price.currency if counted[0].base_price else ""
    base_total = sum((r.base_price.decimal() for r in counted if r.base_price), Decimal(0))
    other_total = sum((r.other_price.decimal() for r in counted if r.other_price), Decimal(0))
    cheapers = [r.gap.cheaper for r in counted if r.gap is not None]
    return CompareSummary(
        n=len(counted),
        median_gap_pct=statistics.median(pcts),
        mean_gap_pct=sum(pcts, Decimal(0)) / len(pcts),
        cheaper_counts={
            base: cheapers.count(Cheaper.BASE),
            other: cheapers.count(Cheaper.OTHER),
        },
        equal_count=cheapers.count(Cheaper.EQUAL),
        basket=Basket(
            base=MoneyValue.of(base_total, currency), other=MoneyValue.of(other_total, currency)
        ),
    )


def pair_block(ds: DatasetV3, base: str, other: str) -> Reason | None:
    """A reason no pair between the two contexts can be counted, whatever the rows."""
    statuses = {view.status(ds, c) for c in (base, other)}
    if RetailerStatus.BLOCKED in statuses:
        return Reason.RETAILER_BLOCKED
    shops = view.context(ds, base).retailer, view.context(ds, other).retailer
    if view.market_currency(ds, shops[0]) != view.market_currency(ds, shops[1]):
        return Reason.CURRENCY_MISMATCH
    return None


def _headline(
    ds: DatasetV3, rows: tuple[PairRow, ...], base: str, other: str, n: int
) -> Reason | None:
    return pair_block(ds, base, other) or _cohort_reason(rows, n)


def _cohort_reason(rows: tuple[PairRow, ...], n: int) -> Reason | None:
    if n >= MIN_COHORT:
        return None
    if n > 0:
        return Reason.COHORT_TOO_SMALL
    candidates = [
        r for r in rows if r.excluded_reason not in {Excluded.NOT_OFFERED, Excluded.EARLY}
    ]
    if all(r.excluded_reason is Excluded.NO_MATCH for r in candidates):
        return Reason.NO_MATCH
    reviewed = [
        r
        for r in candidates
        if r.excluded_reason not in {Excluded.NO_MATCH, Excluded.MATCH_UNREVIEWED}
    ]
    if not reviewed and any(r.excluded_reason is Excluded.MATCH_UNREVIEWED for r in candidates):
        return Reason.MATCHES_UNREVIEWED
    return Reason.COHORT_TOO_SMALL


def _side(  # noqa: PLR0913 -- one side of the pair plus the shared rows and products
    ds: DatasetV3,
    retailer: str,
    other: str,
    *,
    rows: tuple[PairRow, ...],
    offered: list[ProductV3],
    i: int,
) -> Side:
    status = view.status(ds, retailer)
    observed = sum(
        1
        for p in offered
        if (o := view.collected(p, retailer)) is not None and view.price_on(o, i) is not None
    )
    return Side(
        retailer=retailer,
        status=status,
        reason={
            RetailerStatus.BLOCKED: Reason.RETAILER_BLOCKED,
            RetailerStatus.PARTIAL: Reason.RETAILER_PARTIAL,
        }.get(status),
        observed=observed,
        counted=sum(r.counted for r in rows),
        only_here=sum(1 for p in offered if retailer in p.offers and other not in p.offers),
    )


def group_key(row: PairRow, by: GroupBy) -> str:
    return row.brand if by is GroupBy.BRAND else row.category[0]


def _groups(
    rows: tuple[PairRow, ...], base: str, other: str, by: GroupBy, blocked: Reason | None
) -> tuple[Group, ...]:
    buckets: defaultdict[str, list[PairRow]] = defaultdict(list)
    for row in rows:
        buckets[group_key(row, by)].append(row)
    groups = []
    for key in sorted(buckets):
        members = tuple(buckets[key])
        n = sum(r.counted for r in members)
        reason = blocked or _cohort_reason(members, n)
        groups.append(
            Group(
                key=key,
                n=n,
                status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
                reason=reason,
                summary=None if reason else summarise(members, base, other),
            )
        )
    return tuple(groups)


def compare(  # noqa: PLR0913 -- the endpoint's filters; date and grouping are keyword-only
    dataset: view.AnyDataset,
    base: str,
    other: str,
    where: ProductFilter,
    *,
    on: date | None = None,
    group_by: GroupBy | None = None,
) -> Metric[Comparison]:
    """Rows for every product either context offers, plus the summary when n ≥ 5 (§7.4).

    ``base`` and ``other`` are context ids. ``group_by`` adds one summary per brand or top-level
    category, each under its own n ≥ 5 rule. The summary and groups always cover every row, never
    a page of them.
    """
    ds = view.as_v3(dataset)
    if base == other:
        msg = "base and other must be different retailers"
        raise view.UnknownInput(msg)
    view.context(ds, base)
    view.context(ds, other)
    i = view.date_index(ds, on)
    offered = [p for p in view.products(ds, where) if base in p.offers or other in p.offers]
    if not view.applies(ds, PROFILES):
        return _not_applicable(ds, base, other, offered, i)
    pairs = [pair_with_labels(ds, p, base, other, i) for p in offered]
    rows = tuple(row for row, _ in pairs)
    n = sum(r.counted for r in rows)
    reason = _headline(ds, rows, base, other, n)
    summary = summarise(rows, base, other) if reason is None else None
    # A blocked side or a currency mismatch withholds every group; the cohort rule is per group.
    blocked = pair_block(ds, base, other)
    groups = () if group_by is None else _groups(rows, base, other, group_by, blocked)
    caveats = [
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": c})
        for c in (base, other)
        if view.status(ds, c) is RetailerStatus.PARTIAL
    ]
    early = sum(r.excluded_reason is Excluded.EARLY for r in rows)
    if early:
        caveats.append(Caveat(code=CaveatCode.EARLY_EXCLUDED, params={"count": str(early)}))
    caveats += pair_caveats(ds, base, other, [labels for _, labels in pairs if labels])
    return Metric[Comparison](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=Comparison(
            base=base,
            other=other,
            sides=Sides(
                base=_side(ds, base, other, rows=rows, offered=offered, i=i),
                other=_side(ds, other, base, rows=rows, offered=offered, i=i),
            ),
            rows=rows,
            summary=summary,
            total=len(rows),
            group_by=group_by,
            groups=groups,
        ),
        reason=reason,
        cohort=Cohort(description=COHORT_DESCRIPTION, n=n),
        caveats=tuple(caveats),
        as_of=ds.meta.dates[i],
    )


def _not_applicable(
    ds: DatasetV3, base: str, other: str, offered: list[ProductV3], i: int
) -> Metric[Comparison]:
    """No rows and no summary; the sides still say what each context collected."""
    return Metric[Comparison](
        status=Status.NOT_ENOUGH_DATA,
        data=Comparison(
            base=base,
            other=other,
            sides=Sides(
                base=_side(ds, base, other, rows=(), offered=offered, i=i),
                other=_side(ds, other, base, rows=(), offered=offered, i=i),
            ),
            rows=(),
            summary=None,
            total=0,
        ),
        reason=Reason.NOT_APPLICABLE,
        as_of=ds.meta.dates[i],
    )
