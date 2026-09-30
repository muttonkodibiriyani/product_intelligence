"""Read helpers over a validated ``pi.dataset/v2`` document. No metric logic lives here."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

from pi_dataset import Dataset, MatchEdge, MoneyValue, NotObserved, Offer, Product, Retailer
from pi_dataset.models import RetailerStatus
from pi_metrics.model import ProductFilter


class UnknownInput(ValueError):  # noqa: N818 -- a request error; the API maps it to 422
    """A date or retailer the dataset doesn't have."""


def date_index(ds: Dataset, on: date | None) -> int:
    """Index into ``meta.dates``; ``None`` is the latest date."""
    if on is None:
        return len(ds.meta.dates) - 1
    try:
        return ds.meta.dates.index(on)
    except ValueError:
        msg = f"{on} is not an observation date of this dataset"
        raise UnknownInput(msg) from None


def retailer(ds: Dataset, retailer_id: str) -> Retailer:
    for candidate in ds.meta.retailers:
        if candidate.id == retailer_id:
            return candidate
    msg = f"unknown retailer {retailer_id!r}"
    raise UnknownInput(msg)


def selected_retailers(ds: Dataset, ids: tuple[str, ...]) -> tuple[Retailer, ...]:
    return tuple(retailer(ds, i) for i in ids) if ids else ds.meta.retailers


def products(ds: Dataset, where: ProductFilter) -> Iterator[Product]:
    return (p for p in ds.products if where.matches(p))


def price_on(offer: Offer, i: int) -> MoneyValue | None:
    return offer.series.price[i]


def regular_on(offer: Offer, i: int) -> MoneyValue | None:
    return None if offer.series.regular is None else offer.series.regular[i]


def covers(window: NotObserved, product: Product, day: date) -> bool:
    if not window.start <= day <= window.end:
        return False
    if window.categories is None:
        return True
    wanted = {c.casefold() for c in window.categories}
    return any(level.casefold() in wanted for level in product.category)


def not_observed(ds: Dataset, retailer_id: str, product: Product, i: int) -> bool:
    """A ``notObserved`` window says this retailer's catalogue wasn't seen for the product."""
    day = ds.meta.dates[i]
    return any(w.retailer == retailer_id and covers(w, product, day) for w in ds.not_observed)


def complete_run(ds: Dataset, retailer_id: str, product: Product, i: int) -> bool:
    """The retailer's crawl on date ``i`` is complete for the product's category.

    Only a ``supported`` retailer, collected since on or before the date, with no ``notObserved``
    window over the date and category can back an absence claim: a removal, a launch or an
    assortment gap (design §6, §7.3).
    """
    shop = retailer(ds, retailer_id)
    return (
        shop.status is RetailerStatus.SUPPORTED
        and shop.since is not None
        and shop.since <= ds.meta.dates[i]
        and not not_observed(ds, retailer_id, product, i)
    )


def collected(product: Product, retailer_id: str) -> Offer | None:
    """The retailer's offer, unless it is missing or an early recon sample (never counted)."""
    offer = product.offers.get(retailer_id)
    return None if offer is None or offer.early else offer


def seen(offer: Offer, i: int) -> bool:
    """The offer was observed on date ``i``: priced, or with an observed stock state."""
    if offer.series.price[i] is not None:
        return True
    states = offer.series.availability
    return states is not None and states[i] is not None


def edge_between(product: Product, a: str, b: str) -> MatchEdge | None:
    low, high = sorted((a, b))
    return next((e for e in product.matches if (e.a, e.b) == (low, high)), None)


def same_size(a: Offer, b: Offer) -> bool:
    """Both sizes known and equal; the caller handles an unknown size separately."""
    if a.size is None or b.size is None:
        return False
    return (
        Decimal(a.size.value) == Decimal(b.size.value)
        and a.size.unit.casefold() == b.size.unit.casefold()
    )


def market_currency(ds: Dataset, retailer_id: str) -> str:
    return ds.market_of(retailer_id).currency
