"""Promotion share and items (design §6 ``/v1/promotions``, §7.4).

A promotion is an observed ``price`` below the observed ``regular`` price on the same date.
The depth is ``(regular - price) / regular x 100``, derived here once (the contract carries only
observations). A retailer's share counts only offers with both prices observed on the date, so
an unpublished regular price is never read as "not on promotion".

Beside the items, each context carries the depth of every promotion in fixed bands and its
brands and categories with the most promotions. Both count every promotion the filters select,
whatever ``min_pct`` and the API's item ``limit``, so a chart never reads a cut list. A group's
share is given only where its context's share is (and over a cohort of at least ``MIN_COHORT``).
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Literal

from pi_core.money import CURRENCY_EXPONENTS
from pi_dataset import ContractModel, DatasetV3, MoneyValue
from pi_dataset.models import FieldStatus, RetailerStatus
from pi_metrics import view
from pi_metrics.model import (
    EVERY_PROFILE,
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
#: The profiles promotions apply to (ADR-0008 §3).
PROFILES = EVERY_PROFILE


#: Lower edges of the depth bands, in percent: [0, 10), [10, 20), ... [50, 100).
BAND_EDGES = (0, 10, 20, 30, 40, 50)
#: Brands and categories given per context, most promotions first.
TOP_GROUPS = 8

GroupKind = Literal["brand", "category"]
KINDS: tuple[GroupKind, ...] = ("brand", "category")


class PromoItem(ContractModel):
    id: str
    name: str
    brand: str
    category: str
    retailer: str
    price: MoneyValue
    regular: MoneyValue
    #: ``regular - price``, exact, in the offer's currency.
    saved: MoneyValue
    depth_pct: Pct
    #: Set by the API from its image hosts (``ProductCard.image`` rules); never by the metric.
    image: str | None = None


class PromoGroup(ContractModel):
    kind: GroupKind
    key: str
    #: Offers in the group with both prices observed, and those below their regular price.
    n: int
    on_promo: int
    #: Only where the context's own share is measured and ``n >= MIN_COHORT``.
    share: Pct | None


class RetailerPromo(ContractModel):
    #: The context id; a retailer's sole context has the retailer's id.
    retailer: str
    n: int
    on_promo: int
    share: Pct | None
    reason: Reason | None
    #: Promotions per depth band (``BAND_EDGES``), every one the filters select. Bands, groups
    #: and items are empty for a context that is not ``listable``.
    bands: tuple[int, ...] = ()
    #: The brands, then the categories, with the most promotions (``TOP_GROUPS`` of each).
    groups: tuple[PromoGroup, ...] = ()


class Promotions(ContractModel):
    retailers: tuple[RetailerPromo, ...]
    items: tuple[PromoItem, ...]
    #: Rows before any ``limit``; ``truncated`` says the list was cut to it (pi_api).
    total: int
    truncated: bool = False


def depth(price: MoneyValue, regular: MoneyValue) -> Decimal:
    return (regular.decimal() - price.decimal()) / regular.decimal() * 100


def saved(price: MoneyValue, regular: MoneyValue) -> MoneyValue:
    """``regular - price`` at the currency's exponent; both are in one currency."""
    minor = regular.minor - price.minor
    exponent = CURRENCY_EXPONENTS[regular.currency]
    amount = f"{Decimal(minor).scaleb(-exponent):.{exponent}f}"
    return MoneyValue(amount=amount, minor=minor, currency=regular.currency)


def band(pct: Decimal) -> int:
    """The index of ``pct``'s band in ``BAND_EDGES``."""
    return max(k for k, edge in enumerate(BAND_EDGES) if pct >= edge)


def _groups(
    kind: GroupKind,
    n: Counter[str],
    on_promo: Counter[str],
    measured: bool,
) -> list[PromoGroup]:
    top = sorted((k for k in on_promo if on_promo[k]), key=lambda k: (-on_promo[k], k))
    return [
        PromoGroup(
            kind=kind,
            key=k,
            n=n[k],
            on_promo=on_promo[k],
            share=Decimal(on_promo[k]) / n[k] * 100 if measured and n[k] >= MIN_COHORT else None,
        )
        for k in top[:TOP_GROUPS]
    ]


#: Reasons that withhold only a context's share: its observed discounts are still facts.
SHARE_ONLY = frozenset({Reason.RETAILER_PARTIAL, Reason.COHORT_TOO_SMALL})


def listable(share: RetailerPromo) -> bool:
    """Whether a context's discounted items, bands and groups are published: its share is
    measured, or only the share is withheld. A blocked or unverified context's are not."""
    return share.share is not None or share.reason in SHARE_ONLY


def _share(
    ds: DatasetV3, retailer: str, n: int, on_promo: int, unverified: frozenset[str]
) -> RetailerPromo:
    status = view.status(ds, retailer)
    reason = None
    if status is RetailerStatus.BLOCKED:
        reason = Reason.RETAILER_BLOCKED
    elif retailer in unverified:  # before partial: it withholds the items too, not only the share
        reason = Reason.WAS_PRICE_UNVERIFIED
    elif status is RetailerStatus.PARTIAL:
        reason = Reason.RETAILER_PARTIAL
    if reason is None and n < MIN_COHORT:
        reason = Reason.COHORT_TOO_SMALL
    share = None if reason is not None else Decimal(on_promo) / n * 100
    return RetailerPromo(retailer=retailer, n=n, on_promo=on_promo, share=share, reason=reason)


def promotions(  # noqa: PLR0913 -- the query's filters plus the keyword-only unverified set
    dataset: view.AnyDataset,
    retailers: tuple[str, ...],
    where: ProductFilter,
    min_pct: Decimal | None = None,
    on: date | None = None,
    *,
    unverified: frozenset[str] = frozenset(),
) -> Metric[Promotions]:
    """Per-context promo share (n ≥ 5 each) and the promoted items, deepest first.

    ``retailers`` are context ids; empty means every context. A context in ``unverified`` has
    unverified was-prices: its share is withheld with that reason, never measured, never 0, and
    like a blocked context it lists no items (``listable``).
    """
    ds = view.as_v3(dataset)
    selected = view.selected_contexts(ds, retailers)
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    off = None
    if not view.applies(ds, PROFILES):
        off = Reason.NOT_APPLICABLE
    elif not ds.meta.capabilities.promotions:
        off = Reason.CAPABILITY_OFF
    elif ds.meta.fields.get("regular", FieldStatus.NOT_COLLECTED) in UNCOLLECTED:
        off = Reason.FIELD_NOT_COLLECTED
    if off is not None:
        return Metric[Promotions](
            status=Status.NOT_ENOUGH_DATA,
            data=Promotions(retailers=(), items=(), total=0),
            reason=off,
            as_of=as_of,
        )
    shares: list[RetailerPromo] = []
    items: list[PromoItem] = []
    for shop in selected:
        found: list[PromoItem] = []
        n = on_promo = 0
        bands = [0] * len(BAND_EDGES)
        counts: dict[GroupKind, tuple[Counter[str], Counter[str]]] = {
            kind: (Counter(), Counter()) for kind in KINDS
        }
        for product in view.products(ds, where):
            offer = view.collected(product, shop.id)
            if offer is None:
                continue
            price, regular = view.price_on(offer, i), view.regular_on(offer, i)
            if price is None or regular is None:
                continue
            n += 1
            keys: dict[GroupKind, str] = {"brand": product.brand, "category": product.category[0]}
            promoted = price.decimal() < regular.decimal()
            for kind, (seen, promo) in counts.items():
                seen[keys[kind]] += 1
                promo[keys[kind]] += promoted
            if promoted:
                on_promo += 1
                pct = depth(price, regular)
                bands[band(pct)] += 1
                if min_pct is None or pct >= min_pct:
                    found.append(
                        PromoItem(
                            id=product.id,
                            name=product.name,
                            brand=product.brand,
                            category=product.category[0],
                            retailer=shop.id,
                            price=price,
                            regular=regular,
                            saved=saved(price, regular),
                            depth_pct=pct,
                        )
                    )
        share = _share(ds, shop.id, n, on_promo, unverified)
        if not listable(share):
            shares.append(share)
            continue
        measured = share.share is not None
        groups = [g for kind in KINDS for g in _groups(kind, *counts[kind], measured)]
        shares.append(share.model_copy(update={"bands": tuple(bands), "groups": tuple(groups)}))
        items.extend(found)
    items.sort(key=lambda item: (-item.depth_pct, item.retailer, item.id))
    reason = next((s.reason for s in shares if s.reason is not None), None)
    caveats = tuple(
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": s.retailer})
        for s in shares
        if s.reason is Reason.RETAILER_PARTIAL
    )
    return Metric[Promotions](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=Promotions(retailers=tuple(shares), items=tuple(items), total=len(items)),
        reason=reason,
        cohort=Cohort(
            description="offers with price and regular observed on the date",
            n=min((s.n for s in shares), default=0),
        ),
        caveats=caveats,
        as_of=as_of,
    )
