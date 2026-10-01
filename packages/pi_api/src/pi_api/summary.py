"""``/v1/summary`` (API 1.4.0): one context's catalogue at a glance, for the landing dashboard.

The numbers come from ``pi_metrics.summary``, computed once per snapshot generation and
context and cached. This module adds what depends on the request or the deployment: the
snapshot's freshness at request time and the ``topDiscounts`` thumbnails, which follow the
``ProductCard.image`` rules (an https URL on the retailer's ``PI_API_IMAGE_HOSTS``, else null).
An imported retailer's freshness is a ``snapshot`` of its import date (API 1.5.0). The default
context is a collected one, and a collected context's ``asOf`` and freshness never come from an
import (API 1.5.1).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from pi_api.analytics import RetailerId
from pi_api.catalog import EvidenceHosts, ScopeQuery, card_image
from pi_api.dq import collected_day
from pi_api.source import Loaded
from pi_dataset import ContractModel
from pi_metrics import Metric, view
from pi_metrics.summary import Summary, default_context, summary

#: Snapshot age, in whole days since its cutoff, up to which it is ``fresh``; then ``aging`` up
#: to ``AGING_DAYS``, then ``stale``. Collection runs daily.
FRESH_DAYS = 1
AGING_DAYS = 3
#: Cached summaries (generation x context); a deployment serves a handful of snapshots.
CACHE_SIZE = 16


class SummaryQuery(ScopeQuery):
    retailer: RetailerId | None = Field(
        default=None,
        description=(
            "A context id (a retailer's sole context has the retailer's id). "
            "Default: the context with the most collected offers."
        ),
    )


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    #: An imported retailer (API 1.5.0): ``cutoff`` is the import date, the capture date is
    #: unknown, so the data is never called fresh however recent the import.
    SNAPSHOT = "snapshot"


class Freshness(ContractModel):
    #: The snapshot's cutoff (``meta.cutoff``); for a ``snapshot``, when it was imported.
    cutoff: datetime
    #: Whole days from the cutoff to the request.
    age_days: int
    status: FreshnessStatus


class SummaryView(Summary):
    freshness: Freshness


def freshness(cutoff: datetime, now: datetime) -> Freshness:
    age = max((now - cutoff).days, 0)
    status = (
        FreshnessStatus.FRESH
        if age <= FRESH_DAYS
        else FreshnessStatus.AGING
        if age <= AGING_DAYS
        else FreshnessStatus.STALE
    )
    return Freshness(cutoff=cutoff, age_days=age, status=status)


def _with_images(loaded: Loaded, metric: Metric[Summary], images: EvidenceHosts) -> Metric[Summary]:
    top = metric.data.top_discounts
    if top is None:
        return metric
    ds = loaded.dataset
    ctx = metric.data.retailer
    products = {p.id: p for p in ds.products}
    items = tuple(
        item.model_copy(
            update={
                "image": card_image(
                    ds, products[item.id], [(ctx, products[item.id].offers[ctx])], images
                )
            }
        )
        for item in top
    )
    return metric.model_copy(
        update={"data": metric.data.model_copy(update={"top_discounts": items})}
    )


class SummaryCache:
    """``pi_metrics.summary`` per (generation, context), least recently used out first."""

    def __init__(self, images: EvidenceHosts, size: int = CACHE_SIZE) -> None:
        self._images = images
        self._size = size
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, str], Metric[Summary]] = OrderedDict()

    def get(self, loaded: Loaded, retailer: str | None) -> Metric[Summary]:
        ds = loaded.dataset
        ctx = (
            default_context(ds, loaded.unverified)
            if retailer is None
            else view.context(ds, retailer)
        ).id
        key = (loaded.generation, ctx)
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None:
                self._entries.move_to_end(key)
                return hit
        metric = _with_images(loaded, summary(ds, ctx, loaded.unverified), self._images)
        with self._lock:
            self._entries[key] = metric
            self._entries.move_to_end(key)
            while len(self._entries) > self._size:
                self._entries.popitem(last=False)
        return metric


def _freshness(loaded: Loaded, ctx: str, now: datetime) -> Freshness:
    for shop in loaded.imported:
        if ctx in shop.contexts:
            age = max((now - shop.imported_at).days, 0)
            return Freshness(cutoff=shop.imported_at, age_days=age, status=FreshnessStatus.SNAPSHOT)
    return freshness(loaded.dataset.meta.cutoff, now)


def summary_view(metric: Metric[Summary], loaded: Loaded, now: datetime) -> Metric[SummaryView]:
    ctx = metric.data.retailer
    as_of = (
        metric.as_of
        if ctx in loaded.unverified
        else collected_day(loaded.imported, metric.as_of, loaded.dataset.meta.cutoff)
    )
    fields = dict(metric.data) | {"as_of": as_of}
    data = SummaryView(**fields, freshness=_freshness(loaded, ctx, now))
    return Metric[SummaryView](
        status=metric.status,
        data=data,
        reason=metric.reason,
        cohort=metric.cohort,
        caveats=metric.caveats,
        as_of=as_of,
    )
