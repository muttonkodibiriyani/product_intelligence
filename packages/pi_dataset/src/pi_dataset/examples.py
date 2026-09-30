"""Synthetic ``pi.dataset/v2`` examples: committed under ``docs/contracts/examples/``.

They document the contract and are the fixture datasets for the read API (service-layer design
§10). Every name, key and price is invented; nothing comes from a retailer. All are ``meta.test``.
Regenerate with ``uv run pi-dataset examples docs/contracts/examples``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from pi_core import AvailabilityState, MatchClass, ReviewState
from pi_dataset.models import (
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
from pi_dataset.validate import dump_dataset

_PRODUCER = Producer(name="pi_dataset.examples", version="1")
_CAPS = Capabilities(
    history=True,
    promotions=True,
    campaigns=False,
    stock=True,
    sizes=True,
    shades=True,
    coverage=True,
    images=False,
    ratings=True,
)
_FIELDS = {
    "price": FieldStatus.OK,
    "regular": FieldStatus.OK,
    "stock": FieldStatus.PARTIAL,
    "size": FieldStatus.OK,
    "shades": FieldStatus.OK,
    "rating": FieldStatus.OK,
    "gtin": FieldStatus.NOT_PUBLISHED,
    "image": FieldStatus.NOT_COLLECTED,
}
_DAYS = 3


def _dates(last: date) -> tuple[date, ...]:
    return tuple(last - timedelta(days=_DAYS - 1 - i) for i in range(_DAYS))


def _money(prices: Sequence[str | None], currency: str) -> tuple[MoneyValue | None, ...]:
    return tuple(None if p is None else MoneyValue.of(Decimal(p), currency) for p in prices)


def _offer(  # noqa: PLR0913 -- keyword-only fixture builder
    retailer: str,
    currency: str,
    prices: Sequence[str | None],
    *,
    regular: Sequence[str | None] | None = None,
    stock: Sequence[AvailabilityState | None] | None = None,
    size: tuple[str, str] = ("50", "ml"),
    early: bool = False,
    captured: datetime,
) -> Offer:
    return Offer(
        currency=currency,
        sku=f"EX-{retailer.upper()}-{len(prices)}{prices[-1] or 'NA'}".replace(".", ""),
        url=None,
        size=Size(value=size[0], unit=size[1]),
        shade_count=0,
        rating=Rating(average="4.25", scale="5", count=12),
        early=early,
        series=Series(
            price=_money(prices, currency),
            regular=None if regular is None else _money(regular, currency),
            availability=None if stock is None else tuple(stock),
        ),
        evidence=Evidence(captured_at=captured, source=f"example:{retailer}", run_id=None),
    )


def _edge(
    a: str, b: str, state: ReviewState, match_class: MatchClass = MatchClass.EXACT
) -> MatchEdge:
    return MatchEdge(
        a=min(a, b),
        b=max(a, b),
        match_class=match_class,
        review_state=state,
        decided_by=None if state is ReviewState.PROPOSED else DecidedBy.HUMAN,
        confidence="0.97",
        method="brand_line_size",
        stage="reviewed",
    )


def _meta(
    *,
    scope: str,
    market: MarketInfo,
    retailers: tuple[Retailer, ...],
    cutoff: datetime,
) -> Meta:
    return Meta(
        kind="snapshot",
        cutoff=cutoff,
        generated_at=cutoff + timedelta(hours=1),
        scope=scope,
        vertical="beauty",
        markets=(market,),
        retailers=retailers,
        dates=_dates(cutoff.date()),
        match_stage="reviewed",
        capabilities=_CAPS,
        fields=_FIELDS,
        producer=_PRODUCER,
        test=True,
    )


IN, LOW, OUT = (
    AvailabilityState.IN_STOCK,
    AvailabilityState.LOW_STOCK,
    AvailabilityState.OUT_OF_STOCK,
)


def ae_pilot() -> Dataset:
    """Two supported retailers in one AED market: the shape of today's pilot."""
    cutoff = datetime(2026, 9, 30, tzinfo=UTC)
    market = MarketInfo(country="AE", currency="AED", time_zone="Asia/Dubai", locales=("en", "ar"))
    north, south = "example_north_ae", "example_south_ae"
    retailers = (
        Retailer(
            id=north,
            name="Example North",
            country="AE",
            status=RetailerStatus.SUPPORTED,
            since=date(2026, 9, 1),
            note=None,
        ),
        Retailer(
            id=south,
            name="Example South",
            country="AE",
            status=RetailerStatus.SUPPORTED,
            since=date(2026, 9, 1),
            note={"en": "Recon samples only.", "ar": "عينات استطلاع فقط."},
            early_examples=True,
        ),
    )
    products = (
        Product(
            id="p-0001",
            brand="Example Beauty",
            name="Hydra Serum",
            category=("skincare", "serum"),
            unit="ml",
            offers={
                north: _offer(
                    north,
                    "AED",
                    ["129.00", "129.00", "99.00"],
                    regular=["129.00", "129.00", "129.00"],
                    stock=[IN, IN, LOW],
                    captured=cutoff,
                ),
                south: _offer(
                    south, "AED", ["135.50", None, "135.50"], stock=[IN, None, IN], captured=cutoff
                ),
            },
            matches=(_edge(north, south, ReviewState.APPROVED),),
        ),
        Product(
            id="p-0002",
            brand="Example Beauty",
            name="Velvet Lipstick",
            category=("makeup", "lips"),
            unit="g",
            shades=("Rose", "Plum"),
            attributes={"finish": "matte"},
            offers={
                north: _offer(
                    north,
                    "AED",
                    ["89.00"] * 3,
                    size=("3.5", "g"),
                    stock=[IN, OUT, OUT],
                    captured=cutoff,
                ),
                south: _offer(
                    south,
                    "AED",
                    [None, None, "92.00"],
                    size=("3.5", "g"),
                    early=True,
                    captured=cutoff,
                ),
            },
            matches=(_edge(north, south, ReviewState.LOCKED),),
        ),
        Product(
            id="p-0003",
            brand="Sample Labs",
            name="Night Cream",
            category=("skincare", "moisturiser"),
            unit="ml",
            offers={north: _offer(north, "AED", ["210.00"] * 3, captured=cutoff)},
        ),
    )
    return Dataset(
        schema_id="pi.dataset/v2",
        meta=_meta(scope="pilot", market=market, retailers=retailers, cutoff=cutoff),
        products=products,
    )


def kw_three_retailers() -> Dataset:
    """Three retailers in KWD (3 decimals): one partial, one blocked, a proposed edge."""
    cutoff = datetime(2026, 9, 30, tzinfo=UTC)
    market = MarketInfo(country="KW", currency="KWD", time_zone="Asia/Kuwait", locales=("ar", "en"))
    a, b, c = "example_alpha_kw", "example_beta_kw", "example_gamma_kw"
    retailers = (
        Retailer(
            id=a,
            name="Example Alpha",
            country="KW",
            status=RetailerStatus.SUPPORTED,
            since=date(2026, 9, 20),
            note=None,
        ),
        Retailer(
            id=b,
            name="Example Beta",
            country="KW",
            status=RetailerStatus.PARTIAL,
            since=date(2026, 9, 20),
            note={"en": "Fragrance only.", "ar": "العطور فقط."},
        ),
        Retailer(
            id=c,
            name="Example Gamma",
            country="KW",
            status=RetailerStatus.BLOCKED,
            since=None,
            note={"en": "Blocked by the site; no data.", "ar": "محجوب؛ لا بيانات."},
        ),
    )
    products = (
        Product(
            id="k-0001",
            brand="Example Parfums",
            name="Oud Nuit EDP",
            category=("fragrance",),
            unit="ml",
            attributes={"concentration": "edp"},
            offers={
                a: _offer(
                    a, "KWD", ["32.500", "32.500", "29.250"], size=("100", "ml"), captured=cutoff
                ),
                b: _offer(
                    b, "KWD", ["33.000", "33.000", "33.000"], size=("100", "ml"), captured=cutoff
                ),
            },
            matches=(_edge(a, b, ReviewState.PROPOSED),),
        ),
    )
    not_observed = (
        NotObserved(
            retailer=b,
            start=cutoff.date() - timedelta(days=2),
            end=cutoff.date(),
            categories=("skincare", "makeup"),
            why={"en": "Outside the collected categories.", "ar": "خارج الفئات المجمعة."},
        ),
        NotObserved(
            retailer=c,
            start=cutoff.date() - timedelta(days=2),
            end=cutoff.date(),
            categories=None,
            why={"en": "Blocked.", "ar": "محجوب."},
        ),
    )
    return Dataset(
        schema_id="pi.dataset/v2",
        meta=_meta(scope="fragrance", market=market, retailers=retailers, cutoff=cutoff),
        products=products,
        not_observed=not_observed,
    )


def fr_two_retailers() -> Dataset:
    """A non-Gulf market (EUR, fr-FR): nothing about the contract is Gulf-specific."""
    cutoff = datetime(2026, 9, 30, tzinfo=UTC)
    market = MarketInfo(country="FR", currency="EUR", time_zone="Europe/Paris", locales=("fr-FR",))
    x, y = "example_ouest_fr", "example_est_fr"
    retailers = (
        Retailer(
            id=x,
            name="Exemple Ouest",
            country="FR",
            status=RetailerStatus.SUPPORTED,
            since=date(2026, 9, 25),
            note=None,
        ),
        Retailer(
            id=y,
            name="Exemple Est",
            country="FR",
            status=RetailerStatus.SUPPORTED,
            since=date(2026, 9, 25),
            note=None,
        ),
    )
    products = (
        Product(
            id="f-0001",
            brand="Marque Exemple",
            name="Crème Visage",
            category=("skincare",),
            unit="ml",
            offers={
                x: _offer(x, "EUR", ["24.90"] * 3, captured=cutoff),
                y: _offer(y, "EUR", ["26.50", "23.85", "23.85"], captured=cutoff),
            },
            matches=(_edge(x, y, ReviewState.APPROVED, MatchClass.SIZE_NORMALIZED),),
        ),
    )
    return Dataset(
        schema_id="pi.dataset/v2",
        meta=_meta(scope="skincare", market=market, retailers=retailers, cutoff=cutoff),
        products=products,
    )


EXAMPLES: dict[str, Callable[[], Dataset]] = {
    "ae-pilot": ae_pilot,
    "kw-three-retailers": kw_three_retailers,
    "fr-two-retailers": fr_two_retailers,
}


def render_examples() -> dict[str, bytes]:
    """File name → canonical bytes, exactly as committed."""
    return {f"{name}.json": dump_dataset(build()) for name, build in EXAMPLES.items()}


def write_examples(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in render_examples().items():
        path = directory / name
        path.write_bytes(data)
        written.append(path)
    return written
