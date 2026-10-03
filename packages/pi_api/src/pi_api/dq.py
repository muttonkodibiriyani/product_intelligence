"""Read-time data-quality view of imported retailers (owner decision, 2026-10-01; API 1.5.0).

An imported retailer's data came from a one-off import, not from PI's daily collection. Its
stored rows and files are never changed: this view is computed from the validated dataset at
load, once per generation, and only the served copy differs.

- **Was-prices.** An imported ``regular`` (was) price is the retailer's own stated was-price,
  never checked by PI. Since the owner's decision of 2026-10-03 (API 1.13.0) they are served and
  measured like any other, and every priced response that involves the retailer says whose
  figure it is (``was_price_stated``). A regular price at or below the current price is never a
  promotion (``pi_metrics``). A retailer named in ``WAS_PRICE_WITHHELD`` (none now) gets the
  1 October rule back: the view clears its ``regular`` series, so no discount, promotion or
  top-discount figure reads it and none reads "no promotion" either (``was_price_unverified``).
- **Import date.** The offers' ``capturedAt`` is the import time, not an observation date. The
  retailer is served as a snapshot imported on that date, never as fresh collection, and the
  dataset's ``meta.cutoff`` is the latest capture of the other retailers' offers, so an import
  never reads as the data's "as of" time (when every offer is imported, the file's cutoff is
  kept and the response's ``snapshot_import_date`` caveat says so). ``meta.dates`` and the
  series are left as published; ``collected_day`` caps the ``asOf`` day that a collected
  retailer's ``/summary`` reports.

Each response that involves an imported retailer says so in caveats: ``was_price_stated`` (or
``was_price_unverified`` when withheld) where the endpoint shows prices or promotions and the
retailer has was-prices, then always ``snapshot_import_date`` and ``parent_listings_included``.

Not done here: dropping the import's aggregate-parent listings. The served document carries no
parent marker, so that dedupe belongs to the export; until then the caveat says the retailer's
products may include parents that repeat their variants.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pi_dataset import DatasetV3, OfferV3, ProductV3
from pi_metrics import Caveat, CaveatCode

#: Retailers served through this view: their data is an import, not PI's collection.
IMPORTED = frozenset({"ulta_ae"})

#: Imported retailers whose was-prices are withheld as unverified. Empty since the owner's
#: decision of 2026-10-03 ("Show Ulta discounts"): ``ulta_ae``'s stated was-prices are served.
WAS_PRICE_WITHHELD: frozenset[str] = frozenset()

#: Endpoints that show prices, was-prices or promotions (exports by the same name).
PRICED = frozenset(
    {
        "products",
        "product",
        "admin_product",
        "history",
        "compare",
        "category_compare",
        "price_suggestions",
        "promotions",
        "summary",
    }
)


@dataclass(frozen=True)
class Imported:
    """What the view did to one imported retailer in a dataset."""

    retailer: str
    #: The retailer's context ids in the dataset.
    contexts: tuple[str, ...]
    #: The latest ``capturedAt`` of the retailer's offers: when its snapshot was imported.
    imported_at: datetime
    #: Offers that carry a stated was-price (any non-null value in their ``regular`` series).
    was_prices: int
    #: The retailer's market time zone: the import date is that local day (API 1.7.0).
    time_zone: str = "UTC"
    #: Whether its was-prices were withheld (``WAS_PRICE_WITHHELD``): the series was cleared.
    withheld: bool = False

    @property
    def imported_on(self) -> date:
        """The local day of ``imported_at`` in the market, as ``meta.dates`` count days."""
        return self.imported_at.astimezone(ZoneInfo(self.time_zone)).date()


def _without_regular(offer: OfferV3) -> OfferV3:
    return offer.model_copy(update={"series": offer.series.model_copy(update={"regular": None})})


def imported_view(
    ds: DatasetV3, withheld: frozenset[str] | None = None
) -> tuple[DatasetV3, tuple[Imported, ...]]:
    """The dataset as served, and one ``Imported`` per imported retailer it holds.

    A dataset without one is returned as the same object, so other retailers' responses are
    unchanged byte for byte.
    """
    withheld = WAS_PRICE_WITHHELD if withheld is None else withheld
    contexts = {c.id: c.retailer for c in ds.meta.contexts if c.retailer in IMPORTED}
    if not contexts:
        return ds, ()
    latest: dict[str, datetime] = {}
    stated: dict[str, int] = dict.fromkeys(contexts.values(), 0)
    products: list[ProductV3] = []
    for product in ds.products:
        offers = dict(product.offers)
        for cid, offer in product.offers.items():
            shop = contexts.get(cid)
            if shop is None:
                continue
            at = offer.evidence.captured_at
            latest[shop] = max(latest.get(shop, at), at)
            if offer.series.regular is not None:
                stated[shop] += any(m is not None for m in offer.series.regular)
                if shop in withheld:
                    offers[cid] = _without_regular(offer)
        products.append(
            product if offers == product.offers else product.model_copy(update={"offers": offers})
        )
    own = [
        o.evidence.captured_at
        for p in ds.products
        for cid, o in p.offers.items()
        if cid not in contexts
    ]
    meta = ds.meta.model_copy(update={"cutoff": max(own)}) if own else ds.meta
    served = ds.model_copy(update={"products": tuple(products), "meta": meta})
    found = tuple(
        Imported(
            retailer=shop,
            contexts=tuple(sorted(c for c, r in contexts.items() if r == shop)),
            imported_at=latest[shop],
            was_prices=stated[shop],
            time_zone=ds.market_of(shop).time_zone,
            withheld=shop in withheld,
        )
        for shop in sorted(latest)
    )
    return served, found


def caveats(
    imported: tuple[Imported, ...], endpoint: str, selected: frozenset[str]
) -> tuple[Caveat, ...]:
    """The caveats a response owes for the imported retailers it involves.

    ``selected`` holds the retailer or context ids the request named; empty means all of them.
    """
    out: list[Caveat] = []
    for shop in imported:
        if selected and shop.retailer not in selected and selected.isdisjoint(shop.contexts):
            continue
        if endpoint.removeprefix("export_") in PRICED and (shop.withheld or shop.was_prices):
            code = CaveatCode.WAS_PRICE_UNVERIFIED if shop.withheld else CaveatCode.WAS_PRICE_STATED
            out.append(Caveat(code=code, params={"retailer": shop.retailer}))
        out.append(
            Caveat(
                code=CaveatCode.SNAPSHOT_IMPORT_DATE,
                params={"retailer": shop.retailer, "date": shop.imported_on.isoformat()},
            )
        )
        out.append(
            Caveat(code=CaveatCode.PARENT_LISTINGS_INCLUDED, params={"retailer": shop.retailer})
        )
    return tuple(out)


def collected_day(
    imported: tuple[Imported, ...], day: date, cutoff: datetime, time_zone: str
) -> date:
    """The as-of day of collected data: with an import served, never after the cutoff's local
    day in the market's ``time_zone`` (the day ``meta.dates`` are counted in)."""
    return min(day, cutoff.astimezone(ZoneInfo(time_zone)).date()) if imported else day
