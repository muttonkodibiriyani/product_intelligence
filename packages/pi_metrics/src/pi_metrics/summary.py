"""One context's catalogue at a glance (``/v1/summary``): the landing dashboard's numbers.

Every figure is over the context's non-early offers observed on the latest date (priced, or
with an observed stock state); price figures over those with a price in the market currency.
Percentiles and medians are nearest-rank, so each is an observed price, exact in its currency
(the median of an even count is the lower middle). Promotion figures follow
``pi_metrics.promotions``: an offer counts only with both prices observed, so an unpublished
regular price is never read as "not on promotion"; without the ``regular`` field they are
withheld, never zero. Every withheld section is ``None`` and listed in ``withheld`` with its
reason.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pi_dataset import Context, ContractModel, DatasetV3, MoneyValue, OfferV3, ProductV3
from pi_dataset.models import FieldStatus, RetailerStatus
from pi_dataset.text import SourceText
from pi_metrics import view
from pi_metrics.model import (
    EVERY_PROFILE,
    EVERYTHING,
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Cohort,
    Metric,
    Pct,
    RatingValue,
    Reason,
    Status,
)
from pi_metrics.promotions import UNCOLLECTED, depth

#: The profiles the summary applies to (ADR-0008 §3).
PROFILES = EVERY_PROFILE
#: Rows in the price ladder and the promotion-depth grid: the largest top-level categories.
CATEGORY_ROWS = 20
#: Brands in ``brandPrice``, by priced offer count.
BRAND_ROWS = 30
#: Category paths in ``categoryMix``, by offer count.
MIX_ROWS = 100
#: Histogram bins, equal on a log scale between the lowest and highest price.
HIST_BINS = 20
#: Points in ``ratingPrice``; beyond it a deterministic sample (by a hash of the point).
RATING_POINTS = 800
#: Items in ``topDiscounts``.
TOP_DISCOUNTS = 20
#: Promotion-depth bands, in percent: [low, high), the last one closed at 100.
DEPTH_BANDS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("<10", Decimal(0), Decimal(10)),
    ("10-20", Decimal(10), Decimal(20)),
    ("20-30", Decimal(20), Decimal(30)),
    ("30-50", Decimal(30), Decimal(50)),
    ("50+", Decimal(50), Decimal(101)),
)


class Section(StrEnum):
    """The parts of a summary that can be withheld on their own."""

    PRICES = "prices"
    PROMOTIONS = "promotions"
    RATINGS = "ratings"


class Withheld(ContractModel):
    section: Section
    reason: Reason


class LadderRow(ContractModel):
    category: SourceText
    n: int
    min: MoneyValue
    p25: MoneyValue
    p50: MoneyValue
    p75: MoneyValue
    max: MoneyValue


class PromoDepth(ContractModel):
    """``cells[r][c]``: promoted offers of ``category[r]`` whose depth is in ``bands[c]``."""

    category: tuple[SourceText, ...]
    bands: tuple[str, ...]
    cells: tuple[tuple[int, ...], ...]


class BrandPrice(ContractModel):
    """One of the ``BRAND_ROWS`` brands with the most priced products (n desc, then brand)."""

    brand: SourceText
    #: Priced products of the brand (fold-equal spellings merged).
    n: int
    median: MoneyValue


class CategoryShare(ContractModel):
    #: The full category path, top level first.
    category: tuple[SourceText, ...]
    n: int


class PriceHistogram(ContractModel):
    #: ``len(counts) + 1`` amounts in the summary currency; bin k is ``[edges[k], edges[k+1])``,
    #: the last closed.
    edges: tuple[str, ...]
    counts: tuple[int, ...]


class RatingPoint(ContractModel):
    price: str
    rating: RatingValue
    #: Offers at this price and rating.
    count: int


class RatingPrice(ContractModel):
    #: Rated offers on the most common scale (see ``rating_scale_mixed``).
    n: int
    rated_pct: Pct
    scale: str
    points: tuple[RatingPoint, ...]
    #: The points were sampled down to ``RATING_POINTS``.
    sampled: bool


class TopDiscount(ContractModel):
    id: str
    brand: SourceText
    name: SourceText
    category: tuple[SourceText, ...]
    price: MoneyValue
    regular: MoneyValue
    depth_pct: Pct
    #: Set by the API from its image hosts (``ProductCard.image`` rules); never by the metric.
    image: SourceText | None = None


class Summary(ContractModel):
    #: The context id; a retailer's sole context has the retailer's id.
    retailer: str
    #: The date every figure is for: the snapshot's latest.
    as_of: date
    currency: str
    #: Products with a non-early offer observed at the context on the latest date (``asOf``);
    #: an offer only seen on an earlier date doesn't count. Null when the context is withheld
    #: whole (blocked, not applicable), never 0.
    products: int | None
    #: Of those, priced in ``currency``: the denominator of every price figure and of
    #: ``brandPrice[].n`` (brand concentration = sum of the top n / priced). ``products -
    #: priced`` were observed without a price (a stock state only) or in another currency.
    priced: int | None
    brands: int | None
    categories: int | None
    median_price: MoneyValue | None
    promo_share_pct: Pct | None
    ladder: tuple[LadderRow, ...] | None
    promo_depth: PromoDepth | None
    brand_price: tuple[BrandPrice, ...] | None
    category_mix: tuple[CategoryShare, ...] | None
    price_hist: PriceHistogram | None
    rating_price: RatingPrice | None
    top_discounts: tuple[TopDiscount, ...] | None
    withheld: tuple[Withheld, ...]


def default_context(ds: DatasetV3) -> Context:
    """The context with the most non-early offers observed on the latest date (ties by id)."""
    i = len(ds.meta.dates) - 1
    counts = Counter(
        cid for p in ds.products for cid, o in p.offers.items() if not o.early and view.seen(o, i)
    )
    return min(ds.meta.contexts, key=lambda c: (-counts[c.id], c.id))


def _rank[T](ordered: Sequence[T], pct: int) -> T:
    """Nearest-rank percentile of a sorted, non-empty sequence."""
    return ordered[max(math.ceil(pct * len(ordered) / 100) - 1, 0)]


def _amount(m: MoneyValue) -> Decimal:
    return m.decimal()


def _sorted(prices: list[MoneyValue]) -> list[MoneyValue]:
    return sorted(prices, key=_amount)


def _ladder(rows: dict[str, list[MoneyValue]]) -> tuple[LadderRow, ...]:
    out = []
    for category, prices in rows.items():
        s = _sorted(prices)
        out.append(
            LadderRow(
                category=category,
                n=len(s),
                min=s[0],
                p25=_rank(s, 25),
                p50=_rank(s, 50),
                p75=_rank(s, 75),
                max=s[-1],
            )
        )
    return tuple(out)


def _histogram(prices: list[MoneyValue], exponent: int) -> PriceHistogram | None:
    low, high = _amount(min(prices, key=_amount)), _amount(max(prices, key=_amount))
    if low <= 0 or low == high:
        return None
    quantum = Decimal(1).scaleb(-exponent)
    ratio = (high / low).ln() / HIST_BINS
    inner = [(low * (ratio * k).exp()).quantize(quantum) for k in range(1, HIST_BINS)]
    edges = sorted({low, *inner, high})
    edges = [e for e in edges if low <= e <= high]
    counts = [0] * (len(edges) - 1)
    for price in prices:
        value = _amount(price)
        k = next(i for i in range(len(counts)) if value < edges[i + 1] or i == len(counts) - 1)
        counts[k] += 1
    return PriceHistogram(edges=tuple(str(e) for e in edges), counts=tuple(counts))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rating_price(
    priced: list[tuple[ProductV3, OfferV3, MoneyValue]],
) -> tuple[RatingPrice | None, int]:
    """Points on the most common scale; returns the count of ratings on another scale."""
    rated = [(o.rating, price) for _, o, price in priced if o.rating and o.rating.count > 0]
    scales = Counter(Decimal(r.scale) for r, _ in rated)
    if not scales:
        return None, 0
    scale = min(scales, key=lambda s: (-scales[s], s))
    used = [(Decimal(r.average), price) for r, price in rated if Decimal(r.scale) == scale]
    if len(used) < MIN_COHORT:
        return None, len(rated) - len(used)
    grid = Counter((price.amount, average) for average, price in used)
    keys = sorted(grid, key=lambda k: (Decimal(k[0]), k[1]))
    sampled = len(keys) > RATING_POINTS
    if sampled:
        chosen = set(sorted(keys, key=lambda k: _digest(f"{k[0]}|{k[1]}"))[:RATING_POINTS])
        keys = [k for k in keys if k in chosen]
    return (
        RatingPrice(
            n=len(used),
            rated_pct=Decimal(len(used)) / len(priced) * 100,
            scale=str(scale),
            points=tuple(RatingPoint(price=a, rating=r, count=grid[(a, r)]) for a, r in keys),
            sampled=sampled,
        ),
        len(rated) - len(used),
    )


def _top[K](groups: dict[K, list[MoneyValue]], rows: int, label: Callable[[K], str]) -> list[K]:
    """The ``rows`` largest groups with at least ``MIN_COHORT`` prices, by size then label."""
    big = [k for k, v in groups.items() if len(v) >= MIN_COHORT]
    return sorted(big, key=lambda k: (-len(groups[k]), label(k)))[:rows]


def _promo_off(ds: DatasetV3) -> Reason | None:
    if not ds.meta.capabilities.promotions:
        return Reason.CAPABILITY_OFF
    if ds.meta.fields.get("regular", FieldStatus.NOT_COLLECTED) in UNCOLLECTED:
        return Reason.FIELD_NOT_COLLECTED
    return None


def _rating_off(ds: DatasetV3) -> Reason | None:
    if not ds.meta.capabilities.ratings:
        return Reason.CAPABILITY_OFF
    if ds.meta.fields.get("rating", FieldStatus.NOT_COLLECTED) is FieldStatus.NOT_COLLECTED:
        return Reason.FIELD_NOT_COLLECTED
    return None


def _empty(ctx: Context, as_of: date, currency: str, reason: Reason) -> Summary:
    return Summary(
        retailer=ctx.id,
        as_of=as_of,
        currency=currency,
        products=None,
        priced=None,
        brands=None,
        categories=None,
        median_price=None,
        promo_share_pct=None,
        ladder=None,
        promo_depth=None,
        brand_price=None,
        category_mix=None,
        price_hist=None,
        rating_price=None,
        top_discounts=None,
        withheld=tuple(Withheld(section=s, reason=reason) for s in Section),
    )


class _Promo(ContractModel):
    share: Pct | None
    depth: PromoDepth | None
    top: tuple[TopDiscount, ...] | None
    n: int


def _promotions(
    priced: list[tuple[ProductV3, OfferV3, MoneyValue]], i: int, categories: list[str]
) -> _Promo:
    n = 0
    promoted: list[tuple[ProductV3, MoneyValue, MoneyValue, Decimal]] = []
    for product, offer, price in priced:
        regular = view.regular_on(offer, i)
        if regular is None:
            continue
        n += 1
        if price.decimal() < regular.decimal():
            promoted.append((product, price, regular, depth(price, regular)))
    if n < MIN_COHORT:
        return _Promo(share=None, depth=None, top=None, n=n)
    cells = {c: [0] * len(DEPTH_BANDS) for c in categories}
    for product, _, _, pct in promoted:
        row = cells.get(product.category[0])
        if row is not None:
            band = next(k for k, (_, lo, hi) in enumerate(DEPTH_BANDS) if lo <= pct < hi)
            row[band] += 1
    deepest = sorted(promoted, key=lambda t: (-t[3], t[0].id))[:TOP_DISCOUNTS]
    return _Promo(
        share=Decimal(len(promoted)) / n * 100,
        depth=PromoDepth(
            category=tuple(categories),
            bands=tuple(label for label, _, _ in DEPTH_BANDS),
            cells=tuple(tuple(cells[c]) for c in categories),
        ),
        top=tuple(
            TopDiscount(
                id=p.id,
                brand=p.brand,
                name=p.name,
                category=p.category,
                price=price,
                regular=regular,
                depth_pct=pct,
            )
            for p, price, regular, pct in deepest
        ),
        n=n,
    )


class _Scan(ContractModel):
    """One pass over the context's offers observed on the latest date."""

    offered: tuple[tuple[ProductV3, OfferV3], ...]
    priced: tuple[tuple[ProductV3, OfferV3, MoneyValue], ...]
    early: int


def _scan(ds: DatasetV3, ctx: Context, i: int, currency: str) -> _Scan:
    offered, early = [], 0
    for product in view.products(ds, EVERYTHING):
        offer = product.offers.get(ctx.id)
        if offer is None or not view.seen(offer, i):
            continue
        if offer.early:
            early += 1
        else:
            offered.append((product, offer))
    priced = tuple(
        (p, o, price)
        for p, o in offered
        if (price := view.price_on(o, i)) is not None and price.currency == currency
    )
    return _Scan(offered=tuple(offered), priced=priced, early=early)


def _brands(scan: _Scan) -> tuple[BrandPrice, ...]:
    """Fold-equal brands count together under their least raw form."""
    groups: dict[str, list[MoneyValue]] = defaultdict(list)
    label: dict[str, str] = {}
    for product, _, price in scan.priced:
        key = view.fold(product.brand)
        groups[key].append(price)
        label[key] = min(label.get(key, product.brand), product.brand)
    return tuple(
        BrandPrice(brand=label[k], n=len(groups[k]), median=_rank(_sorted(groups[k]), 50))
        for k in _top(groups, BRAND_ROWS, lambda k: label[k])
    )


def _caveats(ctx: Context, shop: RetailerStatus, early: int, mixed: int) -> tuple[Caveat, ...]:
    caveats = []
    if shop is RetailerStatus.PARTIAL:
        caveats.append(Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": ctx.id}))
    if early:
        caveats.append(Caveat(code=CaveatCode.EARLY_EXCLUDED, params={"count": str(early)}))
    if mixed:
        caveats.append(
            Caveat(
                code=CaveatCode.RATING_SCALE_MIXED,
                params={"retailer": ctx.id, "count": str(mixed)},
            )
        )
    return tuple(caveats)


def _promo_section(
    ds: DatasetV3, scan: _Scan, i: int, rows: list[str], unverified: bool
) -> tuple[_Promo, Reason | None]:
    reason = _promo_off(ds)
    if reason is None and unverified:
        reason = Reason.WAS_PRICE_UNVERIFIED
    if reason is not None:
        return _Promo(share=None, depth=None, top=None, n=0), reason
    promo = _promotions(list(scan.priced), i, rows)
    return promo, None if promo.share is not None else Reason.COHORT_TOO_SMALL


def _rating_section(ds: DatasetV3, scan: _Scan) -> tuple[RatingPrice | None, int, Reason | None]:
    reason = _rating_off(ds)
    if reason is not None:
        return None, 0, reason
    ratings, mixed = _rating_price(list(scan.priced))
    return ratings, mixed, None if ratings is not None else Reason.COHORT_TOO_SMALL


def summary(
    dataset: view.AnyDataset, context_id: str | None, unverified: frozenset[str] = frozenset()
) -> Metric[Summary]:
    """The context's summary on the latest date; ``None`` picks ``default_context``.

    A context in ``unverified`` has unverified was-prices: its promotions are withheld with
    that reason, never measured, never 0.
    """
    ds = view.as_v3(dataset)
    ctx = default_context(ds) if context_id is None else view.context(ds, context_id)
    i = len(ds.meta.dates) - 1
    as_of = ds.meta.dates[i]
    currency = view.market_currency(ds, ctx.retailer)
    shop = view.status(ds, ctx.id)
    off = None
    if not view.applies(ds, PROFILES):
        off = Reason.NOT_APPLICABLE
    elif shop is RetailerStatus.BLOCKED:
        off = Reason.RETAILER_BLOCKED
    if off is not None:
        return Metric[Summary](
            status=Status.NOT_ENOUGH_DATA,
            data=_empty(ctx, as_of, currency, off),
            reason=off,
            as_of=as_of,
        )
    scan = _scan(ds, ctx, i, currency)
    prices = _sorted([price for _, _, price in scan.priced])
    by_category: dict[str, list[MoneyValue]] = defaultdict(list)
    for product, _, price in scan.priced:
        by_category[product.category[0]].append(price)
    rows = _top(by_category, CATEGORY_ROWS, str)
    enough = len(prices) >= MIN_COHORT
    promo, promo_reason = _promo_section(ds, scan, i, rows, ctx.id in unverified)
    ratings, mixed, rating_reason = _rating_section(ds, scan)
    withheld = [
        Withheld(section=section, reason=reason)
        for section, reason in (
            (Section.PRICES, None if enough else Reason.COHORT_TOO_SMALL),
            (Section.PROMOTIONS, promo_reason),
            (Section.RATINGS, rating_reason),
        )
        if reason is not None
    ]
    mix = Counter(p.category for p, _ in scan.offered)
    exponent = len(prices[0].amount.partition(".")[2]) if prices else 0
    data = Summary(
        retailer=ctx.id,
        as_of=as_of,
        currency=currency,
        products=len(scan.offered),
        priced=len(scan.priced),
        brands=len({view.fold(p.brand) for p, _ in scan.offered}),
        categories=len({p.category[0] for p, _ in scan.offered}),
        median_price=_rank(prices, 50) if enough else None,
        promo_share_pct=promo.share,
        ladder=_ladder({c: by_category[c] for c in rows}) if enough else None,
        promo_depth=promo.depth,
        brand_price=_brands(scan) if enough else None,
        category_mix=tuple(
            CategoryShare(category=path, n=n)
            for path, n in sorted(mix.items(), key=lambda kv: (-kv[1], kv[0]))[:MIX_ROWS]
        ),
        price_hist=_histogram(prices, exponent) if enough else None,
        rating_price=ratings,
        top_discounts=promo.top,
        withheld=tuple(withheld),
    )
    return Metric[Summary](
        status=Status.OK if enough else Status.NOT_ENOUGH_DATA,
        data=data,
        reason=None if enough else Reason.COHORT_TOO_SMALL,
        cohort=Cohort(description="offers observed with a price on the latest date", n=len(prices)),
        caveats=_caveats(ctx, shop, scan.early, mixed),
        as_of=as_of,
    )
