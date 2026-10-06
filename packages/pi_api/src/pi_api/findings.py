"""``/v1/findings`` (API 1.23.0): the twelve findings at the top of the Insights page.

The findings come from ``pi_metrics.findings``, computed once per snapshot generation, shop pair
and date and cached: they read every shop's catalogue and compare's counted pairs between each
two, which takes seconds on the UAE snapshot, so a separate endpoint keeps ``/insights`` fast and
lets the page show its own sections while the findings load. This module adds what depends on
the deployment: each example's card image (``card_image``, the shop's own offer, as the value
picks), and ``pi_match``'s brand normalisation for brand-level comparisons.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import date

from pydantic import Field

from pi_api.analytics import RetailerId
from pi_api.catalog import EvidenceHosts, ScopeQuery, card_image
from pi_api.source import Loaded
from pi_dataset import DatasetV3
from pi_match.normalise import normalise_brand
from pi_metrics import Metric
from pi_metrics.findings import Example, Findings, findings

#: Cached findings (generation x focus x rival x date); a page reads one pair at a time.
CACHE_SIZE = 16


class FindingsQuery(ScopeQuery):
    """Whole catalogues: no brand, category or product filter. Every shop besides the two is a
    third shop the findings also read."""

    focus: RetailerId = Field(description="The context the findings advise.")
    rival: RetailerId = Field(description="The context it is set against.")
    on: date | None = Field(default=None, alias="date")


def example_images(
    ds: DatasetV3, metric: Metric[Findings], images: EvidenceHosts
) -> Metric[Findings]:
    """Each example's card image (``card_image``, the example shop's own offer)."""
    products = {p.id: p for p in ds.products}

    def pictured(e: Example) -> Example:
        product = products[e.id]
        image = card_image(ds, product, [(e.retailer, product.offers[e.retailer])], images)
        return e.model_copy(update={"image": image})

    shown = tuple(
        f.model_copy(update={"examples": tuple(pictured(e) for e in f.examples)})
        for f in metric.data.findings
    )
    return metric.model_copy(update={"data": metric.data.model_copy(update={"findings": shown})})


class FindingsCache:
    """``pi_metrics.findings`` per (generation, focus, rival, date), least recently used out
    first. Concurrent misses on one key may each compute it; the result is the same."""

    def __init__(self, images: EvidenceHosts, size: int | None = None) -> None:
        self._images = images
        self._size = CACHE_SIZE if size is None else size
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, str, str, date | None], Metric[Findings]] = (
            OrderedDict()
        )

    def get(self, loaded: Loaded, ds: DatasetV3, query: FindingsQuery) -> Metric[Findings]:
        """The findings over ``ds``, the dataset ``query.on`` reads (``read_at``)."""
        key = (loaded.generation, query.focus, query.rival, query.on)
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None:
                self._entries.move_to_end(key)
                return hit
        metric = findings(
            ds,
            query.focus,
            query.rival,
            on=query.on,
            brand_key=normalise_brand,
            unverified=loaded.unverified,
        )
        metric = example_images(ds, metric, self._images)
        with self._lock:
            self._entries[key] = metric
            self._entries.move_to_end(key)
            while len(self._entries) > self._size:
                self._entries.popitem(last=False)
        return metric
