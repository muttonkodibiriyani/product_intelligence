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
- ``category`` is the one-level code followed by the naming offer's own breadcrumb (at most three
  levels, verbatim; see ``category_path``);
- ``image`` is the retailer's own main image URL, hotlinked (never rehosted) and only from that
  retailer's allowlisted https host (``IMAGE_HOSTS``); anything else, including another
  retailer's host, is ``null``, never a guess;
- Ulta's status is the owner's statement (``UltaContext``), not inferred from whether rows exist.

``to_v3`` (``--output-v3``, opt-in) upgrades that v2 snapshot under ``beauty@1`` and states each
collected offer's ``listingCount``: the listing rows grouped into it (one family, one size).
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import HttpUrl

from pi_core import AvailabilityState, Concentration, MatchClass, ReviewState, is_valid_gtin
from pi_core.enums import NotObservedReason
from pi_dataset import (
    AttributeEvidence,
    AttributeSource,
    Capabilities,
    ContentField,
    CrawlWindow,
    Dataset,
    DatasetV3,
    DecidedBy,
    Evidence,
    FieldStatus,
    MarketInfo,
    MatchEdge,
    Meta,
    MoneyValue,
    NotObserved,
    NotObservedV3,
    Offer,
    OfferContent,
    OfferVariant,
    Producer,
    Product,
    ProfileDeclaration,
    Rating,
    Retailer,
    RetailerStatus,
    Series,
    Size,
    committed_profile,
    upgrade,
)
from pi_dataset.v3 import BEAUTY_EVIDENCE_FROM, EXCERPT_MAX
from scripts.demo_export.export import (
    MARKET_TIME_ZONE,
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
from scripts.demo_export.tidy import tidy_rows

MARKET = MarketInfo(country="AE", currency="AED", time_zone=MARKET_TIME_ZONE, locales=("en", "ar"))
#: Slot -> (source-register key, display name). Faces (2026-10-03), Ounass and Bloomingdale's
#: (2026-10-07, beauty only, EN only) are v2/v3 only.
RETAILERS = {
    "u": ("ulta_ae", "Ulta UAE"),
    "s": ("sephora_me", "Sephora UAE"),
    "f": ("faces_ae", "Faces UAE"),
    "o": ("ounass_ae", "Ounass UAE"),
    "b": ("bloomingdales_ae", "Bloomingdale's UAE"),
}
#: Slots whose crawl is not known to be a complete catalogue (Faces, Ounass, Bloomingdale's).
#: Such a retailer's snapshot is ``partial`` whatever its runs say.
INCOMPLETE_CATALOGUE = frozenset({"f", "o", "b"})
#: The ``INCOMPLETE_CATALOGUE`` slots whose import run can attest a complete day (Faces only). In
#: history, a Faces day is complete only on an import run recorded ``succeeded``, which the feed
#: claims only when the run read every product URL of the measured sitemap
#: (``pi_capture.feed.completeness``; decision log 2026-10-06). Ounass and Bloomingdale's have no
#: measured denominator: no day of theirs is ever complete, so their absence infers nothing (no
#: launch, removal or stock-out from a page not seen; decision log 2026-10-06).
SITEMAP_ATTESTED = frozenset({"f"})
#: Slots whose per-page stock is not published (``null``, not observed). Faces' page stock is
#: loaded (decision log 2026-10-06) but its export side is a separate Faces exporter PR, so it
#: stays unpublished here. Ounass and Bloomingdale's publish the stock their own page states (the
#: JSON-LD offer and the page flag agree, else the feed leaves it unknown): an out-of-stock page
#: is an offer published out of stock, never dropped or read as removed.
STOCK_NOT_PUBLISHED = frozenset({"f"})
#: How each slot's source states a regular price, read here at export time so rows loaded before
#: a declaration changed are published under it too (observations are append-only).
#: ``on_promotion``: a regular price is stated on promotional rows, so a full-price row's regular
#: is its price (the query's CASE). ``not_collected``: no regular price was ever captured, so none
#: is published, ``fields.regular`` is ``not_collected`` and promotions are off; a stored
#: price_type 'full' is not evidence of a full price. Every slot must be declared: no default.
#: Bloomingdale's: no list price on any of the 7,739 pages captured 3-5 Oct (Reviewer, 2026-10-08),
#: but the 9 Oct capture reads one on 90 markdowns, so a page without one is at full price. It
#: must agree with the importing shop's ``regular_stated`` (``pi_capture.feed.SHOPS``).
REGULAR_STATED: dict[str, Literal["on_promotion", "not_collected"]] = {
    "u": "on_promotion",
    "s": "on_promotion",
    "f": "on_promotion",
    "o": "on_promotion",
    "b": "on_promotion",
}
STATUS = {
    "ok": RetailerStatus.SUPPORTED,
    "partial": RetailerStatus.PARTIAL,
    "blocked": RetailerStatus.BLOCKED,
    "pending": RetailerStatus.PENDING,
}
PRODUCT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MATCH_STAGE = "first-pass"
#: Retailer breadcrumb levels published below the one-level code (Home is never stored).
CATEGORY_DEPTH = 3
#: Sephora's brand-navigation prefix ("BRANDS > Brands > <brand> > ..."): the brand is already
#: ``Product.brand``, so the path starts after it.
BRAND_NAV = ("BRANDS", "Brands")
#: Sephora-internal pseudo-crumbs that name no category.
NOT_A_CATEGORY = frozenset({"PID Unicity", "without_pid"})
#: Per retailer (register key, as in ``RETAILERS``, never the raw ``source.name``), the hosts whose
#: image URLs are published (owner decision: hotlinked from the retailer's own CDN only; decision
#: log 2026-10-01). Another retailer's host is never accepted.
IMAGE_HOSTS: dict[str, frozenset[str]] = {
    "sephora_me": frozenset({"img-product.sephora.me"}),
    "ulta_ae": frozenset({"media.alshaya.com"}),
    "faces_ae": frozenset({"www.faces.ae"}),
    # Verified on a saved Bloomingdale's page (.../on/demandware.static/-/Sites-bloomingdales-
    # master-catalog/...).
    "bloomingdales_ae": frozenset({"prodheadless.atgwasl.com"}),
    # Verified on the 10-03 capture (2026-10-07): all 139,173 image URLs of its 32,810 rows.
    "ounass_ae": frozenset({"ounass-ae.atgcdn.ae"}),
}
#: The retailer's "no image" placeholder (``.../images/noimagemedium.png``) is not a product image.
PLACEHOLDER_IMAGE = re.compile(r"/noimage[^/]*$", re.IGNORECASE)
#: Published prices outside this band are listed in the run log for a manual check (never changed).
PRICE_REVIEW_BAND = (Decimal(1), Decimal(3000))


def product_id(token: str) -> str:
    """The v1 id when it is a valid v2 id, else a stable hash of it (never a collision-prone
    character substitution)."""
    if PRODUCT_ID.fullmatch(token):
        return token
    return "p-" + hashlib.sha256(token.encode()).hexdigest()[:24]


@dataclass
class Stale:
    """Values not published because they were captured on another day than ``meta.dates`` (or,
    with crawl ``windows``, outside the retailer's window), and offers the windows' runs did not
    see (``retained``)."""

    day: date
    prices: int = 0
    regulars: int = 0
    stock: int = 0
    retained: int = 0
    #: Per retailer slot (``--run``, ADR-0013): a value counts when captured in its window, not
    #: on ``day``. ``None`` is the one-day rule.
    windows: Mapping[str, CrawlWindow] | None = None

    def on_day(self, moment: datetime) -> bool:
        return market_date(moment) == self.day

    def holds(self, shop: str, moment: datetime) -> bool:
        """``moment`` is a publishable capture of retailer slot ``shop``."""
        if self.windows is None:
            return self.on_day(moment)
        window = self.windows.get(shop)
        return window is not None and window.start <= moment <= window.end


@dataclass(frozen=True)
class Withheld:
    """Retailer slots exported WITHHELD (F1, ADR-0013 §8; Coordinator 01a11e1d-19a1): their offers
    keep the values of their own run (``--run``), but the body gives them no crawl window, so no
    cross-retailer gap is counted on their old captures. Each states ``since``, its window's last
    market day, and one whole-retailer ``notObserved`` entry with ``why`` runs from the day after
    ``since`` (or the cutoff day, if that is earlier) to ``until``: the roll-time cutoff day, or
    the body's own cutoff day when ``None``; never earlier than the latter."""

    slots: frozenset[str]
    why: Mapping[str, str]
    until: date | None = None


def market_date(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(MARKET.time_zone)).date()


def crawl_windows(
    rows: Sequence[ListingRow], runs: Mapping[str, Sequence[int]] | None = None
) -> dict[str, CrawlWindow]:
    """Each retailer slot's crawl window (ADR-0013): the first and last capture of the values its
    rows carry (price and stock captures; ``retained`` rows carry none). ``runs`` are the declared
    runs per source name (``--run``): the first is the window's run, the rest its segments, and a
    capture from any other run fails. Undeclared, a retailer's values must come from one run: two
    runs, even on adjacent days, are never merged into one window."""
    by_slot: dict[str, list[ListingRow]] = defaultdict(list)
    for row in rows:
        by_slot[row.retailer].append(row)
    windows = {}
    for slot, shop_rows in by_slot.items():
        name = RETAILERS[slot][0]
        captures = [
            capture
            for row in shop_rows
            if not row.retained
            for capture in (row.price_capture, row.stock_capture)
        ]
        used = {run for _, run in captures}
        if runs is None:
            if len(used) > 1:
                msg = f"{name}: values from runs {sorted(used)}; one run per retailer (ADR-0013)"
                raise ValueError(f"{msg}, pass --run to declare a run and its segments")
            declared = sorted(used)
        else:
            sources = sorted({row.source_name for row in shop_rows})
            declared = [run for source in sources for run in runs.get(source, ())]
            if not declared:
                raise ValueError(f"{name}: no --run declared for {', '.join(sources)}")
            if extra := used - set(declared):
                msg = f"{name}: values from runs {sorted(extra)} outside the declared {declared}"
                raise ValueError(msg)
        primary = [at for at, run in captures if run == declared[0]] if declared else []
        if not primary:
            raise ValueError(f"{name}: no capture of run {declared[:1] or '(none)'} in the rows")
        moments = [at for at, _ in captures]
        windows[slot] = CrawlWindow(
            start=min(moments),
            end=max(moments),
            run_id=str(declared[0]),
            segments=tuple(str(run) for run in declared[1:]),
        )
    return windows


def money(value: Decimal | None, currency: str) -> MoneyValue | None:
    """A positive price, or ``None`` (not observed). Zero or negative is not a price."""
    if value is None or value <= 0:
        return None
    return MoneyValue.of(value, currency)


def availability(value: str | None) -> AvailabilityState | None:
    if value is None or value == AvailabilityState.NOT_OBSERVED:
        return None
    return AvailabilityState(value)


def image(value: str | None, retailer: str) -> HttpUrl | None:
    """An absolute https URL on one of ``retailer``'s allowlisted hosts, without credentials or
    a fragment (even an empty trailing ``#``), that is not the retailer's placeholder; else None."""
    if not value:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or parts.hostname not in IMAGE_HOSTS.get(retailer, frozenset())
        or port not in (None, 443)
        or parts.username is not None
        or "#" in value
        or PLACEHOLDER_IMAGE.search(parts.path)
    ):
        return None
    return HttpUrl(value)


def breadcrumb(path: str | None) -> tuple[tuple[str, ...], frozenset[str]]:
    """The retailer's breadcrumb levels to publish (verbatim, at most ``CATEGORY_DEPTH``) and what
    was done to get them: ``internal`` (a pseudo-crumb dropped), ``brand_nav`` (the brand-navigation
    prefix dropped), ``truncated`` (levels below ``CATEGORY_DEPTH`` cut).

    A pseudo-crumb is removed wherever it sits: a path of pseudo-crumbs only gives no levels (the
    product is ``(code,)``), while one in the middle of a real path is spliced out and the levels
    around it are kept."""
    levels = [level.strip() for level in (path or "").split(" > ")]
    levels = [level for level in levels if level]
    notes: set[str] = set()
    if any(level in NOT_A_CATEGORY for level in levels):
        notes.add("internal")
        levels = [level for level in levels if level not in NOT_A_CATEGORY]
    if tuple(levels[: len(BRAND_NAV)]) == BRAND_NAV:
        notes.add("brand_nav")
        levels = levels[len(BRAND_NAV) + 1 :]
    if len(levels) > CATEGORY_DEPTH:
        notes.add("truncated")
    return tuple(levels[:CATEGORY_DEPTH]), frozenset(notes)


def category_path(row: ListingRow) -> tuple[str, ...]:
    """The one-level code, then the retailer's own breadcrumb (``breadcrumb``); no breadcrumb
    gives the code alone."""
    return (category_for(row), *breadcrumb(row.category_path)[0])


def category_notes(rows: Sequence[ListingRow]) -> dict[str, int]:
    """Per-run counts of the listings whose breadcrumb was cut or cleaned (for the run log, so a
    new pseudo-crumb or a deeper tree shows up instead of leaking through)."""
    counts = dict.fromkeys(("internal", "brand_nav", "truncated"), 0)
    for row in rows:
        for note in breadcrumb(row.category_path)[1]:
            counts[note] += 1
    return counts


def price_review(dataset: Dataset) -> dict[str, list[str]]:
    """The SKUs whose published price is below or above ``PRICE_REVIEW_BAND``, for the run log.
    A flag for a manual check against the stored page, never a change to the price."""
    low, high = PRICE_REVIEW_BAND
    review: dict[str, list[str]] = {"below": [], "above": []}
    for product in dataset.products:
        for offer in product.offers.values():
            price = offer.series.price[0]
            if price is None:
                continue
            amount = Decimal(price.amount)
            if amount < low:
                review["below"].append(offer.sku or product.id)
            elif amount > high:
                review["above"].append(offer.sku or product.id)
    return {side: sorted(skus) for side, skus in review.items()}


def offer(rows: Sequence[ListingRow], currency: str, stale: Stale) -> Offer:
    """Price and regular come from the price capture, stock from the stock observation's own
    capture (``stock_capture``); each is published only when captured on ``stale.day`` (or in
    the retailer's crawl window, ``stale.windows``). Stock is published only from the same market
    day as a published price (option A, ADR-0013). The evidence is the price capture when the
    price is published, else the stock observation.

    An offer whose rows are all ``retained`` (the window's runs did not see it) has no value and
    keeps its earlier capture as evidence: never a removal, never out of stock."""
    live = [row for row in rows if not row.retained]
    if not live:
        stale.retained += 1
        return retained_offer(rows, currency)
    rep = choose_representative(live)
    unit, size = rep.effective_size
    price_at, price_run_id = rep.price_capture
    stock_at, stock_run_id = rep.stock_capture
    price = money(rep.price, currency)
    collected = REGULAR_STATED[rep.retailer] == "on_promotion"
    # The query's CASE gives a stored 'full' row its own price as regular; anything else is a
    # stated regular, which a source declared not_collected cannot have.
    derived = rep.price_type == "full" and rep.regular == rep.price
    if not collected and rep.regular is not None and not derived:
        msg = f"{rep.source_name} {rep.source_listing_key}: a stated regular price on a source"
        raise ValueError(f"{msg} declared not_collected (REGULAR_STATED)")
    stated = money(rep.regular, currency) if collected else None
    if price is not None and not stale.holds(rep.retailer, price_at):
        price = None
        stale.prices += 1
        stale.regulars += stated is not None
    regular = stated if price is not None else None
    stock = None if rep.retailer in STOCK_NOT_PUBLISHED else availability(rep.availability)
    if stock is not None and not (
        stale.holds(rep.retailer, stock_at)
        and (price is None or market_date(stock_at) == market_date(price_at))
    ):
        stock = None
        stale.stock += 1
    captured, run_id = (price_at, price_run_id) if price is not None else (stock_at, stock_run_id)
    if rep.file_received_at is not None and captured == rep.file_received_at:
        msg = (
            f"{rep.source_name} {rep.source_listing_key}: dated by its feed file's import time "
            f"{captured.isoformat()}, not a capture time"
        )
        raise ValueError(msg)
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
        image=image(rep.image, RETAILERS[rep.retailer][0]),
    )


def retained_offer(rows: Sequence[ListingRow], currency: str) -> Offer:
    """An offer the crawl window's runs did not see: no value, its earlier row's capture as
    evidence (``to_v3`` marks it ``retained`` and covers it with a ``notObserved`` entry)."""
    rep = min(rows, key=lambda row: row.variant_id)
    unit, size = rep.effective_size
    captured, run_id = rep.price_capture
    return Offer(
        currency=currency,
        sku=rep.source_sku or rep.source_listing_key,
        url=HttpUrl(rep.url),
        size=Size(value=decimal_text(size), unit=unit) if unit and size and size > 0 else None,
        shade_count=len({row.shade for row in rows if row.shade}),
        rating=None,
        early=False,
        series=Series(
            price=(None,),
            regular=None,
            availability=(None,),
        ),
        evidence=Evidence(
            captured_at=captured,
            source=f"{rep.source_name} · local pi_db snapshot",
            run_id=str(run_id),
        ),
        image=image(rep.image, RETAILERS[rep.retailer][0]),
    )


def edge(match: MatchRow, keys: Sequence[GroupKey]) -> MatchEdge:
    """pi_db match_edge -> contract edge (docs/contracts/pi-dataset-v2.md rule 8), between the
    retailers of the pair's own two groups (``a`` < ``b``), never an assumed pair."""
    state = ReviewState(match.review_state)
    decided = None
    if state is not ReviewState.PROPOSED:
        decided = DecidedBy.HUMAN if match.human else DecidedBy.AUTO
    a, b = sorted(RETAILERS[key.retailer][0] for key in keys)
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


def pair_token(other: GroupKey, namer: GroupKey) -> str:
    """The id token of a matched pair's product (as in v1: ``m-<ulta>-<sephora>``)."""
    return f"m-{other.stable_token}-{namer.stable_token}"


def product(
    groups: Mapping[GroupKey, Sequence[ListingRow]],
    keys: Sequence[GroupKey],
    token: str,
    stale: Stale,
    matches: Sequence[MatchEdge] = (),
) -> Product:
    """One product: the first key's rows name it (the pair's namer: Sephora, as in v1)."""
    rows = groups[keys[0]]
    rep = choose_representative(rows)
    shade_families = sorted({row.shade_family for row in rows if row.shade_family})
    attributes: dict[str, Any] = {"shadeFamilies": shade_families} if shade_families else {}
    # one concentration across every offer's rows, or none: a conflict is never resolved here,
    # and a value outside pi_core's Concentration (e.g. "eau fraiche") is never published
    concentrations = {
        c.lower() for key in keys for row in groups[key] if (c := _text(row.concentration))
    }
    if len(concentrations) == 1 and concentrations <= {c.value for c in Concentration}:
        attributes["concentration"] = concentrations.pop()
    offers = {
        RETAILERS[key.retailer][0]: offer(groups[key], MARKET.currency, stale) for key in keys
    }
    return Product(
        id=product_id(token),
        brand=rep.brand,
        name=rep.name,
        category=category_path(rep),
        unit=keys[0].size_unit,
        offers=offers,
        matches=tuple(matches),
        shades=tuple(sorted({row.shade_hex.lower() for row in rows if row.shade_hex})[:12]),
        attributes=attributes,
        # the naming offer's thumbnail, else the first other offer that has one
        image=next((o.image for o in offers.values() if o.image is not None), None),
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


def listed_slots(rows: Sequence[ListingRow], ulta_early: Sequence[Any] = ()) -> tuple[str, ...]:
    """Ulta and Sephora as before (Ulta's status is the owner's statement, listed without rows),
    plus any other slot with rows. A file of other slots only lists just those."""
    present = {row.retailer for row in rows}
    legacy = bool(present & {"u", "s"}) or bool(ulta_early) or not present
    return tuple(s for s in RETAILERS if (legacy and s in {"u", "s"}) or s in present)


def incomplete_status(rows: Sequence[ListingRow], shop: str) -> RetailerStatus:
    """An ``INCOMPLETE_CATALOGUE`` retailer: ``partial`` with rows (its runs never make it
    ``supported``), ``pending`` without."""
    if retailer_status(rows, shop) == "pending":
        return RetailerStatus.PENDING
    return RetailerStatus.PARTIAL


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
    slots: Sequence[str] | None = None,
    windows: Mapping[str, CrawlWindow] | None = None,
    withheld: Withheld | None = None,
) -> Dataset:
    """``ulta_note`` is v1's ``meta.retailers[u].note``, so both versions say the same thing.

    ``slots`` are the retailers listed in ``meta.retailers`` (``listed_slots`` by default): a
    per-source file (ADR-0010) lists only its own, e.g. ``("f",)`` for the Faces file.

    ``windows`` (``crawl_windows``, ADR-0013) publish each retailer's values captured in its
    crawl window instead of only those of the cutoff's day; ``to_v3`` writes them. ``withheld``
    slots still publish the values of their window but state ``since`` and a ``notObserved``
    entry instead (``Withheld``); ``to_v3`` then gives them no window."""
    if not rows and not ulta_early:
        raise ValueError("refusing to create an empty demo dataset")
    captures = [row.evidence_retrieved_at or row.observed_at for row in rows]
    captures += [parse_utc(p["offers"]["u"]["evidence"]["capturedAt"]) for p in ulta_early]
    captures += [w.end for w in (windows or {}).values()]
    cutoff = max(captures)
    zone = ZoneInfo(MARKET.time_zone)
    day = cutoff.astimezone(zone).date()
    stale = Stale(day, windows=windows)

    groups = group_rows(tidy_rows(rows))
    pairs, unpaired = pair_groups(groups, matches)
    products = [
        product(
            groups,
            (namer, other),
            pair_token(other, namer),
            stale,
            (edge(match, (namer, other)),),
        )
        for other, namer, match in pairs
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
    with_image = sum(p.image is not None for p in products)

    listed = listed_slots(rows, ulta_early) if slots is None else tuple(slots)
    # The owner's statement, not row presence: rows from before the block must not hide it.
    ulta_status = RetailerStatus.BLOCKED if ulta.blocked else STATUS[retailer_status(rows, "u")]
    candidates = [
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
    candidates += [
        Retailer(
            id=RETAILERS[shop][0],
            name=RETAILERS[shop][1],
            country=MARKET.country,
            status=incomplete_status(rows, shop),
            since=None,
            note=None,
        )
        for shop in RETAILERS
        if shop in INCOMPLETE_CATALOGUE
    ]
    by_id = {r.id: r for r in candidates}
    retailers = [by_id[RETAILERS[shop][0]] for shop in RETAILERS if shop in listed]
    not_observed: tuple[NotObserved, ...] = ()
    if "u" in listed and ulta_status is RetailerStatus.BLOCKED:
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
    if withheld is not None:
        if "u" in withheld.slots and ulta_status is RetailerStatus.BLOCKED:
            raise ValueError("ulta_ae is blocked by ruling: it cannot also be withheld")
        retailers, held = withhold(retailers, withheld, windows, day)
        not_observed = (*not_observed, *held)
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
            images=with_image > 0,
            ratings=has_rating,
        ),
        fields={
            "price": status_of(
                "parse_failure"
                if bad_prices and not has_price and not stale.prices
                else "partial"
                if bad_prices or stale.prices or stale.retained
                else "ok"
                if has_price
                else "not_collected"
            ),
            "regular": status_of(
                "partial"
                if stale.regulars or (stale.retained and has_regular)
                else "ok"
                if has_regular
                else "not_collected"
            ),
            "stock": status_of(
                "partial"
                if stale.stock or (stale.retained and has_stock)
                else "ok"
                if has_stock
                else "not_collected"
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
            "image": status_of(
                "ok"
                if with_image == len(products)
                else "partial"
                if with_image
                else "not_collected"
            ),
        },
        producer=Producer(name="demo_export", version="2", commit=producer_commit),
        test=False,
    )
    return Dataset(
        schema_id="pi.dataset/v2", meta=meta, products=tuple(products), not_observed=not_observed
    )


def withhold(
    retailers: Sequence[Retailer],
    withheld: Withheld,
    windows: Mapping[str, CrawlWindow] | None,
    day: date,
) -> tuple[list[Retailer], list[NotObserved]]:
    """``retailers`` with each ``withheld`` slot's ``since`` set, and its whole-retailer entries
    (``Withheld``). A withheld slot that is not listed, or has no window to take ``since`` from,
    is refused: a withheld retailer is never guessed."""
    slot_of = {rid: slot for slot, (rid, _) in RETAILERS.items()}
    listed = {slot_of[r.id] for r in retailers}
    if missing := sorted(withheld.slots - listed):
        raise ValueError(f"withheld {missing}: not a listed retailer of this export")
    until = day if withheld.until is None else withheld.until
    if until < day:
        raise ValueError(f"withheld until {until}: before the cutoff day {day}")
    out: list[Retailer] = []
    entries: list[NotObserved] = []
    for r in retailers:
        slot = slot_of[r.id]
        if slot not in withheld.slots:
            out.append(r)
            continue
        window = (windows or {}).get(slot)
        if window is None:
            raise ValueError(f"{r.id}: withheld with no crawl window (--run) to take since from")
        since = market_date(window.end)
        out.append(r.model_copy(update={"since": since}))
        entries.append(
            NotObserved(
                retailer=r.id,
                start=min(since + timedelta(days=1), day),
                end=until,
                categories=None,
                why=with_since(withheld.why, since),
            )
        )
    return out, entries


#: The withhold reason's date placeholder, filled with the slot's own ``since`` (Coordinator
#: 01a11e53-59d7): the note's date and the row's ``since`` are one value by construction.
SINCE = "<since>"
MONTHS = {
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
    "ar": (
        "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
        "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
    ),
}  # fmt: skip


def with_since(why: Mapping[str, str], since: date) -> dict[str, str]:
    """``why`` with each ``<since>`` written as ``since`` in its language ("1 October 2026",
    "1 أكتوبر 2026", ASCII digits). Any other ``<``/``>`` left is refused: nothing downstream
    fills a placeholder, so one would be served as-is."""
    out = {
        lang: text.replace(SINCE, f"{since.day} {MONTHS[lang][since.month - 1]} {since.year}")
        for lang, text in why.items()
    }
    if left := {lang: t for lang, t in out.items() if "<" in t or ">" in t}:
        raise ValueError(f"withhold reason has an unfilled placeholder: {left}")
    return out


def offer_rows(
    rows: Sequence[ListingRow], matches: Sequence[MatchRow]
) -> dict[tuple[str, str], Sequence[ListingRow]]:
    """The listing rows of each collected offer, by (product id, retailer id): the grouping and
    pairing ``build_dataset_v2`` uses, so every collected offer has its rows."""
    groups = group_rows(rows)
    pairs, unpaired = pair_groups(groups, matches)
    owned: list[tuple[tuple[GroupKey, ...], str]] = [
        ((namer, other), pair_token(other, namer)) for other, namer, _ in pairs
    ]
    owned += [((key,), key.stable_token) for key in unpaired]
    return {
        (product_id(token), RETAILERS[key.retailer][0]): groups[key]
        for keys, token in owned
        for key in keys
    }


def listing_counts(
    rows: Sequence[ListingRow], matches: Sequence[MatchRow]
) -> dict[tuple[str, str], int]:
    """Listing rows per collected offer, by (product id, retailer id)."""
    return {key: len(group) for key, group in offer_rows(rows, matches).items()}


def _text(value: str | None) -> str | None:
    """Edge-trimmed text; blank is absent, never an empty value."""
    text = value.strip() if value is not None else ""
    return text or None


def _gtin(value: str | None) -> str | None:
    """The stored barcode when it is a valid GTIN; an invalid one is dropped (as offline_import)."""
    return value if value is not None and is_valid_gtin(value) else None


def _gallery(row: ListingRow) -> tuple[HttpUrl, ...]:
    """The row's gallery on the retailer's own hosts, page order, each URL once."""
    urls = (image(url, RETAILERS[row.retailer][0]) for url in row.images)
    return tuple(dict.fromkeys(url for url in urls if url is not None))


def captured_fields(rows: Sequence[ListingRow]) -> dict[str, tuple[ContentField, ...]]:
    """Per retailer id, the content fields any of its exported rows carries. A field no row of a
    retailer has is *not captured* from it; one that some rows have is *not published* where a
    row lacks it (Reviewer, 2026-10-03)."""
    has: dict[str, set[ContentField]] = {rid: set() for rid, _ in RETAILERS.values()}
    for row in rows:
        fields = has[RETAILERS[row.retailer][0]]
        fields.update(
            field
            for field, value in (
                (ContentField.DESCRIPTION, _text(row.description)),
                (ContentField.INGREDIENTS, _text(row.ingredients)),
                (ContentField.IMAGES, _gallery(row)),
                (ContentField.SHADE, _text(row.shade)),
                (ContentField.GTIN, _gtin(row.gtin)),
            )
            if value
        )
    return {rid: tuple(f for f in ContentField if f in fields) for rid, fields in has.items()}


def content(rows: Sequence[ListingRow], captured: tuple[ContentField, ...]) -> OfferContent:
    """One offer's page content. Description, ingredients and gallery are the representative
    row's (the listing the offer's price is from); description and ingredients fall back to the
    first other row, by sku, that has them. Variants are every row of the offer, by sku."""
    rep = choose_representative(rows)
    ordered = [rep, *sorted((r for r in rows if r is not rep), key=_sku)]
    return OfferContent(
        captured=captured,
        description=next((t for r in ordered if (t := _text(r.description))), None),
        ingredients=next((t for r in ordered if (t := _text(r.ingredients))), None),
        images=_gallery(rep),
        variants=tuple(
            OfferVariant(sku=_sku(r), shade=_text(r.shade), gtin=_gtin(r.gtin))
            for r in sorted(rows, key=_sku)
        ),
        family=rep.family_id,
    )


def _sku(row: ListingRow) -> str:
    return row.source_sku or row.source_listing_key


#: The ``why`` of the ``notObserved`` entry covering offers marked with a reason (ADR-0013).
NOT_OBSERVED_WHY = {
    NotObservedReason.RETAINED: {
        "en": (
            "Not seen by this crawl run: listed from an earlier run with no value. "
            "Not a removal and not out of stock."
        ),
        "ar": (
            "لم يرصدها تشغيل الزحف هذا: مدرجة من تشغيل سابق دون أي قيمة. "
            "ليست إزالة ولا نفادًا للمخزون."
        ),
    },
}


#: The beauty profile versions this export writes (``--profile beauty@<n>``).
BEAUTY_VERSIONS = (1, 2)

#: Under an evidence profile (beauty@2 on, ADR-0008 §5), the keys this export can show the
#: source of: the gift titles are the page's own text, stored as read. No other key is stored
#: with its source text (the concentration label and the shade family are stored as values only),
#: so each is published as not collected rather than with evidence it does not have.
EVIDENCED_KEYS = frozenset({"giftWithPurchase"})


def to_v3(  # noqa: PLR0913 - #310's positional withheld, then the keyword-only profile
    v2: Dataset,
    rows: Sequence[ListingRow],
    matches: Sequence[MatchRow],
    windows: Mapping[str, CrawlWindow] | None = None,
    withheld: frozenset[str] = frozenset(),
    *,
    beauty: int = 1,
) -> DatasetV3:
    """``v2`` upgraded under ``beauty@<beauty>`` (default 1), each collected offer with its
    ``listingCount`` and ``content``; an early (recon) offer's stay ``null``. The caller validates
    the dump with ``load_any``.

    A snapshot (one date) also states each retailer's own ``fields`` and ``capabilities`` (never
    the roll-up of ``meta.fields``, ADR-0013) and its crawl ``window`` from ``windows`` (the ones
    ``build_dataset_v2`` used). An offer whose rows are all retained is marked ``retained`` and
    covered by one ``notObserved`` entry per retailer, context and reason: the window's market
    dates and the marked products' categories. A ``withheld`` slot (``Withheld``) gets no window:
    its values are still counted against its own window in its ``fields``.

    From ``beauty@2`` every value carries its evidence: a key outside ``EVIDENCED_KEYS`` is
    declared not collected and its v2 values are left out, and each offer's gift titles (its
    representative row's) are its ``giftWithPurchase``, with the page as their evidence."""
    profile = evidence_profile(beauty)
    evidenced = beauty >= BEAUTY_EVIDENCE_FROM
    if evidenced:
        v2 = v2.model_copy(
            update={"products": tuple(p.model_copy(update={"attributes": {}}) for p in v2.products)}
        )
    grouped = offer_rows(rows, matches)
    captured = captured_fields(rows)
    v3 = upgrade(v2, profile)
    products = tuple(
        p.model_copy(
            update={
                "offers": {
                    cid: o
                    if o.early
                    else o.model_copy(
                        update={
                            "listing_count": len(grouped[p.id, cid]),
                            "content": content(grouped[p.id, cid], captured[cid]),
                            "not_observed_reason": NotObservedReason.RETAINED
                            if all(row.retained for row in grouped[p.id, cid])
                            else None,
                        }
                        | (gift_attributes(grouped[p.id, cid]) if evidenced else {})
                    )
                    for cid, o in p.offers.items()
                }
            }
        )
        for p in v3.products
    )
    slot_of = {rid: slot for slot, (rid, _) in RETAILERS.items()}
    retailer_of = {c.id: c.retailer for c in v3.meta.contexts}
    marked: dict[tuple[str, str, NotObservedReason], set[str]] = defaultdict(set)
    for p in products:
        for cid, o in p.offers.items():
            if o.not_observed_reason is not None:
                marked[retailer_of[cid], cid, o.not_observed_reason].add(p.category[0])
    covering = []
    for (rid, cid, reason), categories in sorted(marked.items()):
        window = (windows or {}).get(slot_of[rid])
        if window is None:
            raise ValueError(f"{rid}: offers marked {reason} without a crawl window (--run)")
        covering.append(
            NotObservedV3(
                retailer=rid,
                context=cid,
                start=market_date(window.start),
                end=market_date(window.end),
                categories=tuple(sorted(categories)),
                why=NOT_OBSERVED_WHY[reason],
            )
        )
    meta = v3.meta
    if len(v2.meta.dates) == 1:
        states = retailer_states(v2, grouped, windows)
        meta = meta.model_copy(
            update={
                "retailers": tuple(
                    r.model_copy(
                        update={
                            "window": None
                            if slot_of[r.id] in withheld
                            else (windows or {}).get(slot_of[r.id]),
                            "fields": states[r.id][0],
                            "capabilities": states[r.id][1],
                        }
                    )
                    for r in meta.retailers
                )
            }
        )
    return v3.model_copy(
        update={
            "meta": meta,
            "products": products,
            "not_observed": (*v3.not_observed, *covering),
        }
    )


def evidence_profile(beauty: int) -> ProfileDeclaration:
    """The committed ``beauty@<beauty>``; from the evidence version on, every key outside
    ``EVIDENCED_KEYS`` declared not collected (a snapshot may turn a capability off, never on)."""
    if beauty not in BEAUTY_VERSIONS:
        raise ValueError(f"beauty@{beauty}: this export writes {BEAUTY_VERSIONS}")
    profile = committed_profile("beauty", beauty)
    if profile is None:  # pragma: no cover - the profiles are committed with pi_dataset
        raise ValueError(f"beauty@{beauty} is not a committed profile")
    if beauty < BEAUTY_EVIDENCE_FROM:
        return profile
    return profile.model_copy(
        update={
            "attribute_set": tuple(
                a if a.key in EVIDENCED_KEYS else a.model_copy(update={"capability": False})
                for a in profile.attribute_set
            )
        }
    )


def gift_attributes(rows: Sequence[ListingRow]) -> dict[str, Any]:
    """An offer's ``giftWithPurchase`` and its evidence: the representative row's gift titles
    (the listing its price is from), as the page states them. No titles, no key: a page without
    a gift and one whose promotions were not read both leave it out."""
    titles = list(choose_representative(rows).gift_with_purchase)
    if not titles:
        return {}
    evidence = AttributeEvidence(
        source=AttributeSource.PAGE,
        field="gift_with_purchase",
        excerpt=" | ".join(titles)[:EXCERPT_MAX],
        rule=None,
    )
    return {
        "attributes": {"giftWithPurchase": titles},
        "attribute_evidence": {"giftWithPurchase": evidence},
    }


def retailer_states(
    v2: Dataset,
    grouped: Mapping[tuple[str, str], Sequence[ListingRow]],
    windows: Mapping[str, CrawlWindow] | None,
) -> dict[str, tuple[dict[str, FieldStatus], Capabilities]]:
    """Each listed retailer's field states and capabilities from its own offers alone, with the
    rules of ``meta.fields``: its offers are rebuilt from their rows to count what its window (or
    the day) left out."""
    stale = {r.id: Stale(v2.meta.dates[-1], windows=windows) for r in v2.meta.retailers}
    offers: dict[str, list[Offer]] = {r.id: [] for r in v2.meta.retailers}
    bad: dict[str, int] = defaultdict(int)
    for p in v2.products:
        for rid, o in p.offers.items():
            offers[rid].append(o)
            if not o.early:
                group = grouped[p.id, rid]
                offer(group, o.currency, stale[rid])
                bad[rid] += sum(1 for row in group if row.price is not None and row.price <= 0)
    return {rid: _states(offers[rid], stale[rid], bad[rid]) for rid in offers}


def _states(
    offers: Sequence[Offer], stale: Stale, bad_prices: int
) -> tuple[dict[str, FieldStatus], Capabilities]:
    collected = [o for o in offers if not o.early]
    has_price = any(o.series.price[0] is not None for o in collected)
    has_regular = any(o.series.regular is not None for o in collected)
    has_stock = any((o.series.availability or (None,))[0] is not None for o in collected)
    sized = sum(o.size is not None for o in offers)
    has_shades = any(o.shade_count for o in offers)
    has_rating = any(o.rating is not None for o in offers)
    with_image = sum(o.image is not None for o in offers)
    fields = {
        "price": "parse_failure"
        if bad_prices and not has_price and not stale.prices
        else "partial"
        if bad_prices or stale.prices or stale.retained
        else "ok"
        if has_price
        else "not_collected",
        "regular": "partial"
        if stale.regulars or (stale.retained and has_regular)
        else "ok"
        if has_regular
        else "not_collected",
        "stock": "partial"
        if stale.stock or (stale.retained and has_stock)
        else "ok"
        if has_stock
        else "not_collected",
        "size": "ok"
        if offers and sized == len(offers)
        else "partial"
        if sized
        else "not_published",
        "shades": "ok" if has_shades else "not_collected",
        "rating": "ok" if has_rating else "not_collected",
        "gtin": "not_published",
        "image": "ok"
        if offers and with_image == len(offers)
        else "partial"
        if with_image
        else "not_collected",
    }
    capabilities = Capabilities(
        history=False,
        promotions=has_regular,
        campaigns=False,
        stock=has_stock,
        sizes=sized > 0,
        shades=has_shades,
        coverage=False,
        images=with_image > 0,
        ratings=has_rating,
    )
    return {name: status_of(state) for name, state in fields.items()}, capabilities
