"""Per-brand assortment gaps of one focus retailer against every other (lane D, ADR-0012).

The unit is a listing: one product (one size) at one retailer. A focus listing is a collected
offer of the focus retailer observed on the date. What links it to another retailer ``r`` is,
strongest first:

* ``both``: an ``approved`` or ``locked`` exact edge to a collected ``r`` offer of the same product.
  Only these are presence at ``r`` (``both_by``).
* ``unconfirmed``: any other evidence of the same item at ``r``: a proposed exact edge, an exact
  edge to an early sample, an ``r`` offer grouped without an edge or with an unclear identity, or
  an exact edge the match file names between two products the view did not merge.
* ``family``: a family or size-normalized edge (same product, another size or shade). Never
  ``both``: products are per size.
* nothing: no edge, a rejected one, or a substitute (another item).

A focus listing takes its strongest link over every other retailer. With none it is ``focus
only``, labelled ``unmatched`` ("no match found at the compared shops; not proven absent"),
or ``missing`` only when the match stage is ``reviewed`` and no compared shop is withheld.

Absence is claimed only where a complete run backs it (``view.complete_run``):

* ``not_at[x]``: focus listings with no link to ``x``, for each ``supported`` other retailer
  ``x`` whose run is complete for the listing's category. Statuses are read from the view's
  retailers at run time, so a shop that becomes supported gets its count with no code change.
* ``others_only``: another retailer's listings observed on the date with no link to the focus
  retailer, only when the focus retailer's run is complete for their category; otherwise
  excluded and counted in a caveat. When the focus retailer itself is not supported, it is
  ``None``, never 0.

A retailer that is not ``supported`` is named in ``withheld`` with its reason. Its listings still
count where they are presence (a fact). Shares are given only over ``MIN_COHORT`` listings.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Protocol

from pi_core.enums import MatchClass, ReviewState
from pi_dataset import ContractModel, DatasetV3, ProductV3
from pi_dataset.models import RetailerStatus
from pi_metrics import view
from pi_metrics.assortment import REVIEWED_STAGE, GapLabel
from pi_metrics.model import (
    COUNTED_STATES,
    EVERY_PROFILE,
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Metric,
    Pct,
    ProductFilter,
    Reason,
    Status,
)

#: The profiles brand gaps apply to (ADR-0008 §3).
PROFILES = EVERY_PROFILE
#: Same product, another size or shade.
FAMILY_CLASSES = frozenset({MatchClass.FAMILY, MatchClass.SIZE_NORMALIZED})


class Side(StrEnum):
    BOTH = "both"
    UNCONFIRMED = "unconfirmed"
    FAMILY = "family"
    FOCUS_ONLY = "focus_only"
    OTHERS_ONLY = "others_only"


class _Link(IntEnum):
    """Evidence between a listing and a retailer, weakest first."""

    NONE = 0
    FAMILY = 1
    UNCONFIRMED = 2
    BOTH = 3


LINK_SIDE = {
    _Link.NONE: Side.FOCUS_ONLY,
    _Link.FAMILY: Side.FAMILY,
    _Link.UNCONFIRMED: Side.UNCONFIRMED,
    _Link.BOTH: Side.BOTH,
}


class CrossLink(ContractModel):
    """A match-file edge between two listings, as the products of the view that hold them.

    pi-api builds these from the match file's listing tokens; the metric never reads the file.
    Unordered: an edge counts only when one side is the focus retailer's, so an edge between two
    other shops never links either of them to the focus.
    """

    a_product: str
    a_retailer: str
    b_product: str
    b_retailer: str
    match_class: MatchClass
    review_state: ReviewState


class CrawlWindow(ContractModel):
    #: Dubai dates of the retailer's first and last observation in the run.
    start: date
    end: date


class WindowOf(Protocol):
    """A retailer's crawl window, or ``None`` where it is not known (the window PR supplies it)."""

    def __call__(self, ds: DatasetV3, retailer_id: str, /) -> CrawlWindow | None: ...


def no_window(ds: DatasetV3, retailer_id: str, /) -> CrawlWindow | None:
    return None


class BasisSide(ContractModel):
    retailer: str
    status: RetailerStatus
    #: Listings of the retailer observed on the date, after the filters.
    listings: int
    window: CrawlWindow | None


class Withheld(ContractModel):
    retailer: str
    reason: Reason


class GapRow(ContractModel):
    id: str
    brand: str
    name: str
    category: tuple[str, ...]
    #: The listing's retailer: the focus retailer, except on ``others_only`` rows.
    retailer: str
    side: Side
    #: ``both`` rows: the retailers an accepted exact edge links it to.
    both_at: tuple[str, ...] = ()
    #: Focus rows: the supported retailers proven not to have it (``not_at``).
    not_at: tuple[str, ...] = ()


class ShopCount(ContractModel):
    retailer: str
    n: int


class BrandRow(ContractModel):
    brand: str
    #: Focus listings: ``both + unconfirmed + family + focus_only``.
    focus_n: int
    both: int
    unconfirmed: int
    family: int
    focus_only: int
    both_by: tuple[ShopCount, ...]
    #: One per supported other retailer, in id order, 0 included: a proven count.
    not_at: tuple[ShopCount, ...]
    others_only: int | None
    others_by: tuple[ShopCount, ...]
    #: ``focus_only / focus_n``, only where ``focus_n >= MIN_COHORT``.
    focus_only_share: Pct | None
    share_reason: Reason | None


class BrandGaps(ContractModel):
    focus: str
    others: tuple[str, ...]
    focus_only_label: GapLabel
    absence_label: GapLabel
    totals: BrandRow
    by_brand: tuple[BrandRow, ...]
    withheld: tuple[Withheld, ...]
    sides: tuple[BasisSide, ...]
    items: tuple[GapRow, ...]


def _withheld_reason(status: RetailerStatus) -> Reason | None:
    if status is RetailerStatus.SUPPORTED:
        return None
    return Reason.RETAILER_BLOCKED if status is RetailerStatus.BLOCKED else Reason.RETAILER_PARTIAL


def _seen(ds: DatasetV3, product: ProductV3, retailer_id: str, i: int) -> bool:
    return any(
        view.seen(o, i)
        for c in view.contexts_of(ds, retailer_id)
        if (o := view.collected(product, c.id)) is not None
    )


def _complete(ds: DatasetV3, product: ProductV3, retailer_id: str, i: int) -> bool:
    shops = view.contexts_of(ds, retailer_id)
    return bool(shops) and all(view.complete_run(ds, c.id, product, i) for c in shops)


def _in_product(ds: DatasetV3, product: ProductV3, focus: str, other: str) -> _Link:
    """The product's own evidence that its focus and ``other`` offers are one item."""
    offers = view.retailer_offers(ds, product, other)
    if not offers or not view.retailer_offers(ds, product, focus):
        return _Link.NONE
    if view.identity_unclear(ds, product, focus) or view.identity_unclear(ds, product, other):
        return _Link.UNCONFIRMED
    edge = view.edge_between(product, focus, other)
    if edge is None:  # grouped without an edge: not identity, not absence either
        return _Link.UNCONFIRMED
    if edge.review_state is ReviewState.REJECTED or edge.match_class is MatchClass.SUBSTITUTE:
        return _Link.NONE
    if edge.match_class in FAMILY_CLASSES:
        return _Link.FAMILY
    counted = edge.review_state in COUNTED_STATES and any(not o.early for o in offers)
    return _Link.BOTH if counted else _Link.UNCONFIRMED


def _gap_row(
    product: ProductV3,
    *,
    retailer: str,
    side: Side,
    both_at: tuple[str, ...] = (),
    not_at: tuple[str, ...] = (),
) -> GapRow:
    return GapRow(
        id=product.id,
        brand=product.brand,
        name=product.name,
        category=product.category,
        retailer=retailer,
        side=side,
        both_at=both_at,
        not_at=not_at,
    )


def _oriented(link: CrossLink, focus: str) -> tuple[str, str, str] | None:
    """``(focus product, other product, other retailer)``; ``None`` when neither side is the
    focus retailer's."""
    if link.a_retailer == focus:
        return link.a_product, link.b_product, link.b_retailer
    if link.b_retailer == focus:
        return link.b_product, link.a_product, link.a_retailer
    return None


def _cross(link: CrossLink) -> _Link:
    if link.review_state is ReviewState.REJECTED or link.match_class is MatchClass.SUBSTITUTE:
        return _Link.NONE
    # An exact edge the view did not merge (proposed, not a clique, a conflict) is unconfirmed.
    return _Link.FAMILY if link.match_class in FAMILY_CLASSES else _Link.UNCONFIRMED


def _counts(found: Counter[str], keys: Sequence[str] = ()) -> tuple[ShopCount, ...]:
    return tuple(ShopCount(retailer=r, n=found[r]) for r in sorted({*found, *keys}))


def _row(
    brand: str,
    rows: Sequence[GapRow],
    focus_withheld: bool,
    supported: Sequence[str],
) -> BrandRow:
    sides = Counter(r.side for r in rows)
    focus_n = sum(sides[s] for s in (Side.BOTH, Side.UNCONFIRMED, Side.FAMILY, Side.FOCUS_ONLY))
    both_by = Counter(x for r in rows for x in r.both_at)
    not_at = Counter(x for r in rows for x in r.not_at)
    others_by = Counter(r.retailer for r in rows if r.side is Side.OTHERS_ONLY)
    measured = focus_n >= MIN_COHORT
    return BrandRow(
        brand=brand,
        focus_n=focus_n,
        both=sides[Side.BOTH],
        unconfirmed=sides[Side.UNCONFIRMED],
        family=sides[Side.FAMILY],
        focus_only=sides[Side.FOCUS_ONLY],
        both_by=_counts(both_by),
        not_at=_counts(not_at, supported),
        others_only=None if focus_withheld else sides[Side.OTHERS_ONLY],
        others_by=_counts(others_by),
        focus_only_share=Decimal(sides[Side.FOCUS_ONLY]) / focus_n * 100 if measured else None,
        share_reason=None if measured else Reason.COHORT_TOO_SMALL,
    )


def brand_gaps(  # noqa: PLR0913 -- the query's inputs
    dataset: view.AnyDataset,
    focus: str,
    where: ProductFilter,
    on: date | None = None,
    *,
    links: Sequence[CrossLink] = (),
    window_of: WindowOf = no_window,
) -> Metric[BrandGaps]:
    """Per brand: the focus retailer's listings by link to the others, and the others' listings
    not at the focus retailer. ``focus`` is a retailer id."""
    ds = view.as_v3(dataset)
    focus_shop = view.retailer(ds, focus)
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    others = tuple(r for r in ds.meta.retailers if r.id != focus)
    withheld = tuple(
        Withheld(retailer=r.id, reason=reason)
        for r in (focus_shop, *others)
        if (reason := _withheld_reason(r.status)) is not None
    )
    focus_withheld = _withheld_reason(focus_shop.status) is not None
    supported = tuple(r.id for r in others if r.status is RetailerStatus.SUPPORTED)
    reviewed = ds.meta.match_stage == REVIEWED_STAGE
    absence_label = GapLabel.MISSING if reviewed else GapLabel.UNMATCHED
    focus_only_label = (
        GapLabel.MISSING
        if reviewed and not any(w.retailer != focus for w in withheld)
        else GapLabel.UNMATCHED
    )
    if not view.applies(ds, PROFILES):
        empty = _row("", (), focus_withheld, supported)
        return Metric[BrandGaps](
            status=Status.NOT_ENOUGH_DATA,
            data=BrandGaps(
                focus=focus,
                others=tuple(r.id for r in others),
                focus_only_label=focus_only_label,
                absence_label=absence_label,
                totals=empty,
                by_brand=(),
                withheld=withheld,
                sides=(),
                items=(),
            ),
            reason=Reason.NOT_APPLICABLE,
            as_of=as_of,
        )

    # Cross-product evidence, both ways: (focus product, retailer) and (other product, retailer).
    from_focus: dict[tuple[str, str], _Link] = defaultdict(lambda: _Link.NONE)
    to_focus: dict[tuple[str, str], _Link] = defaultdict(lambda: _Link.NONE)
    for link in links:
        oriented = _oriented(link, focus)
        if oriented is None:
            continue
        own, other, retailer_id = oriented
        evidence = _cross(link)
        from_focus[own, retailer_id] = max(from_focus[own, retailer_id], evidence)
        to_focus[other, retailer_id] = max(to_focus[other, retailer_id], evidence)

    items: list[GapRow] = []
    listings: Counter[str] = Counter()
    unobserved = 0
    for product in view.products(ds, where):
        if _seen(ds, product, focus, i):
            listings[focus] += 1
            found = {
                r.id: max(_in_product(ds, product, focus, r.id), from_focus[product.id, r.id])
                for r in others
            }
            best = max(found.values(), default=_Link.NONE)
            items.append(
                _gap_row(
                    product,
                    retailer=focus,
                    side=LINK_SIDE[best],
                    both_at=tuple(r for r, k in found.items() if k is _Link.BOTH),
                    not_at=tuple(
                        x
                        for x in supported
                        if found[x] is _Link.NONE and _complete(ds, product, x, i)
                    ),
                )
            )
        for r in others:
            if not _seen(ds, product, r.id, i):
                continue
            listings[r.id] += 1
            linked = max(_in_product(ds, product, focus, r.id), to_focus[product.id, r.id])
            if linked is not _Link.NONE or focus_withheld:
                continue
            if not _complete(ds, product, focus, i):
                unobserved += 1
                continue
            items.append(_gap_row(product, retailer=r.id, side=Side.OTHERS_ONLY))

    items.sort(key=lambda row: (row.brand.casefold(), row.side, row.retailer, row.id))
    brands: dict[str, list[GapRow]] = defaultdict(list)
    for row in items:
        brands[row.brand].append(row)
    caveats = [
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": w.retailer})
        for w in withheld
        if w.reason is Reason.RETAILER_PARTIAL
    ]
    if unobserved:
        caveats.append(
            Caveat(code=CaveatCode.NOT_OBSERVED_EXCLUDED, params={"count": str(unobserved)})
        )
    return Metric[BrandGaps](
        status=Status.OK,
        data=BrandGaps(
            focus=focus,
            others=tuple(r.id for r in others),
            focus_only_label=focus_only_label,
            absence_label=absence_label,
            totals=_row("", items, focus_withheld, supported),
            by_brand=tuple(
                _row(b, rows, focus_withheld, supported) for b, rows in sorted(brands.items())
            ),
            withheld=withheld,
            sides=tuple(
                BasisSide(
                    retailer=r.id,
                    status=r.status,
                    listings=listings[r.id],
                    window=window_of(ds, r.id),
                )
                for r in (focus_shop, *others)
            ),
            items=tuple(items),
        ),
        caveats=tuple(caveats),
        as_of=as_of,
    )
