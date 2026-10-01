"""Build the ``pi.dataset/v2`` snapshot from the same pi_db rows as the v1 export.

v1 (``export.py``) stays the dashboard's input until it moves to v2 (ADR-0007 §6). This builder
reuses v1's grouping and pairing, and renders them as ``pi_dataset`` models, so building the
dataset runs every contract rule: an invalid document cannot be written. What changes from v1:

- retailers are keyed by their source-register key, not the ``u``/``s`` slots;
- money is ``MoneyValue`` (decimal string plus minor units), never a JSON float;
- ratings keep the retailer's own scale (v1 rescaled to 5);
- there is no promo series (the metric layer derives depth from ``price`` and ``regular``);
- availability is a series, with ``null`` for "not observed";
- a match edge carries the ``pi_db`` review state verbatim and who decided it, never who;
- one date (the cutoff's day in Dubai): a price, regular or stock value captured on another day is
  ``null`` there (contract rule 6: never carried forward), and the field is reported ``partial``;
- Ulta's status is the owner's statement (``UltaContext``), not inferred from whether rows exist.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import HttpUrl

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
from scripts.demo_export.export import (
    GroupKey,
    ListingRow,
    MatchRow,
    UltaContext,
    category_for,
    choose_representative,
    decimal_text,
    group_rows,
    pair_groups,
    parse_utc,
    retailer_status,
)

MARKET = MarketInfo(country="AE", currency="AED", time_zone="Asia/Dubai", locales=("en", "ar"))
#: v1 slot -> (source-register key, display name).
RETAILERS = {"u": ("ulta_ae", "Ulta UAE"), "s": ("sephora_me", "Sephora UAE")}
STATUS = {
    "ok": RetailerStatus.SUPPORTED,
    "partial": RetailerStatus.PARTIAL,
    "blocked": RetailerStatus.BLOCKED,
    "pending": RetailerStatus.PENDING,
}
PRODUCT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MATCH_STAGE = "first-pass"


def product_id(token: str) -> str:
    """The v1 id when it is a valid v2 id, else a stable hash of it (never a collision-prone
    character substitution)."""
    if PRODUCT_ID.fullmatch(token):
        return token
    return "p-" + hashlib.sha256(token.encode()).hexdigest()[:24]


@dataclass
class Stale:
    """Values not published because they were captured on another day than ``meta.dates``."""

    day: date
    prices: int = 0
    regulars: int = 0
    stock: int = 0

    def on_day(self, moment: datetime) -> bool:
        return moment.astimezone(ZoneInfo(MARKET.time_zone)).date() == self.day


def money(value: Decimal | None, currency: str) -> MoneyValue | None:
    """A positive price, or ``None`` (not observed). Zero or negative is not a price."""
    if value is None or value <= 0:
        return None
    return MoneyValue.of(value, currency)


def availability(value: str | None) -> AvailabilityState | None:
    if value is None or value == AvailabilityState.NOT_OBSERVED:
        return None
    return AvailabilityState(value)


def offer(rows: Sequence[ListingRow], currency: str, stale: Stale) -> Offer:
    """Price and regular come from the price capture, stock from the stock observation's own
    capture (``stock_capture``); each is published only when captured on ``stale.day``. The
    evidence is the price capture when the price is published, else the stock observation."""
    rep = choose_representative(rows)
    unit, size = rep.effective_size
    price_at, price_run_id = rep.price_capture
    stock_at, stock_run_id = rep.stock_capture
    price = money(rep.price, currency)
    if price is not None and not stale.on_day(price_at):
        price = None
        stale.prices += 1
        stale.regulars += money(rep.regular, currency) is not None
    regular = money(rep.regular, currency) if price is not None else None
    stock = availability(rep.availability)
    if stock is not None and not stale.on_day(stock_at):
        stock = None
        stale.stock += 1
    captured, run_id = (price_at, price_run_id) if price is not None else (stock_at, stock_run_id)
    rating = None
    if rep.rating is not None and rep.rating_scale is not None and rep.rating_count is not None:
        rating = Rating(
            average=decimal_text(rep.rating),
            scale=decimal_text(rep.rating_scale),
            count=rep.rating_count,
        )
    return Offer(
        currency=currency,
        sku=rep.source_sku or rep.source_listing_key,
        url=HttpUrl(rep.url),
        size=Size(value=decimal_text(size), unit=unit) if unit and size and size > 0 else None,
        shade_count=len({row.shade for row in rows if row.shade}),
        rating=rating,
        early=False,
        series=Series(
            price=(price,),
            regular=(regular,) if regular is not None else None,
            availability=(stock,),
        ),
        evidence=Evidence(
            captured_at=captured,
            source=f"{rep.source_name} · local pi_db snapshot",
            run_id=str(run_id),
        ),
    )


def edge(match: MatchRow) -> MatchEdge:
    """pi_db match_edge -> contract edge (docs/contracts/pi-dataset-v2.md rule 8)."""
    state = ReviewState(match.review_state)
    decided = None
    if state is not ReviewState.PROPOSED:
        decided = DecidedBy.HUMAN if match.human else DecidedBy.AUTO
    a, b = sorted(key for key, _ in RETAILERS.values())
    return MatchEdge(
        a=a,
        b=b,
        match_class=MatchClass(match.match_class),
        review_state=state,
        decided_by=decided,
        confidence=decimal_text(match.score) if match.score is not None else None,
        method=match.algo_version,
        stage=MATCH_STAGE,
    )


def product(
    groups: Mapping[GroupKey, Sequence[ListingRow]],
    keys: Sequence[GroupKey],
    token: str,
    stale: Stale,
    matches: Sequence[MatchEdge] = (),
) -> Product:
    """One product: the first key's rows name it (Sephora for a matched pair, as in v1)."""
    rows = groups[keys[0]]
    rep = choose_representative(rows)
    shade_families = sorted({row.shade_family for row in rows if row.shade_family})
    return Product(
        id=product_id(token),
        brand=rep.brand,
        name=rep.name,
        category=(category_for(rep),),
        unit=keys[0].size_unit,
        offers={
            RETAILERS[key.retailer][0]: offer(groups[key], MARKET.currency, stale) for key in keys
        },
        matches=tuple(matches),
        shades=tuple(sorted({row.shade_hex.lower() for row in rows if row.shade_hex})[:12]),
        attributes={"shadeFamilies": list(shade_families)} if shade_families else {},
    )


def early_product(v1: Mapping[str, Any], stale: Stale) -> Product:
    """A recon sample from the v1 early-example dict (``parse_ulta_early_fixture``)."""
    src = v1["offers"]["u"]
    captured = parse_utc(src["evidence"]["capturedAt"])
    rating = None
    if src["rating"] is not None:
        average, count = src["rating"]
        rating = Rating(average=decimal_text(Decimal(str(average))), scale="5", count=count)
    price = money(Decimal(str(src["series"]["price"][0])), MARKET.currency)
    if price is not None and not stale.on_day(captured):
        price = None
        stale.prices += 1
    return Product(
        id=product_id(v1["id"]),
        brand=v1["brand"],
        name=v1["name"],
        category=(v1["category"],),
        unit=None,
        offers={
            RETAILERS["u"][0]: Offer(
                currency=MARKET.currency,
                sku=src["sku"],
                url=HttpUrl(src["url"]) if src["url"] else None,
                size=None,
                shade_count=0,
                rating=rating,
                early=True,
                series=Series(price=(price,), availability=(None,)),
                evidence=Evidence(
                    captured_at=captured,
                    source=src["evidence"]["source"],
                    run_id=src["evidence"]["runId"],
                ),
            )
        },
    )


def status_of(state: str) -> FieldStatus:
    return FieldStatus(state)


def build_dataset_v2(  # noqa: PLR0913 - mirrors build_dataset plus the v2 meta
    rows: Sequence[ListingRow],
    matches: Sequence[MatchRow],
    *,
    generated_at: datetime,
    ulta: UltaContext,
    ulta_note: Mapping[str, str],
    ulta_early: Sequence[Mapping[str, Any]] = (),
    scope: str = "beauty",
    producer_commit: str | None = None,
) -> Dataset:
    """``ulta_note`` is v1's ``meta.retailers[u].note``, so both versions say the same thing."""
    if not rows and not ulta_early:
        raise ValueError("refusing to create an empty demo dataset")
    captures = [row.evidence_retrieved_at or row.observed_at for row in rows]
    captures += [parse_utc(p["offers"]["u"]["evidence"]["capturedAt"]) for p in ulta_early]
    cutoff = max(captures)
    zone = ZoneInfo(MARKET.time_zone)
    day = cutoff.astimezone(zone).date()
    stale = Stale(day)

    groups = group_rows(rows)
    pairs, unpaired = pair_groups(groups, matches)
    products = [
        product(
            groups,
            (sephora, ulta_key),
            f"m-{ulta_key.stable_token}-{sephora.stable_token}",
            stale,
            (edge(match),),
        )
        for ulta_key, sephora, match in pairs
    ]
    products += [product(groups, (key,), key.stable_token, stale) for key in unpaired]
    known = {p.id for p in products}
    products += [early_product(v1, stale) for v1 in ulta_early if product_id(v1["id"]) not in known]
    products.sort(key=lambda p: p.id)

    offers = [o for p in products for o in p.offers.values()]
    collected = [o for o in offers if not o.early]
    raw_prices = [row.price for row in rows if row.price is not None]
    bad_prices = sum(1 for value in raw_prices if value <= 0)
    has_price = any(o.series.price[0] is not None for o in collected)
    has_regular = any(o.series.regular is not None for o in collected)
    has_stock = any((o.series.availability or (None,))[0] is not None for o in collected)
    has_size = any(p.unit is not None for p in products)
    has_shades = any(p.shades for p in products)
    has_rating = any(o.rating is not None for o in offers)

    # The owner's statement, not row presence: rows from before the block must not hide it.
    ulta_status = RetailerStatus.BLOCKED if ulta.blocked else STATUS[retailer_status(rows, "u")]
    retailers = [
        Retailer(
            id=RETAILERS["u"][0],
            name=RETAILERS["u"][1],
            country=MARKET.country,
            status=ulta_status,
            since=ulta.blocked_since.astimezone(zone).date()
            if ulta_status is RetailerStatus.BLOCKED
            else None,
            note=dict(ulta_note) or None,
            early_examples=bool(ulta_early),
        ),
        Retailer(
            id=RETAILERS["s"][0],
            name=RETAILERS["s"][1],
            country=MARKET.country,
            status=STATUS[retailer_status(rows, "s")],
            since=None,
            note=None,
        ),
    ]
    not_observed: tuple[NotObserved, ...] = ()
    if ulta_status is RetailerStatus.BLOCKED:
        start = ulta.blocked_since.astimezone(zone).date()
        not_observed = (
            NotObserved(
                retailer=RETAILERS["u"][0],
                start=start,
                end=max(start, day),
                categories=None,
                why={
                    "en": "Cloudflare challenge; no blocked result is treated as out of stock.",
                    "ar": "تحدّي Cloudflare؛ لا تُعامل النتيجة المحجوبة على أنها نفاد مخزون.",
                },
            ),
        )
    meta = Meta(
        kind="snapshot",
        cutoff=cutoff,
        generated_at=generated_at,
        scope=scope,
        vertical="beauty",
        markets=(MARKET,),
        retailers=tuple(retailers),
        dates=(day,),
        match_stage=MATCH_STAGE,
        capabilities=Capabilities(
            history=False,
            promotions=has_regular,
            campaigns=False,
            stock=has_stock,
            sizes=has_size,
            shades=has_shades,
            coverage=False,
            images=False,
            ratings=has_rating,
        ),
        fields={
            "price": status_of(
                "parse_failure"
                if bad_prices and not has_price and not stale.prices
                else "partial"
                if bad_prices or stale.prices
                else "ok"
                if has_price
                else "not_collected"
            ),
            "regular": status_of(
                "partial" if stale.regulars else "ok" if has_regular else "not_collected"
            ),
            "stock": status_of(
                "partial" if stale.stock else "ok" if has_stock else "not_collected"
            ),
            "size": status_of(
                "ok"
                if all(p.unit is not None for p in products)
                else "partial"
                if has_size
                else "not_published"
            ),
            "shades": status_of("ok" if has_shades else "not_collected"),
            "rating": status_of("ok" if has_rating else "not_collected"),
            "gtin": status_of("not_published"),
            "image": status_of("not_collected"),
        },
        producer=Producer(name="demo_export", version="2", commit=producer_commit),
        test=False,
    )
    return Dataset(
        schema_id="pi.dataset/v2", meta=meta, products=tuple(products), not_observed=not_observed
    )
