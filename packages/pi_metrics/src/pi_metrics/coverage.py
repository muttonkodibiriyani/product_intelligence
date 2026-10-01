"""Per-retailer coverage and trust (design §6 ``/v1/coverage``), with its contexts.

A retailer's row counts its offers in every one of its contexts, as in v2. Its ``contexts``
list each context and whether it was observed on each date (ADR-0008 §2, "Coverage lists
contexts"). A context is never better than its retailer: it carries the retailer's status, and
a ``blocked`` retailer's contexts are observed on no date. Coverage describes collection, not a
metric over it, so it applies to every profile.
"""

from __future__ import annotations

from datetime import date

from pi_core import Channel, MatchClass
from pi_dataset import Context, ContractModel, DatasetV3, Location, ProductV3
from pi_dataset.models import LocalizedText, RetailerStatus
from pi_metrics import view
from pi_metrics.model import COUNTED_STATES, EVERYTHING, Metric, Status


class ContextDay(ContractModel):
    date: date
    #: An offer of the context was seen, and no whole-catalogue ``notObserved`` window covers it.
    observed: bool


class ContextCoverage(ContractModel):
    id: str
    channel: Channel
    location: Location | None
    label: LocalizedText
    #: The retailer's status: a context is never better than its retailer.
    status: RetailerStatus
    product_count: int
    freshness: date | None
    dates: tuple[ContextDay, ...]


class RetailerCoverage(ContractModel):
    id: str
    name: str
    status: RetailerStatus
    since: date | None
    note: LocalizedText | None
    product_count: int
    matched_count: int
    freshness: date | None
    contexts: tuple[ContextCoverage, ...]


class Coverage(ContractModel):
    retailers: tuple[RetailerCoverage, ...]


def coverage(dataset: view.AnyDataset, retailers: tuple[str, ...]) -> Metric[Coverage]:
    """Collected (non-early) products, those with a counted edge, and the last observed date."""
    ds = view.as_v3(dataset)
    rows = []
    for shop in view.selected_retailers(ds, retailers):
        offered = [
            (p, own)
            for p in view.products(ds, EVERYTHING)
            if (own := [o for o in view.retailer_offers(ds, p, shop.id) if not o.early])
        ]
        matched = sum(
            any(
                shop.id in (e.a, e.b)
                and e.match_class is MatchClass.EXACT
                and e.review_state in COUNTED_STATES
                for e in p.matches
            )
            for p, _ in offered
        )
        seen = [
            i
            for i in range(len(ds.meta.dates))
            if any(view.seen(o, i) for _, own in offered for o in own)
        ]
        rows.append(
            RetailerCoverage(
                id=shop.id,
                name=shop.name,
                status=shop.status,
                since=shop.since,
                note=shop.note,
                product_count=len(offered),
                matched_count=matched,
                freshness=ds.meta.dates[seen[-1]] if seen else None,
                contexts=tuple(
                    _context_coverage(ds, c, shop.status)
                    for c in ds.meta.contexts
                    if c.retailer == shop.id
                ),
            )
        )
    return Metric[Coverage](
        status=Status.OK, data=Coverage(retailers=tuple(rows)), as_of=ds.meta.dates[-1]
    )


def _unobserved(ds: DatasetV3, ctx: Context, i: int) -> bool:
    """A ``notObserved`` window over the whole catalogue (no categories) of the context."""
    day = ds.meta.dates[i]
    return any(
        w.retailer == ctx.retailer
        and w.context in (None, ctx.id)
        and w.categories is None
        and w.start <= day <= w.end
        for w in ds.not_observed
    )


def _context_coverage(ds: DatasetV3, ctx: Context, shop_status: RetailerStatus) -> ContextCoverage:
    offered: list[ProductV3] = [
        p for p in view.products(ds, EVERYTHING) if view.collected(p, ctx.id) is not None
    ]
    observed = [
        shop_status is not RetailerStatus.BLOCKED
        and not _unobserved(ds, ctx, i)
        and any(view.seen(p.offers[ctx.id], i) for p in offered)
        for i in range(len(ds.meta.dates))
    ]
    seen = [i for i, ok in enumerate(observed) if ok]
    return ContextCoverage(
        id=ctx.id,
        channel=ctx.channel,
        location=ctx.location,
        label=ctx.label,
        status=shop_status,
        product_count=len(offered),
        freshness=ds.meta.dates[seen[-1]] if seen else None,
        dates=tuple(
            ContextDay(date=day, observed=ok)
            for day, ok in zip(ds.meta.dates, observed, strict=True)
        ),
    )
