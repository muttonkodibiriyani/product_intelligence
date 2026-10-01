"""Catalogue views: ``/v1/meta``, ``/v1/products``, ``/v1/products/{id}[/history]`` (design §6).

Pure functions of a validated dataset and typed queries; the HTTP layer lives in ``app``.
Admin-only fields are in separate models (``AdminEvidence``), never filtered after the fact.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field

from pi_api.wire import SourceText
from pi_core import AvailabilityState, MatchClass, ReviewState
from pi_dataset import (
    Capabilities,
    ContractModel,
    Dataset,
    FieldStatus,
    MoneyValue,
    Offer,
    Product,
    Rating,
    RetailerStatus,
    Size,
)
from pi_metrics import COUNTED_STATES, Metric, ProductFilter, Reason, Status
from pi_metrics.promotions import depth
from pi_metrics.view import price_on, regular_on

MAX_LIMIT = 100
MAX_VALUES = 25
MAX_TEXT = 120

ShortText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
Values = Annotated[tuple[ShortText, ...], Field(max_length=MAX_VALUES)]
DecimalText = Annotated[str, Field(pattern=r"^\d{1,12}(\.\d{1,6})?$")]


class InvalidQueryError(ValueError):
    """A well-formed request that can't be answered as asked (422)."""


class StaleCursorError(Exception):
    """The cursor's generation is no longer loaded (409)."""


# ---------------------------------------------------------------- meta


class RetailerView(ContractModel):
    id: str
    name: SourceText
    country: str
    status: RetailerStatus
    since: date | None
    note: dict[str, SourceText] | None


class CategoryNode(ContractModel):
    key: SourceText
    count: int
    children: tuple[CategoryNode, ...] = ()


class ScopeRef(ContractModel):
    markets: tuple[str, ...]
    scope: str
    cutoff: datetime
    generation: str


class MetaView(ContractModel):
    datasets: tuple[ScopeRef, ...]
    kind: str
    vertical: str
    cutoff: datetime
    dates: tuple[date, ...]
    match_stage: str
    retailers: tuple[RetailerView, ...]
    capabilities: Capabilities
    fields: dict[str, FieldStatus]
    categories: tuple[CategoryNode, ...]
    test: bool


def retailer_views(ds: Dataset) -> tuple[RetailerView, ...]:
    return tuple(
        RetailerView(
            id=r.id,
            name=r.name,
            country=r.country,
            status=r.status,
            since=r.since,
            note=r.note,
        )
        for r in ds.meta.retailers
    )


def category_tree(products: Iterable[Product]) -> tuple[CategoryNode, ...]:
    """Top-level slugs with their second-level children, counted in products."""
    top: Counter[str] = Counter()
    second: dict[str, Counter[str]] = {}
    for p in products:
        top[p.category[0]] += 1
        if len(p.category) > 1:
            second.setdefault(p.category[0], Counter())[p.category[1]] += 1
    return tuple(
        CategoryNode(
            key=key,
            count=count,
            children=tuple(
                CategoryNode(key=child, count=n)
                for child, n in sorted(second.get(key, Counter()).items())
            ),
        )
        for key, count in sorted(top.items())
    )


def meta_view(ds: Dataset, datasets: tuple[ScopeRef, ...]) -> Metric[MetaView]:
    m = ds.meta
    view = MetaView(
        datasets=datasets,
        kind=m.kind,
        vertical=m.vertical,
        cutoff=m.cutoff,
        dates=m.dates,
        match_stage=m.match_stage,
        retailers=retailer_views(ds),
        capabilities=m.capabilities,
        fields=dict(m.fields),
        categories=category_tree(ds.products),
        test=m.test,
    )
    return Metric[MetaView](status=Status.OK, data=view, as_of=m.dates[-1])


# ---------------------------------------------------------------- products


class ProductSort(StrEnum):
    NAME = "name"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"


class ProductQuery(ContractModel):
    """``/v1/products`` filters. Unknown keys are rejected."""

    market: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    scope: ShortText | None = None
    q: ShortText | None = None
    brand: Values = ()
    category: Values = ()
    retailer: Values = ()
    matched: bool | None = None
    price_min: DecimalText | None = None
    price_max: DecimalText | None = None
    sort: ProductSort = ProductSort.NAME
    limit: int = Field(default=25, ge=1, le=MAX_LIMIT)
    cursor: Annotated[str, Field(max_length=512)] | None = None


class CardMatch(ContractModel):
    a: str
    b: str
    match_class: MatchClass
    review_state: ReviewState
    confidence: str | None


class ProductCard(ContractModel):
    id: str
    brand: SourceText
    name: SourceText
    category: tuple[SourceText, ...]
    size: Size | None
    #: Null until the contract carries images; never invented.
    image: None = None
    prices: dict[str, MoneyValue | None]
    matches: tuple[CardMatch, ...]


class FacetCount(ContractModel):
    key: SourceText
    count: int


class Facets(ContractModel):
    brand: tuple[FacetCount, ...]
    category: tuple[FacetCount, ...]
    retailer: tuple[FacetCount, ...]


class ProductPage(ContractModel):
    total: int
    next_cursor: str | None
    items: tuple[ProductCard, ...]
    facets: Facets


def fold(text: str) -> str:
    """Case- and accent-insensitive key; Arabic letter variants folded to a base form."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.translate(_ARABIC_FOLD)


#: Hamza/madda alef to bare alef, alef maqsura to yeh, teh marbuta to heh; tatweel dropped.
_ARABIC_FOLD = str.maketrans(
    {
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0622": "\u0627",
        "\u0649": "\u064a",
        "\u0629": "\u0647",
        "\u0640": None,
    }
)


def _latest(ds: Dataset, offer: Offer) -> MoneyValue | None:
    return price_on(offer, len(ds.meta.dates) - 1)


def _visible(product: Product, retailers: tuple[str, ...]) -> list[tuple[str, Offer]]:
    return [(r, o) for r, o in product.offers.items() if not retailers or r in retailers]


def _low_price(ds: Dataset, product: Product, retailers: tuple[str, ...]) -> Decimal | None:
    prices = [
        p.decimal()
        for _, o in _visible(product, retailers)
        if not o.early and (p := _latest(ds, o)) is not None
    ]
    return min(prices, default=None)


def _decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:  # pragma: no cover - the pattern already guarantees a decimal
        raise InvalidQueryError(text) from None


def card(ds: Dataset, product: Product) -> ProductCard:
    size = next((o.size for o in product.offers.values() if o.size is not None), None)
    return ProductCard(
        id=product.id,
        brand=product.brand,
        name=product.name,
        category=product.category,
        size=size,
        prices={r: _latest(ds, o) for r, o in sorted(product.offers.items())},
        matches=tuple(
            CardMatch(
                a=e.a,
                b=e.b,
                match_class=e.match_class,
                review_state=e.review_state,
                confidence=e.confidence,
            )
            for e in product.matches
        ),
    )


def _matched(product: Product) -> bool:
    return any(
        e.match_class is MatchClass.EXACT and e.review_state in COUNTED_STATES
        for e in product.matches
    )


def _predicates(ds: Dataset, query: ProductQuery) -> dict[str, Callable[[Product], bool]]:
    """One predicate per filter, so each facet can drop its own (design §6, FE ask 6)."""
    brands = {fold(b) for b in query.brand}
    categories = {fold(c) for c in query.category}
    retailers = set(query.retailer)
    words = fold(query.q).split() if query.q else []
    low, high = _decimal(query.price_min), _decimal(query.price_max)
    visible = tuple(query.retailer)
    checks: dict[str, Callable[[Product], bool]] = {}
    if words:
        checks["q"] = lambda p: all(w in fold(f"{p.brand} {p.name} {p.id}") for w in words)
    if brands:
        checks["brand"] = lambda p: fold(p.brand) in brands
    if categories:
        checks["category"] = lambda p: any(fold(c) in categories for c in p.category)
    if retailers:
        checks["retailer"] = lambda p: any(
            r in retailers and not o.early for r, o in p.offers.items()
        )
    if query.matched is not None:
        wanted = query.matched
        checks["matched"] = lambda p: _matched(p) is wanted
    if low is not None or high is not None:

        def priced(p: Product) -> bool:
            price = _low_price(ds, p, visible)
            return (
                price is not None
                and (low is None or price >= low)
                and (high is None or price <= high)
            )

        checks["price"] = priced
    return checks


def _passes(product: Product, checks: dict[str, Callable[[Product], bool]], skip: str) -> bool:
    return all(check(product) for name, check in checks.items() if name != skip)


def _facets(ds: Dataset, checks: dict[str, Callable[[Product], bool]]) -> Facets:
    brand: Counter[str] = Counter()
    category: Counter[str] = Counter()
    retailer: Counter[str] = Counter()
    for p in ds.products:
        if _passes(p, checks, "brand"):
            brand[p.brand] += 1
        if _passes(p, checks, "category"):
            category[p.category[0]] += 1
        if _passes(p, checks, "retailer"):
            for r, o in p.offers.items():
                if not o.early:
                    retailer[r] += 1

    def counts(counter: Counter[str]) -> tuple[FacetCount, ...]:
        return tuple(FacetCount(key=k, count=n) for k, n in sorted(counter.items()))

    return Facets(brand=counts(brand), category=counts(category), retailer=counts(retailer))


def _filters_digest(query: ProductQuery) -> str:
    fields = query.model_dump(mode="json", exclude={"cursor", "limit"})
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]


def encode_cursor(generation: str, offset: int, digest: str) -> str:
    raw = json.dumps({"g": generation, "o": offset, "f": digest}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, generation: str, digest: str) -> int:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        g, offset, f = raw["g"], raw["o"], raw["f"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        msg = "cursor is not valid"
        raise InvalidQueryError(msg) from None
    if not isinstance(offset, int) or offset < 0:
        msg = "cursor is not valid"
        raise InvalidQueryError(msg)
    if f != digest:
        msg = "cursor belongs to different filters"
        raise InvalidQueryError(msg)
    if g != generation:
        raise StaleCursorError
    return offset


def _unknown_values(ds: Dataset, query: ProductQuery) -> None:
    known = {r.id for r in ds.meta.retailers}
    unknown = sorted(set(query.retailer) - known)
    if unknown:
        msg = f"unknown retailer {unknown[0]!r}"
        raise InvalidQueryError(msg)


def product_page(ds: Dataset, generation: str, query: ProductQuery) -> Metric[ProductPage]:
    _unknown_values(ds, query)
    checks = _predicates(ds, query)
    digest = _filters_digest(query)
    offset = 0 if query.cursor is None else decode_cursor(query.cursor, generation, digest)
    hits = [p for p in ds.products if _passes(p, checks, "")]
    visible = tuple(query.retailer)
    if query.sort is ProductSort.NAME:
        hits.sort(key=lambda p: (fold(p.name), p.id))
    else:
        priced = [(p, _low_price(ds, p, visible)) for p in hits]
        sign = -1 if query.sort is ProductSort.PRICE_DESC else 1
        # Ties break on id ascending in both directions; unpriced products come last.
        with_price = sorted(
            ((p, v) for p, v in priced if v is not None), key=lambda pv: (sign * pv[1], pv[0].id)
        )
        hits = [p for p, _ in with_price] + sorted(
            (p for p, v in priced if v is None), key=lambda p: p.id
        )
    page = hits[offset : offset + query.limit]
    end = offset + len(page)
    return Metric[ProductPage](
        status=Status.OK,
        data=ProductPage(
            total=len(hits),
            next_cursor=encode_cursor(generation, end, digest) if end < len(hits) else None,
            items=tuple(card(ds, p) for p in page),
            facets=_facets(ds, checks),
        ),
        as_of=ds.meta.dates[-1],
    )


# ---------------------------------------------------------------- detail and history


class Evidence(ContractModel):
    captured_at: datetime
    url: SourceText | None


class AdminEvidence(Evidence):
    """Admins only (design §4): where the observation came from."""

    source: SourceText
    run_id: str | None


class OfferView(ContractModel):
    retailer: str
    price: MoneyValue | None
    regular: MoneyValue | None
    promo_pct: Annotated[str, Field(pattern=r"^-?\d+(\.\d+)?$")] | None
    rating: Rating | None
    size: Size | None
    shade_count: int | None
    sku: SourceText | None
    early: bool
    availability: AvailabilityState | None
    evidence: Evidence


class AdminOfferView(OfferView):
    evidence: AdminEvidence


class ProductDetail(ContractModel):
    card: ProductCard
    offers: tuple[OfferView, ...]


class AdminProductDetail(ContractModel):
    card: ProductCard
    offers: tuple[AdminOfferView, ...]


def _promo(price: MoneyValue | None, regular: MoneyValue | None) -> str | None:
    if price is None or regular is None or price.decimal() >= regular.decimal():
        return None
    return str(depth(price, regular).quantize(Decimal("0.1")))


def _offer_fields(ds: Dataset, retailer: str, offer: Offer) -> dict[str, Any]:
    i = len(ds.meta.dates) - 1
    price, regular = price_on(offer, i), regular_on(offer, i)
    states = offer.series.availability
    return {
        "retailer": retailer,
        "price": price,
        "regular": regular,
        "promo_pct": _promo(price, regular),
        "rating": offer.rating,
        "size": offer.size,
        "shade_count": offer.shade_count,
        "sku": offer.sku,
        "early": offer.early,
        "availability": None if states is None else states[i],
    }


def find(ds: Dataset, product_id: str) -> Product:
    for p in ds.products:
        if p.id == product_id:
            return p
    raise KeyError(product_id)


def product_detail(ds: Dataset, product: Product) -> Metric[ProductDetail]:
    offers = tuple(
        OfferView(
            **_offer_fields(ds, r, o),
            evidence=Evidence(
                captured_at=o.evidence.captured_at, url=None if o.url is None else str(o.url)
            ),
        )
        for r, o in sorted(product.offers.items())
    )
    return Metric[ProductDetail](
        status=Status.OK,
        data=ProductDetail(card=card(ds, product), offers=offers),
        as_of=ds.meta.dates[-1],
    )


def admin_product_detail(ds: Dataset, product: Product) -> Metric[AdminProductDetail]:
    offers = tuple(
        AdminOfferView(
            **_offer_fields(ds, r, o),
            evidence=AdminEvidence(
                captured_at=o.evidence.captured_at,
                url=None if o.url is None else str(o.url),
                source=o.evidence.source,
                run_id=o.evidence.run_id,
            ),
        )
        for r, o in sorted(product.offers.items())
    )
    return Metric[AdminProductDetail](
        status=Status.OK,
        data=AdminProductDetail(card=card(ds, product), offers=offers),
        as_of=ds.meta.dates[-1],
    )


class HistoryPoint(ContractModel):
    date: date
    price: MoneyValue | None
    regular: MoneyValue | None
    availability: AvailabilityState | None


class History(ContractModel):
    id: str
    series: dict[str, tuple[HistoryPoint, ...]]


class HistoryQuery(ContractModel):
    market: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    scope: ShortText | None = None
    start: date | None = Field(default=None, alias="from")
    end: date | None = Field(default=None, alias="to")


def history(ds: Dataset, product: Product, query: HistoryQuery) -> Metric[History]:
    """Per-retailer series; a missing day is null, never carried forward."""
    if query.start and query.end and query.start > query.end:
        msg = "from is after to"
        raise InvalidQueryError(msg)
    days = [
        (i, d)
        for i, d in enumerate(ds.meta.dates)
        if (query.start is None or d >= query.start) and (query.end is None or d <= query.end)
    ]
    if len(days) > 1 and not ds.meta.capabilities.history:
        days = days[-1:]
        status, reason = Status.NOT_ENOUGH_DATA, Reason.CAPABILITY_OFF
    else:
        status, reason = Status.OK, None
    series = {
        r: tuple(
            HistoryPoint(
                date=d,
                price=price_on(o, i),
                regular=regular_on(o, i),
                availability=None if o.series.availability is None else o.series.availability[i],
            )
            for i, d in days
        )
        for r, o in sorted(product.offers.items())
    }
    return Metric[History](
        status=status,
        data=History(id=product.id, series=series),
        reason=reason,
        as_of=days[-1][1] if days else ds.meta.dates[-1],
    )


def product_filter(query: ProductQuery) -> ProductFilter:
    return ProductFilter(brands=query.brand, categories=query.category)
