"""A synthetic ``pi.dataset/v2`` fixture that exercises every metric rule (design §10).

Invented names and prices; ``meta.test`` is true. Four retailers in one AED market:
``shop_a`` and ``shop_b`` supported, ``shop_c`` partial, ``shop_d`` blocked. Three dates.

| product | at | what it exercises |
|---|---|---|
| p01-p06 | a, b | exact approved/locked pairs (n = 6); promos and stock mix at a |
| p07 | a, b | proposed edge → ``match_unreviewed`` |
| p08 | a, b | rejected edge → ``match_rejected`` |
| p09 | a, b | approved ``family`` edge → ``match_not_exact`` |
| p10 | a, b | exact approved, different sizes → ``size_mismatch`` |
| p11 | a, b | exact approved, b unpriced on the last date → in the index basket, drops out |
| p12 | a | present at a, absent at b → assortment gap |
| p13 | a, b | b is an early recon sample → ``early`` |
| p14 | b | first seen at b on day 2 after a complete run → a launch |
| p15 | c | first seen at c (partial) on day 2 → withheld launch |
| p16 | a, b, c | exact a-c and b-c edges but no a-b edge → a-b ``no_match`` (no transitivity) |
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pi_core import AvailabilityState, MatchClass, ReviewState
from pi_dataset import (
    Capabilities,
    Dataset,
    DecidedBy,
    Evidence,
    FieldStatus,
    MarketInfo,
    MatchEdge,
    Meta,
    MoneyValue,
    NotObserved,
    Offer,
    Producer,
    Product,
    Rating,
    Retailer,
    RetailerStatus,
    Series,
    Size,
)

A, B, C, D = "shop_a", "shop_b", "shop_c", "shop_d"
CUTOFF = datetime(2026, 9, 30, tzinfo=UTC)
DATES = tuple(CUTOFF.date() - timedelta(days=2 - i) for i in range(3))
IN, LOW, OUT = (
    AvailabilityState.IN_STOCK,
    AvailabilityState.LOW_STOCK,
    AvailabilityState.OUT_OF_STOCK,
)
Prices = Sequence[str | None]


def _money(prices: Prices) -> tuple[MoneyValue | None, ...]:
    return tuple(None if p is None else MoneyValue.of(Decimal(p), "AED") for p in prices)


def offer(
    retailer: str,
    prices: Prices,
    *,
    regular: Prices | None = None,
    stock: Sequence[AvailabilityState | None] | None = None,
    size: str = "50",
    rating: tuple[str, str, int] | None = ("4.20", "5", 10),
    early: bool = False,
) -> Offer:
    return Offer(
        currency="AED",
        sku=None,
        url=None,
        size=Size(value=size, unit="ml"),
        shade_count=0,
        rating=None
        if rating is None
        else Rating(average=rating[0], scale=rating[1], count=rating[2]),
        early=early,
        series=Series(
            price=_money(prices),
            regular=None if regular is None else _money(regular),
            availability=None if stock is None else tuple(stock),
        ),
        evidence=Evidence(captured_at=CUTOFF, source=f"fixture:{retailer}", run_id=None),
    )


def edge(
    a: str,
    b: str,
    state: ReviewState = ReviewState.APPROVED,
    match_class: MatchClass = MatchClass.EXACT,
) -> MatchEdge:
    return MatchEdge(
        a=min(a, b),
        b=max(a, b),
        match_class=match_class,
        review_state=state,
        decided_by=None if state is ReviewState.PROPOSED else DecidedBy.HUMAN,
        confidence="0.95",
        method="fixture",
        stage="reviewed",
    )


def product(
    pid: str,
    offers: dict[str, Offer],
    matches: Sequence[MatchEdge] = (),
    *,
    brand: str = "Fixture Beauty",
    category: tuple[str, ...] = ("skincare", "serum"),
) -> Product:
    return Product(
        id=pid,
        brand=brand,
        name=f"Product {pid}",
        category=category,
        unit="ml",
        offers=offers,
        matches=tuple(matches),
    )


def _pairs() -> list[Product]:
    # (a prices, a regular, a stock, b prices, edge state); b is always 100.00 flat.
    rows: list[tuple[Prices, Prices, list[AvailabilityState | None], ReviewState]] = [
        (["90.00"] * 3, ["100.00"] * 3, [IN, IN, IN], ReviewState.APPROVED),
        (["100.00"] * 3, ["100.00"] * 3, [IN, IN, OUT], ReviewState.APPROVED),
        (["110.00"] * 3, ["110.00"] * 3, [IN, LOW, LOW], ReviewState.LOCKED),
        (["95.50"] * 3, ["120.00"] * 3, [IN, IN, IN], ReviewState.APPROVED),
        (["120.00", "120.00", "80.00"], ["120.00"] * 3, [IN, OUT, OUT], ReviewState.LOCKED),
        (["105.25"] * 3, ["105.25"] * 3, [IN, IN, AvailabilityState.REMOVED], ReviewState.APPROVED),
    ]
    return [
        product(
            f"p0{n}",
            {
                A: offer(A, prices, regular=regular, stock=stock),
                B: offer(B, ["100.00"] * 3, regular=["100.00"] * 3, stock=[IN, IN, IN]),
            },
            [edge(A, B, state)],
            brand="Fixture Beauty" if n % 2 else "Sample Labs",
        )
        for n, (prices, regular, stock, state) in enumerate(rows, start=1)
    ]


def metrics_dataset() -> Dataset:
    """The fixture described in the module docstring."""
    flat = ["50.00"] * 3
    products = [
        *_pairs(),
        product("p07", {A: offer(A, flat), B: offer(B, flat)}, [edge(A, B, ReviewState.PROPOSED)]),
        product("p08", {A: offer(A, flat), B: offer(B, flat)}, [edge(A, B, ReviewState.REJECTED)]),
        product(
            "p09",
            {A: offer(A, flat), B: offer(B, flat)},
            [edge(A, B, match_class=MatchClass.FAMILY)],
        ),
        product("p10", {A: offer(A, flat), B: offer(B, flat, size="30")}, [edge(A, B)]),
        product(
            "p11",
            {A: offer(A, ["70.00"] * 3), B: offer(B, ["77.00", "77.00", None])},
            [edge(A, B)],
        ),
        product("p12", {A: offer(A, flat, rating=("3.00", "10", 4))}),
        product(
            "p13",
            {A: offer(A, flat), B: offer(B, [None, None, "55.00"], early=True)},
            [edge(A, B)],
        ),
        product("p14", {B: offer(B, [None, "60.00", "60.00"])}, category=("makeup",)),
        product("p15", {C: offer(C, [None, "65.00", "65.00"])}, category=("makeup",)),
        product(
            "p16",
            {A: offer(A, flat), B: offer(B, flat), C: offer(C, flat)},
            [edge(A, C), edge(B, C)],
        ),
    ]
    since = date(2026, 9, 1)
    retailers = (
        Retailer(
            id=A,
            name="Shop A",
            country="AE",
            status=RetailerStatus.SUPPORTED,
            since=since,
            note=None,
        ),
        Retailer(
            id=B,
            name="Shop B",
            country="AE",
            status=RetailerStatus.SUPPORTED,
            since=since,
            note=None,
        ),
        Retailer(
            id=C,
            name="Shop C",
            country="AE",
            status=RetailerStatus.PARTIAL,
            since=since,
            note={"en": "Makeup only."},
        ),
        Retailer(
            id=D, name="Shop D", country="AE", status=RetailerStatus.BLOCKED, since=None, note=None
        ),
    )
    return Dataset(
        schema_id="pi.dataset/v2",
        meta=Meta(
            kind="snapshot",
            cutoff=CUTOFF,
            generated_at=CUTOFF + timedelta(hours=1),
            scope="fixture",
            vertical="beauty",
            markets=(
                MarketInfo(country="AE", currency="AED", time_zone="Asia/Dubai", locales=("en",)),
            ),
            retailers=retailers,
            dates=DATES,
            match_stage="reviewed",
            capabilities=Capabilities(
                history=True,
                promotions=True,
                campaigns=False,
                stock=True,
                sizes=True,
                shades=False,
                coverage=True,
                images=False,
                ratings=True,
            ),
            fields={
                "price": FieldStatus.OK,
                "regular": FieldStatus.OK,
                "stock": FieldStatus.OK,
                "rating": FieldStatus.OK,
            },
            producer=Producer(name="pi_metrics.fixtures", version="1"),
            test=True,
        ),
        products=tuple(products),
        not_observed=(
            NotObserved(
                retailer=C,
                start=DATES[0],
                end=DATES[-1],
                categories=("skincare",),
                why={"en": "Skincare not collected."},
            ),
            NotObserved(
                retailer=D, start=DATES[0], end=DATES[-1], categories=None, why={"en": "Blocked."}
            ),
        ),
    )


# Variants, each re-validated so a test can't build an invalid dataset.


def rebuild(ds: Dataset, **meta: Any) -> Dataset:
    """``ds`` with some ``meta`` fields replaced, validated again from scratch."""
    return Dataset.model_validate(
        ds.model_copy(update={"meta": ds.meta.model_copy(update=meta)}).model_dump()
    )


def with_capabilities(ds: Dataset, **flags: bool) -> Dataset:
    return rebuild(ds, capabilities=ds.meta.capabilities.model_copy(update=flags))


def with_fields(ds: Dataset, **fields: Any) -> Dataset:
    return rebuild(ds, fields={**ds.meta.fields, **fields})


def with_saudi_shop(ds: Dataset) -> Dataset:
    """Adds ``shop_e`` in a SAR market with no offers: any pair with it is a currency mismatch."""
    return rebuild(
        ds,
        markets=(
            *ds.meta.markets,
            MarketInfo(country="SA", currency="SAR", time_zone="Asia/Riyadh", locales=("en",)),
        ),
        retailers=(
            *ds.meta.retailers,
            Retailer(
                id="shop_e",
                name="Shop E",
                country="SA",
                status=RetailerStatus.SUPPORTED,
                since=ds.meta.dates[0],
                note=None,
            ),
        ),
    )


def with_dates(ds: Dataset, count: int) -> Dataset:
    """Only the last ``count`` dates, with every series cut to match."""
    keep = slice(len(ds.meta.dates) - count, None)
    products = []
    for p in ds.products:
        offers = {}
        for rid, o in p.offers.items():
            s = o.series
            series = s.model_copy(
                update={
                    "price": s.price[keep],
                    "regular": None if s.regular is None else s.regular[keep],
                    "availability": None if s.availability is None else s.availability[keep],
                }
            )
            offers[rid] = o.model_copy(update={"series": series})
        products.append(p.model_copy(update={"offers": offers}))
    windows = tuple(
        w.model_copy(update={"start": max(w.start, ds.meta.dates[keep][0])})
        for w in ds.not_observed
    )
    cut = ds.model_copy(update={"products": tuple(products), "not_observed": windows})
    return rebuild(cut, dates=ds.meta.dates[keep])


def scaled(ds: Dataset, copies: int) -> Dataset:
    """``ds`` with its products repeated ``copies`` times under new ids, unvalidated for speed."""
    products = tuple(
        p.model_copy(update={"id": f"{p.id}x{k}"}) for k in range(copies) for p in ds.products
    )
    return ds.model_copy(update={"products": products})
