"""Build a multi-day ``pi.dataset/v2`` (``--history``) from every crawl day in pi_db.

The single-day snapshot (``build_dataset_v2``) stays the default and is unchanged; this mode is
opt-in. It answers the history views (Launches first): ``meta.dates`` holds every market day on
which an exported retailer was observed, and each offer's series has one value per date.

- **Market days.** A date is the Dubai-local day of the observation (``MARKET.time_zone``),
  never a UTC ``.date()``: an observation at 21:30Z is the next day in Dubai.
- **No carry-forward.** A date's values come only from that day's observations
  (``latest_params`` with the day's bounds). A listing not observed that day is ``null`` there;
  nothing is padded or repeated from another day.
- **Complete days.** A retailer's day is complete when each of its contexts has a succeeded run
  whose observations all fall on that day, with coverage ``supported``. Every date on which a
  retailer is not complete is inside a ``notObserved`` window for it: not collected at all, or
  only partly (an incremental refresh, a blocked or cut-short pass). The metric layer then never
  reads a product missing that day as a removal or a launch (``pi_metrics.view.complete_run``).
- **Since.** A retailer whose latest date is complete is ``supported`` from its first complete
  date (``since``). Status is dataset-wide and read at the latest date, so a retailer whose
  latest date is not complete keeps the status the snapshot rules give it, and backs no absence
  claim. A blocked retailer keeps the owner's statement and window; every other date of it that
  is not complete gets a window too.
- **History** is true only with at least two dates.

Identity (product ids, names, pairing) comes from each listing's latest row, through the same
grouping and pairing as the snapshot, so a product keeps its id from day to day.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from pi_dataset import (
    Dataset,
    FieldStatus,
    MatchEdge,
    NotObserved,
    Offer,
    Product,
    Retailer,
    RetailerStatus,
    Series,
)
from scripts.demo_export.export import (
    LATEST_LISTINGS_SQL,
    MATCHES_SQL,
    GroupKey,
    ListingRow,
    MatchRow,
    UltaContext,
    group_rows,
    in_sources,
    latest_params,
    pair_groups,
    psycopg_database_url,
    slot,
)
from scripts.demo_export.tidy import tidy_rows
from scripts.demo_export.v2 import (
    INCOMPLETE_CATALOGUE,
    MARKET,
    RETAILERS,
    Stale,
    build_dataset_v2,
    edge,
    offer,
    pair_token,
    product,
)

#: Per run: its context, status and the span of its observations (history mode only reads
#: succeeded and partial runs; failed, aborted and running ones are never read).
RUN_SPANS_SQL = """
SELECT
  s.name AS source_name,
  cr.source_context_id AS context_id,
  cr.id AS run_id,
  cr.status::text AS status,
  sc.coverage_status::text AS coverage_status,
  min(o.observed_at) AS first_at,
  max(o.observed_at) AS last_at
FROM crawl_run cr
JOIN source_context sc ON sc.id = cr.source_context_id
JOIN source s ON s.id = sc.source_id
JOIN offer_observation o ON o.crawl_run_id = cr.id
WHERE sc.country = 'AE'
  AND sc.locale = 'en-AE'
  AND s.name = ANY(%(sources)s)
  AND cr.status IN ('succeeded', 'partial')
  AND (o.currency = 'AED' OR o.currency IS NULL)
GROUP BY s.name, cr.source_context_id, cr.id, cr.status, sc.coverage_status
ORDER BY s.name, cr.source_context_id, min(o.observed_at), cr.id
"""

NOT_COLLECTED_WHY = {
    "en": "Not collected on this day: a product missing here is not a removal or a launch.",
    "ar": "لم تُجمع البيانات في هذا اليوم: المنتج الغائب فيه لا يُعدّ إزالةً ولا إطلاقاً.",
}
PARTIAL_WHY = {
    "en": (
        "Collection was incomplete on this day: a product missing here is not a removal or a"
        " launch."
    ),
    "ar": "كان الجمع غير مكتمل في هذا اليوم: المنتج الغائب فيه لا يُعدّ إزالةً ولا إطلاقاً.",
}


def market_day(moment: datetime) -> date:
    """The Dubai-local day of ``moment`` (a timezone-aware time)."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(ZoneInfo(MARKET.time_zone)).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """The market day as ``[start, end)``: local midnight to the next local midnight."""
    zone = ZoneInfo(MARKET.time_zone)
    start = datetime.combine(day, time(), zone)
    return start, datetime.combine(day + timedelta(days=1), time(), zone)


@dataclass(frozen=True)
class RunSpan:
    source_name: str
    context_id: int
    run_id: int
    status: str
    coverage_status: str
    first_at: datetime
    last_at: datetime

    @property
    def days(self) -> list[date]:
        first, last = market_day(self.first_at), market_day(self.last_at)
        return [first + timedelta(days=n) for n in range((last - first).days + 1)]

    @property
    def complete_day(self) -> date | None:
        """The one day this run covers completely, if it does."""
        first, last = market_day(self.first_at), market_day(self.last_at)
        if self.status == "succeeded" and self.coverage_status == "supported" and first == last:
            return first
        return None


@dataclass(frozen=True)
class Coverage:
    """Per slot: the market days it was observed on, and those it was completely observed. An
    ``INCOMPLETE_CATALOGUE`` slot (Faces) is never complete, whatever its runs say."""

    observed: Mapping[str, frozenset[date]] = field(default_factory=dict)
    complete: Mapping[str, frozenset[date]] = field(default_factory=dict)

    @classmethod
    def of(cls, spans: Iterable[RunSpan]) -> Coverage:
        observed: dict[str, set[date]] = {}
        contexts: dict[str, set[int]] = {}
        complete: dict[tuple[str, int], set[date]] = {}
        for span in spans:
            shop = slot(span.source_name)
            observed.setdefault(shop, set()).update(span.days)
            contexts.setdefault(shop, set()).add(span.context_id)
            day = None if shop in INCOMPLETE_CATALOGUE else span.complete_day
            if day is not None:
                complete.setdefault((shop, span.context_id), set()).add(day)
        return cls(
            observed={shop: frozenset(days) for shop, days in observed.items()},
            complete={
                # complete only where every context of the retailer was
                shop: frozenset.intersection(
                    *(frozenset(complete.get((shop, c), ())) for c in sorted(ids))
                )
                for shop, ids in contexts.items()
            },
        )


def load_history(
    database_url: str, sources: Sequence[str]
) -> tuple[list[RunSpan], dict[date, list[ListingRow]], list[MatchRow]]:
    """The runs, each observed market day's rows (that day's observations only) and matches."""
    with psycopg.connect(psycopg_database_url(database_url), row_factory=dict_row) as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            return read_history(cursor, sources)


def read_history(
    cursor: psycopg.Cursor[dict[str, Any]], sources: Sequence[str]
) -> tuple[list[RunSpan], dict[date, list[ListingRow]], list[MatchRow]]:
    cursor.execute(RUN_SPANS_SQL, {"sources": list(sources)})
    spans = [RunSpan(**row) for row in cursor.fetchall()]
    days: dict[date, list[ListingRow]] = {}
    for day in sorted({d for span in spans for d in span.days}):
        cursor.execute(LATEST_LISTINGS_SQL, latest_params(sources, day_bounds(day)))
        days[day] = in_sources([ListingRow(**row) for row in cursor.fetchall()], sources)
    cursor.execute(MATCHES_SQL)
    return spans, days, [MatchRow(**row) for row in cursor.fetchall()]


def latest_rows(days: Mapping[date, Sequence[ListingRow]]) -> list[ListingRow]:
    """Each listing's row from the last day it was observed: what names and pairs it."""
    latest: dict[tuple[str, str], ListingRow] = {}
    for day in sorted(days):
        for row in days[day]:
            latest[(row.source_name, row.source_listing_key)] = row
    return list(latest.values())


def listing(row: ListingRow) -> tuple[str, str]:
    return row.source_name, row.source_listing_key


def history_offer(
    daily: Sequence[Sequence[ListingRow]], dates: Sequence[date], stale: Sequence[Stale]
) -> Offer:
    """One offer over every date: each day's value from that day's rows only (``null`` where
    the offer was not observed); the rest (url, size, rating, evidence) from its last day."""
    per_day = [
        offer(rows, MARKET.currency, stale[i]) if rows else None for i, rows in enumerate(daily)
    ]
    last = next(o for o in reversed(per_day) if o is not None)
    price = tuple(o.series.price[0] if o is not None else None for o in per_day)
    regular = tuple(
        o.series.regular[0] if o is not None and o.series.regular is not None else None
        for o in per_day
    )
    stock = tuple(
        o.series.availability[0] if o is not None and o.series.availability is not None else None
        for o in per_day
    )
    assert len(price) == len(dates)  # noqa: S101 - one value per date, by construction
    series = Series(
        price=price,
        regular=regular if any(m is not None for m in regular) else None,
        availability=stock,
    )
    return last.model_copy(update={"series": series})


def windows(
    retailer: Retailer,
    shop: str,
    dates: Sequence[date],
    cover: Coverage,
    covered: frozenset[date] = frozenset(),
) -> list[NotObserved]:
    """``notObserved`` windows over each run of consecutive dates on which ``shop`` was not
    completely observed; one window per reason (not collected, or only partly). Dates in
    ``covered`` already have a window (a blocked retailer's) and get no second one."""
    observed = cover.observed.get(shop, frozenset())
    complete = cover.complete.get(shop, frozenset())
    out: list[NotObserved] = []
    run: list[date] = []
    why: dict[str, str] | None = None
    for day in [*dates, None]:
        reason = (
            None
            if day is None or day in complete or day in covered
            else PARTIAL_WHY
            if day in observed
            else NOT_COLLECTED_WHY
        )
        if run and why is not None and reason != why:  # a run always has its reason
            out.append(
                NotObserved(
                    retailer=retailer.id, start=run[0], end=run[-1], categories=None, why=why
                )
            )
            run = []
        if reason is not None and day is not None:
            run.append(day)
        why = reason
    return out


def field_status(has: bool, stale: int, bad: int = 0) -> FieldStatus:
    if bad and not has and not stale:
        return FieldStatus.PARSE_FAILURE
    if bad or stale:
        return FieldStatus.PARTIAL
    return FieldStatus.OK if has else FieldStatus.NOT_COLLECTED


def build_history_v2(  # noqa: PLR0913 - mirrors build_dataset_v2 plus the coverage
    days: Mapping[date, Sequence[ListingRow]],
    cover: Coverage,
    matches: Sequence[MatchRow],
    *,
    generated_at: datetime,
    ulta: UltaContext,
    ulta_note: Mapping[str, str],
    scope: str = "beauty",
    producer_commit: str | None = None,
    slots: Sequence[str] | None = None,
) -> Dataset:
    """The multi-day v2 dataset. ``days`` maps each market day to that day's rows only; a day
    with no rows is not a date."""
    for day, rows in days.items():
        wrong = {market_day(r.observed_at) for r in rows} - {day}
        if wrong:
            raise ValueError(f"rows filed under {day} were observed on {sorted(wrong)}")
    dates = tuple(sorted(day for day, rows in days.items() if rows))
    latest = latest_rows(days)
    # The snapshot of each listing's latest row: same ids, names, pairing, retailers and fields.
    base = build_dataset_v2(
        latest,
        matches,
        generated_at=generated_at,
        ulta=ulta,
        ulta_note=ulta_note,
        scope=scope,
        producer_commit=producer_commit,
        slots=slots,
    )
    groups = group_rows(tidy_rows(latest))
    key_of = {listing(row): key for key, rows in groups.items() for row in rows}
    per_key: dict[GroupKey, list[list[ListingRow]]] = {key: [[] for _ in dates] for key in groups}
    for i, day in enumerate(dates):
        for row in days[day]:
            per_key[key_of[listing(row)]][i].append(row)
    stale = [Stale(day) for day in dates]
    naming = Stale(dates[-1])  # product() names from the latest rows; its offers are replaced

    def built(keys: tuple[GroupKey, ...], token: str, edges: Sequence[MatchEdge] = ()) -> Product:
        named = product(groups, keys, token, naming, edges)
        offers = {
            RETAILERS[key.retailer][0]: history_offer(per_key[key], dates, stale) for key in keys
        }
        return named.model_copy(update={"offers": offers})

    pairs, unpaired = pair_groups(groups, matches)
    products = [
        built((namer, other), pair_token(other, namer), (edge(match, (namer, other)),))
        for other, namer, match in pairs
    ]
    products += [built((key,), key.stable_token) for key in unpaired]
    products.sort(key=lambda p: p.id)
    if [p.id for p in products] != [p.id for p in base.products]:  # pragma: no cover - guard
        raise ValueError("history products differ from the snapshot's")

    offers = [o for p in products for o in p.offers.values()]
    has_price = any(m is not None for o in offers for m in o.series.price)
    has_regular = any(o.series.regular is not None for o in offers)
    has_stock = any(s is not None for o in offers for s in (o.series.availability or ()))
    bad = sum(1 for rows in days.values() for r in rows if r.price is not None and r.price <= 0)

    slot_of = {key: shop for shop, (key, _) in RETAILERS.items()}
    retailers = []
    not_observed = list(base.not_observed)
    for listed in base.meta.retailers:
        shop = slot_of[listed.id]
        if listed.status is RetailerStatus.BLOCKED:
            # The owner's statement and its window stand; any other date not completely
            # observed gets its own window, so no date of a blocked retailer is left open.
            retailers.append(listed)
            covered = frozenset(
                d
                for w in base.not_observed
                if w.retailer == listed.id and w.categories is None
                for d in dates
                if w.start <= d <= w.end
            )
            not_observed += windows(listed, shop, dates, cover, covered)
            continue
        complete = sorted(cover.complete.get(shop, frozenset()) & set(dates))
        # Status is dataset-wide and metrics read it at the latest date (promotions gates on it
        # at as_of), so only a complete latest day makes the retailer supported; without one, a
        # snapshot status of supported (read off the rows) is lowered to partial.
        if dates[-1] in complete:
            update = {"status": RetailerStatus.SUPPORTED, "since": complete[0]}
        elif listed.status is RetailerStatus.SUPPORTED:
            update = {"status": RetailerStatus.PARTIAL, "since": None}
        else:
            update = {}
        shop_info = listed.model_copy(update=update) if update else listed
        retailers.append(shop_info)
        not_observed += windows(shop_info, shop, dates, cover)

    meta = base.meta.model_copy(
        update={
            "dates": dates,
            "retailers": tuple(retailers),
            "capabilities": base.meta.capabilities.model_copy(
                update={
                    "history": len(dates) >= 2,
                    "promotions": has_regular,
                    "stock": has_stock,
                }
            ),
            "fields": dict(base.meta.fields)
            | {
                "price": field_status(has_price, sum(s.prices for s in stale), bad),
                "regular": field_status(has_regular, sum(s.regulars for s in stale)),
                "stock": field_status(has_stock, sum(s.stock for s in stale)),
            },
        }
    )
    # Dataset() runs every contract rule again on the new dates, series and windows.
    return Dataset(
        schema_id="pi.dataset/v2",
        meta=meta,
        products=tuple(products),
        not_observed=tuple(not_observed),
    )
