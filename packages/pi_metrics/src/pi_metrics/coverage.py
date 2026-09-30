"""Per-retailer coverage and trust (design §6 ``/v1/coverage``)."""

from __future__ import annotations

from datetime import date

from pi_core import MatchClass
from pi_dataset import ContractModel, Dataset
from pi_dataset.models import LocalizedText, RetailerStatus
from pi_metrics import view
from pi_metrics.model import COUNTED_STATES, EVERYTHING, Metric, Status


class RetailerCoverage(ContractModel):
    id: str
    name: str
    status: RetailerStatus
    since: date | None
    note: LocalizedText | None
    product_count: int
    matched_count: int
    freshness: date | None


class Coverage(ContractModel):
    retailers: tuple[RetailerCoverage, ...]


def coverage(ds: Dataset, retailers: tuple[str, ...]) -> Metric[Coverage]:
    """Collected (non-early) products, those with a counted edge, and the last observed date."""
    rows = []
    for shop in view.selected_retailers(ds, retailers):
        offered = [
            (p, o) for p in view.products(ds, EVERYTHING) if (o := view.collected(p, shop.id))
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
        seen = [i for i in range(len(ds.meta.dates)) if any(view.seen(o, i) for _, o in offered)]
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
            )
        )
    return Metric[Coverage](
        status=Status.OK, data=Coverage(retailers=tuple(rows)), as_of=ds.meta.dates[-1]
    )
