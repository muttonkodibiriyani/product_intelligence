"""Category-to-category prices across two full catalogues (``GET /v1/category-compare``).

No matching: every product a context prices on the latest date counts in its category, placed by
``taxonomy`` at the requested level. Each (category, context) cell carries n and the price
ladder, or ``tooFew`` below ``MIN_COHORT``, never a zero. The per-category gap compares the two
medians, so it describes the categories as stocked, not like-for-like items (that is
``/compare``). Latest date only: there is no trend here.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from pi_dataset import ContractModel, DatasetV3, MoneyValue, ProductV3
from pi_dataset.models import RetailerStatus
from pi_metrics import view
from pi_metrics.compare import Gap, gap, pair_block, pair_caveats
from pi_metrics.model import (
    BEAUTY,
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Cohort,
    Metric,
    Pct,
    Reason,
    Status,
)
from pi_metrics.summary import _mean, _rank, _sorted
from pi_metrics.taxonomy import (
    BUCKETS,
    TAXONOMY_VERSION,
    Label,
    Level,
    Placement,
    Unmapped,
    label,
    place,
)

#: Shipped on every response so no client infers direction from a sign.
CATEGORY_GAP_CONVENTION = (
    "gap compares the two cells' medians: gapAmount = other median - base median; "
    "gapPct = (other median - base median) / base median x 100. A positive gap means the other "
    "retailer's median is higher (dearer) than the base's; see cheaper. A category-level gap "
    "reflects each retailer's range in the category, not like-for-like items."
)
COHORT_DESCRIPTION = (
    "categories with at least MIN_COHORT products priced on the latest date at both retailers"
)
#: The taxonomy is beauty's (ADR-0008 §3); any other profile answers ``not_applicable``.
PROFILES = frozenset({BEAUTY})
#: At most this many unmapped breadcrumbs are listed, the most frequent first.
UNMAPPED_CAP = 50


class Cell(ContractModel):
    """One context's prices in one category. Below ``MIN_COHORT`` only ``n`` is served."""

    retailer: str
    n: int
    too_few: bool
    reason: Reason | None
    median: MoneyValue | None
    mean: MoneyValue | None
    p25: MoneyValue | None
    p75: MoneyValue | None
    min: MoneyValue | None
    max: MoneyValue | None


class CategoryRow(ContractModel):
    key: str
    label: Label
    base: Cell
    other: Cell
    #: Both contexts price at least one product in the category.
    shared: bool
    gap: Gap | None
    #: Why ``gap`` is null: ``cohort_too_small`` (a cell is ``tooFew``), ``retailer_blocked``,
    #: ``currency_mismatch``.
    gap_reason: Reason | None


class UnmappedPath(ContractModel):
    """A breadcrumb taxonomy@1 doesn't place at ``common``, so the next rule can be written."""

    retailer: str
    path: tuple[str, ...]
    reason: Unmapped
    n: int


class Coverage(ContractModel):
    retailer: str
    #: Products priced on the latest date. At ``level=bucket`` this side's cells sum to it; at
    #: ``level=common`` they sum to ``mapped``.
    priced: int
    #: Of ``priced``, those taxonomy@1 places at ``common`` level.
    mapped: int
    #: ``priced - mapped``: of these, ``noBreadcrumb`` have only the exporter's code (all of them
    #: on today's file), the rest have a breadcrumb no rule places.
    unmapped: int
    no_breadcrumb: int
    #: Of ``priced``, those in the ``other`` bucket, and their share.
    other_bucket: int
    other_pct: Pct | None


class CoverageSides(ContractModel):
    base: Coverage
    other: Coverage


class CategoryComparison(ContractModel):
    base: str
    other: str
    level: Level
    taxonomy: str = TAXONOMY_VERSION
    #: The thin threshold: a cell with fewer products is ``tooFew``.
    min_cohort: int = MIN_COHORT
    #: Largest ``min(base.n, other.n)`` first, then the larger total, then the key. At
    #: ``level=bucket`` all nine buckets are rows, an empty one with ``n = 0`` (``tooFew``).
    rows: tuple[CategoryRow, ...]
    coverage: CoverageSides
    #: The most frequent unmapped breadcrumbs (at most ``UNMAPPED_CAP``); ``unmappedPaths`` counts
    #: every distinct one. Products with no breadcrumb are one entry per side with ``path: []``.
    #: Each path is the retailer's text verbatim: render it as plain text, never as HTML or
    #: markdown.
    unmapped: tuple[UnmappedPath, ...]
    unmapped_paths: int
    convention: str = CATEGORY_GAP_CONVENTION


def _priced(ds: DatasetV3, context: str, i: int) -> tuple[list[tuple[ProductV3, MoneyValue]], int]:
    """The context's products priced on date ``i`` in its market currency, and the early offers
    it saw that day: as ``summary._scan``, an offer not seen on ``i`` is in neither."""
    currency = view.market_currency(ds, view.context(ds, context).retailer)
    priced, early = [], 0
    for product in ds.products:
        offer = product.offers.get(context)
        if offer is None or not view.seen(offer, i):
            continue
        if offer.early:
            early += 1
            continue
        price = view.price_on(offer, i)
        if price is not None and price.currency == currency:
            priced.append((product, price))
    return priced, early


def _cell(context: str, prices: list[MoneyValue], blocked: bool) -> Cell:
    n = len(prices)
    reason = (
        Reason.RETAILER_BLOCKED if blocked else Reason.COHORT_TOO_SMALL if n < MIN_COHORT else None
    )
    if reason is not None:
        return Cell(
            retailer=context,
            n=n,
            too_few=n < MIN_COHORT,
            reason=reason,
            median=None,
            mean=None,
            p25=None,
            p75=None,
            min=None,
            max=None,
        )
    s = _sorted(prices)
    return Cell(
        retailer=context,
        n=n,
        too_few=False,
        reason=None,
        median=_rank(s, 50),
        mean=_mean(s),
        p25=_rank(s, 25),
        p75=_rank(s, 75),
        min=s[0],
        max=s[-1],
    )


def _key(placement: Placement, level: Level) -> str | None:
    return placement.bucket if level is Level.BUCKET else placement.common


def _coverage(context: str, placed: list[tuple[Placement, MoneyValue]]) -> Coverage:
    priced = len(placed)
    mapped = sum(p.common is not None for p, _ in placed)
    other = sum(p.bucket == "other" for p, _ in placed)
    return Coverage(
        retailer=context,
        priced=priced,
        mapped=mapped,
        unmapped=priced - mapped,
        no_breadcrumb=sum(p.unmapped is Unmapped.NO_BREADCRUMB for p, _ in placed),
        other_bucket=other,
        other_pct=Decimal(other) / priced * 100 if priced else None,
    )


def _row(
    key: str,
    level: Level,
    cells: tuple[Cell, Cell],
    blocked: Reason | None,
) -> CategoryRow:
    base, other = cells
    if blocked is not None:
        gap_reason: Reason | None = blocked
    elif base.median is None or other.median is None:
        gap_reason = Reason.COHORT_TOO_SMALL
    else:
        gap_reason = None
    return CategoryRow(
        key=key,
        label=label(level, key),
        base=base,
        other=other,
        shared=base.n > 0 and other.n > 0,
        gap=None
        if base.median is None or other.median is None or gap_reason
        else gap(base.median, other.median),
        gap_reason=gap_reason,
    )


def category_compare(
    dataset: view.AnyDataset, base: str, other: str, level: Level
) -> Metric[CategoryComparison]:
    """Every category either context prices on the latest date, both sides' ladders and the
    median gap; ``base`` and ``other`` are context ids."""
    ds = view.as_v3(dataset)
    if base == other:
        msg = "base and other must be different retailers or contexts"
        raise view.UnknownInput(msg)
    i = view.date_index(ds, None)
    sides = (base, other)
    for context in sides:
        view.context(ds, context)
    priced = {c: _priced(ds, c, i) for c in sides}
    placed = {c: [(place(p), price) for p, price in priced[c][0]] for c in sides}
    coverage = CoverageSides(
        base=_coverage(base, placed[base]), other=_coverage(other, placed[other])
    )
    unmapped = Counter(
        (c, product.category[1:], placement.unmapped)
        for c in sides
        for (product, _), (placement, _) in zip(priced[c][0], placed[c], strict=True)
        if placement.unmapped is not None
    )
    ranked = sorted(unmapped.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1], kv[0][2]))
    unmapped_paths = tuple(
        UnmappedPath(retailer=c, path=path, reason=reason, n=n)
        for (c, path, reason), n in ranked[:UNMAPPED_CAP]
    )
    if not view.applies(ds, PROFILES):
        return Metric[CategoryComparison](
            status=Status.NOT_ENOUGH_DATA,
            data=CategoryComparison(
                base=base,
                other=other,
                level=level,
                rows=(),
                coverage=coverage,
                unmapped=(),
                unmapped_paths=0,
            ),
            reason=Reason.NOT_APPLICABLE,
            as_of=ds.meta.dates[i],
        )
    by_key: defaultdict[str, dict[str, list[MoneyValue]]] = defaultdict(
        lambda: {base: [], other: []}
    )
    if level is Level.BUCKET:  # every bucket, an empty one too: a stable grid for clients
        for code in BUCKETS:
            by_key[code] = {base: [], other: []}
    for context in sides:
        for placement, price in placed[context]:
            key = _key(placement, level)
            if key is not None:
                by_key[key][context].append(price)
    blocked = pair_block(ds, base, other)
    blocked_side = {c: view.status(ds, c) is RetailerStatus.BLOCKED for c in sides}
    rows = [
        _row(
            key,
            level,
            (
                _cell(base, prices[base], blocked_side[base]),
                _cell(other, prices[other], blocked_side[other]),
            ),
            blocked,
        )
        for key, prices in by_key.items()
    ]
    rows.sort(key=lambda r: (-min(r.base.n, r.other.n), -(r.base.n + r.other.n), r.key))
    compared = sum(r.gap is not None for r in rows)
    reason = None if compared else blocked or _empty_reason(coverage, level)
    return Metric[CategoryComparison](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=CategoryComparison(
            base=base,
            other=other,
            level=level,
            rows=tuple(rows),
            coverage=coverage,
            unmapped=unmapped_paths,
            unmapped_paths=len(unmapped),
        ),
        reason=reason,
        cohort=Cohort(description=COHORT_DESCRIPTION, n=compared),
        caveats=_caveats(ds, sides, priced, coverage, level),
        as_of=ds.meta.dates[i],
    )


def _empty_reason(coverage: CoverageSides, level: Level) -> Reason:
    """Why no category compares: no breadcrumb to read at ``common`` (today's served file), else
    too few products."""
    sides = (coverage.base, coverage.other)
    if level is Level.COMMON and all(s.priced and s.no_breadcrumb == s.priced for s in sides):
        return Reason.FIELD_NOT_COLLECTED
    return Reason.COHORT_TOO_SMALL


def _caveats(
    ds: DatasetV3,
    sides: tuple[str, str],
    priced: dict[str, tuple[list[tuple[ProductV3, MoneyValue]], int]],
    coverage: CoverageSides,
    level: Level,
) -> tuple[Caveat, ...]:
    caveats = [
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": c})
        for c in sides
        if view.status(ds, c) is RetailerStatus.PARTIAL
    ]
    early = sum(priced[c][1] for c in sides)
    if early:
        caveats.append(Caveat(code=CaveatCode.EARLY_EXCLUDED, params={"count": str(early)}))
    caveats += pair_caveats(ds, *sides, [])
    if level is Level.COMMON:
        for side in (coverage.base, coverage.other):
            if side.no_breadcrumb:
                caveats.append(
                    Caveat(
                        code=CaveatCode.BREADCRUMB_MISSING,
                        params={"retailer": side.retailer, "count": str(side.no_breadcrumb)},
                    )
                )
            if ruled := side.unmapped - side.no_breadcrumb:
                caveats.append(
                    Caveat(
                        code=CaveatCode.UNMAPPED_CATEGORY,
                        params={"retailer": side.retailer, "count": str(ruled)},
                    )
                )
    return tuple(caveats)
