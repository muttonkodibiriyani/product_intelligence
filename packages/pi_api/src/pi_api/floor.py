"""Read-time price floor (owner decision, 2026-10-01): a price of 0.01 or less is invalid.

A published price at or below ``FLOOR`` (0.01 AED, on any retailer, current or regular) is a
placeholder, not a price. The dataset contract is frozen (ADR-0008 §0), so a lone 0.01 can stay
in the file; this view is the one place that withholds it. Stored rows and files are never
changed: the view is computed from the validated dataset at load, once per generation.

- **Null in every response.** The value is cleared from the served copy's series, so every
  metric reads it as not observed: no median, mean, histogram, ladder, brand price, promotion
  depth, gap, index or "cheapest" ever counts it, and no response shows it.
- **Flagged, not silent.** An offer whose latest-date price was withheld is served with
  ``priceFlag: invalid_low`` (cards: ``priceFlags`` by context), and every priced response that
  involves the retailer carries ``invalid_price_excluded`` with the number of its offers that had
  a value withheld on any date.

Zero and negative prices never reach here: ``pi_dataset`` refuses them (a file holding one is
not loaded), so only positive values up to ``FLOOR`` are withheld.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pi_dataset import DatasetV3, MoneyValue, OfferV3, ProductV3
from pi_metrics import Caveat, CaveatCode

#: The highest invalid price, in the market currency's major unit.
FLOOR = Decimal("0.01")

#: Endpoints that show prices or aggregate them (exports by the same name).
PRICED = frozenset(
    {
        "products",
        "product",
        "admin_product",
        "history",
        "compare",
        "index",
        "promotions",
        "summary",
    }
)


class PriceFlag(StrEnum):
    #: The published price was at or below the floor: withheld as invalid, served as null.
    INVALID_LOW = "invalid_low"


@dataclass(frozen=True)
class Floored:
    """What the view withheld at one retailer in a dataset."""

    retailer: str
    #: The retailer's context ids in the dataset.
    contexts: tuple[str, ...]
    #: Offers with at least one price or regular value withheld, on any date.
    offers: int


@dataclass(frozen=True)
class FloorView:
    floored: tuple[Floored, ...] = ()
    #: (product id, context id) of each offer whose latest-date price was withheld.
    flagged: frozenset[tuple[str, str]] = frozenset()


def invalid(money: MoneyValue | None) -> bool:
    return money is not None and money.decimal() <= FLOOR


def _clear(values: tuple[MoneyValue | None, ...]) -> tuple[MoneyValue | None, ...]:
    return tuple(None if invalid(m) else m for m in values)


def _floored(offer: OfferV3) -> OfferV3 | None:
    """The offer with its invalid values cleared, or ``None`` when it has none."""
    series = offer.series
    regular = series.regular or ()
    if not any(invalid(m) for m in (*series.price, *regular)):
        return None
    update: dict[str, object] = {"price": _clear(series.price)}
    if series.regular is not None:
        update["regular"] = _clear(series.regular)
    return offer.model_copy(update={"series": series.model_copy(update=update)})


def floor_view(ds: DatasetV3) -> tuple[DatasetV3, FloorView]:
    """The dataset as served, and what was withheld.

    A dataset with nothing to withhold is returned as the same object, so its responses are
    unchanged byte for byte.
    """
    retailer = {c.id: c.retailer for c in ds.meta.contexts}
    counts: dict[str, int] = {}
    flagged: set[tuple[str, str]] = set()
    products: list[ProductV3] = []
    for product in ds.products:
        offers = dict(product.offers)
        for cid, offer in product.offers.items():
            cleared = _floored(offer)
            if cleared is None:
                continue
            offers[cid] = cleared
            counts[retailer[cid]] = counts.get(retailer[cid], 0) + 1
            if invalid(offer.series.price[-1]):
                flagged.add((product.id, cid))
        products.append(
            product if offers == product.offers else product.model_copy(update={"offers": offers})
        )
    if not counts:
        return ds, FloorView()
    found = tuple(
        Floored(
            retailer=shop,
            contexts=tuple(sorted(c for c, r in retailer.items() if r == shop)),
            offers=counts[shop],
        )
        for shop in sorted(counts)
    )
    served = ds.model_copy(update={"products": tuple(products)})
    return served, FloorView(floored=found, flagged=frozenset(flagged))


def caveats(view: FloorView, endpoint: str, selected: frozenset[str]) -> tuple[Caveat, ...]:
    """``invalid_price_excluded`` for each retailer the request involves (``selected``, empty
    meaning all) that had values withheld, on endpoints that show or aggregate prices."""
    if endpoint.removeprefix("export_") not in PRICED:
        return ()
    return tuple(
        Caveat(
            code=CaveatCode.INVALID_PRICE_EXCLUDED,
            params={"retailer": shop.retailer, "count": str(shop.offers)},
        )
        for shop in view.floored
        if not selected or shop.retailer in selected or not selected.isdisjoint(shop.contexts)
    )
