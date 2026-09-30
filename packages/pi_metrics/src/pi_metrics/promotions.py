"""Promotion share and items (design §6 ``/v1/promotions``, §7.4).

A promotion is an observed ``price`` below the observed ``regular`` price on the same date.
The depth is ``(regular - price) / regular x 100``, derived here once (the contract carries only
observations). A retailer's share counts only offers with both prices observed on the date, so
an unpublished regular price is never read as "not on promotion".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pi_core import PiModel
from pi_dataset import Dataset, MoneyValue
from pi_dataset.models import FieldStatus, RetailerStatus
from pi_metrics import view
from pi_metrics.model import (
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Cohort,
    Metric,
    Pct,
    ProductFilter,
    Reason,
    Status,
)

UNCOLLECTED = {FieldStatus.NOT_COLLECTED, FieldStatus.NOT_PUBLISHED, FieldStatus.BLOCKED}


class PromoItem(PiModel):
    id: str
    name: str
    retailer: str
    price: MoneyValue
    regular: MoneyValue
    stated_pct: Pct


class RetailerPromo(PiModel):
    retailer: str
    n: int
    on_promo: int
    share: Pct | None
    reason: Reason | None


class Promotions(PiModel):
    retailers: tuple[RetailerPromo, ...]
    items: tuple[PromoItem, ...]


def depth(price: MoneyValue, regular: MoneyValue) -> Decimal:
    return (regular.decimal() - price.decimal()) / regular.decimal() * 100


def _share(ds: Dataset, retailer: str, n: int, on_promo: int) -> RetailerPromo:
    status = view.retailer(ds, retailer).status
    reason = {
        RetailerStatus.BLOCKED: Reason.RETAILER_BLOCKED,
        RetailerStatus.PARTIAL: Reason.RETAILER_PARTIAL,
    }.get(status)
    if reason is None and n < MIN_COHORT:
        reason = Reason.COHORT_TOO_SMALL
    share = None if reason is not None else Decimal(on_promo) / n * 100
    return RetailerPromo(retailer=retailer, n=n, on_promo=on_promo, share=share, reason=reason)


def promotions(
    ds: Dataset,
    retailers: tuple[str, ...],
    where: ProductFilter,
    min_pct: Decimal | None = None,
    on: date | None = None,
) -> Metric[Promotions]:
    """Per-retailer promo share (n ≥ 5 each) and the promoted items, deepest first."""
    selected = view.selected_retailers(ds, retailers)
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    off = None
    if not ds.meta.capabilities.promotions:
        off = Reason.CAPABILITY_OFF
    elif ds.meta.fields.get("regular", FieldStatus.NOT_COLLECTED) in UNCOLLECTED:
        off = Reason.FIELD_NOT_COLLECTED
    if off is not None:
        return Metric[Promotions](
            status=Status.NOT_ENOUGH_DATA,
            data=Promotions(retailers=(), items=()),
            reason=off,
            as_of=as_of,
        )
    shares, items = [], []
    for shop in selected:
        n = on_promo = 0
        for product in view.products(ds, where):
            offer = view.collected(product, shop.id)
            if offer is None:
                continue
            price, regular = view.price_on(offer, i), view.regular_on(offer, i)
            if price is None or regular is None:
                continue
            n += 1
            if price.decimal() < regular.decimal():
                on_promo += 1
                pct = depth(price, regular)
                if min_pct is None or pct >= min_pct:
                    items.append(
                        PromoItem(
                            id=product.id,
                            name=product.name,
                            retailer=shop.id,
                            price=price,
                            regular=regular,
                            stated_pct=pct,
                        )
                    )
        shares.append(_share(ds, shop.id, n, on_promo))
    items.sort(key=lambda item: (-item.stated_pct, item.retailer, item.id))
    reason = next((s.reason for s in shares if s.reason is not None), None)
    caveats = tuple(
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": s.retailer})
        for s in shares
        if s.reason is Reason.RETAILER_PARTIAL
    )
    return Metric[Promotions](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=Promotions(retailers=tuple(shares), items=tuple(items)),
        reason=reason,
        cohort=Cohort(
            description="offers with price and regular observed on the date",
            n=min((s.n for s in shares), default=0),
        ),
        caveats=caveats,
        as_of=as_of,
    )
