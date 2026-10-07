"""Write a validated feed into pi_db: append-only and idempotent, like the snapshot loaders.

One import = one crawl_run (rung 0) with one evidence row for the file (fetch_method
``offline_import``, content_hash = the file's sha256). Grain: one source_listing per listing
key (the feed's SKU/variant key), one listing_content and one offer_observation per row.

Replays: the file's sha256 identifies the import. Re-importing the same bytes (even from another
path) reuses its crawl_run and evidence, and every observation's idempotency_key is
sha256(source | file sha256 | listing_key) with observed_at taken from the mapping or the row,
never the import time, so ON CONFLICT DO NOTHING makes the replay a no-op.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import psycopg
from psycopg.types.json import Jsonb

from offline_import import __version__
from offline_import.mapping import ImportMapping
from offline_import.validate import ImportReport, ImportRow
from pi_core import AvailabilityState, FetchMethod, FieldState, PriceType

CONNECTOR_VERSION = f"offline_import/{__version__}"
METHOD = FetchMethod.OFFLINE_IMPORT
RUNG = int(METHOD.rung)  # LadderRung.SITE_DATA (0): nothing is fetched from the source
RETENTION = timedelta(days=90)

Conn = psycopg.Connection[Any]


def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def content_hash(
    labels: dict[str, Any],
    description: str | None,
    badges: list[str] | None,
    ingredients: str | None = None,
) -> str:
    """A listing_content row's hash; unchanged for a row with only labels, as before content, and
    for a row without ingredients, as before they were loaded."""
    if description is None and badges is None and ingredients is None:
        return _sha(json.dumps(labels, sort_keys=True))
    parts: list[Any] = [labels, description, badges]
    if ingredients is not None:
        parts.append(ingredients)
    return _sha(json.dumps(parts, sort_keys=True, ensure_ascii=False))


# Page attributes stored in labels under their own names (the reader's spec keys).
_ATTRIBUTE_TEXT: tuple[str, ...] = (
    "mpn",
    "colour_code",
    "colour_hex",
    "collection",
    "fragrance_family",
    "finish",
    "formulation",
    "lifecycle_class",
    "exclusivity",
    "loyalty_points",
    "installment_amount_minor",
)
_ATTRIBUTE_LISTS: tuple[str, ...] = (
    "gift_with_purchase",
    "bullets",
    "skin_type",
    "concern",
    "installment_provider",
)


def idempotency_key(source: str, file_sha256: str, listing_key: str) -> str:
    return _sha(source, file_sha256, listing_key)


def _field_state(row: ImportRow, prices_mapped: bool) -> dict[str, str]:
    """Why each price is null, and how availability was determined (DQ-02, DAT-06).

    A feed with no price column says nothing about price: 'unknown', which the export skips,
    so a stock-only import never blanks a crawled price. A mapped but blank price is
    'not_published'.
    """
    fs: dict[str, str] = {}
    if row.price_current is None:
        fs["price_current"] = FieldState.NOT_PUBLISHED if prices_mapped else FieldState.UNKNOWN
    if row.availability_observed:
        fs["availability_state"] = FieldState.OBSERVED
    elif row.availability is AvailabilityState.UNKNOWN:
        fs["availability_state"] = FieldState.UNKNOWN
    else:
        fs["availability_state"] = FieldState.NOT_PUBLISHED
    return fs


class Loader:
    def __init__(self, conn: Conn, mapping: ImportMapping, report: ImportReport, uri: str) -> None:
        self.c = conn
        self.m = mapping
        self.report = report
        self.uri = uri
        self.source_id = self._source()
        self.context_id = self._context()
        self._months: set[date] = set()

    # ------------------------------------------------------------ reference rows
    def _one(self, sql: str, args: tuple[Any, ...]) -> int | None:
        row = self.c.execute(sql, args).fetchone()
        return int(row[0]) if row else None

    def _id(self, sql: str, args: tuple[Any, ...]) -> int:
        rid = self._one(sql, args)
        if rid is None:
            raise RuntimeError(f"no id returned: {sql[:60]}")
        return rid

    def _source(self) -> int:
        s = self.m.source
        return self._one("SELECT id FROM source WHERE name=%s", (s.name,)) or self._id(
            "INSERT INTO source (name, kind, base_url, notes) VALUES (%s,%s,%s,%s) RETURNING id",
            (s.name, s.kind.value, s.base_url, s.notes),
        )

    def _context(self) -> int:
        m = self.m
        return self._one(
            "SELECT id FROM source_context WHERE source_id=%s AND country=%s AND locale=%s"
            " AND channel=%s AND valid_to IS NULL ORDER BY id LIMIT 1",
            (self.source_id, m.country, m.locale, m.channel.value),
        ) or self._id(
            "INSERT INTO source_context (source_id, country, channel, locale, time_zone,"
            " ladder_rung_current, coverage_status, refresh_policy)"
            " VALUES (%s,%s,%s,%s,%s,%s,'partial',%s) RETURNING id",
            (
                self.source_id,
                m.country,
                m.channel.value,
                m.locale,
                m.time_zone,
                RUNG,
                Jsonb({"mode": "offline_import", "currency": m.currency}),
            ),
        )

    def _existing(self) -> tuple[int, int, str] | None:
        """(crawl_run, evidence, storage_uri) of an earlier import of the same bytes."""
        row = self.c.execute(
            "SELECT e.crawl_run_id, e.id, e.storage_uri FROM evidence e"
            " JOIN crawl_run r ON r.id = e.crawl_run_id"
            " JOIN source_context c ON c.id = r.source_context_id"
            " WHERE c.source_id=%s AND e.fetch_method=%s AND e.content_hash=%s"
            " ORDER BY e.id LIMIT 1",
            (self.source_id, METHOD.value, self.report.sha256),
        ).fetchone()
        return (int(row[0]), int(row[1]), str(row[2])) if row else None

    def _run_and_evidence(self, now: datetime) -> tuple[int, int]:
        run = self._id(
            "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
            " started_at, manifest_uri) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (self.context_id, CONNECTOR_VERSION, RUNG, now, self.uri),
        )
        evidence = self._id(
            "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
            " ladder_rung_used, fetch_method, retention_until)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (run, self.uri, self.report.sha256, self.uri, now, RUNG, METHOD.value, now + RETENTION),
        )
        return run, evidence

    # ------------------------------------------------------------ per row
    def _url(self, row: ImportRow) -> str:
        url = row.text.get("url")  # validation guarantees an http(s) URL or a template
        if url:
            return url
        assert self.m.url_template is not None  # noqa: S101 - enforced by the mapping
        return self.m.url_template.format(  # path-safe: a key may hold "/", "?", "#"
            listing_key=quote(row.listing_key, safe=""),
            sku=quote(str(row.text.get("sku") or row.listing_key), safe=""),
        )

    def _listing(self, row: ImportRow) -> int:
        t = row.text
        return self._id(
            "INSERT INTO source_listing (source_id, source_listing_key, source_sku, url,"
            " name_original, name_ar, lang, category_path_source, first_seen_at, last_seen_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (source_id, source_listing_key) DO UPDATE SET"
            " last_seen_at=GREATEST(source_listing.last_seen_at, EXCLUDED.last_seen_at),"
            " first_seen_at=LEAST(source_listing.first_seen_at, EXCLUDED.first_seen_at),"
            " source_sku=COALESCE(source_listing.source_sku, EXCLUDED.source_sku),"
            " name_ar=COALESCE(EXCLUDED.name_ar, source_listing.name_ar)"
            " RETURNING id",
            (
                self.source_id,
                row.listing_key,
                t.get("sku"),
                self._url(row),
                t.get("name") or "",
                t.get("name_ar"),
                self.m.locale.split("-")[0].lower(),
                t.get("category_path"),
                row.observed_at,
                row.observed_at,
            ),
        )

    def _content(self, lid: int, row: ImportRow) -> None:
        t = row.text
        labels: dict[str, Any] = {
            # pi_match export keys: brand/size/shade/gtin.
            "brand": t.get("brand"),
            "size": t.get("size"),
            "shade": t.get("shade"),
            "gtin": t.get("gtin"),
            "product_name": t.get("name"),
            "sku": t.get("sku"),
            "image_url": t.get("image_url"),
            "stock_qty": row.stock_qty,
            "gender": t.get("gender"),
            "concentration": t.get("concentration"),
            "promotions": list(row.lists["promotions"]) if row.lists.get("promotions") else None,
            # the export groups listings by master_id (one product per style)
            "master_id": t.get("style_id"),
            **{f: t.get(f) for f in _ATTRIBUTE_TEXT},
            **{f: list(row.lists[f]) for f in _ATTRIBUTE_LISTS if row.lists.get(f)},
            # the shape the Sephora load writes and the export reads: the first image is main
            "images": [
                {"role": "main" if i == 0 else "alt", "position": i, "url": url}
                for i, url in enumerate(row.lists.get("image_urls", ()))
            ]
            or None,
            "import_sha256": self.report.sha256,
            "import_row": row.row,
            "evidence_uri": self.uri,
        }
        labels = {k: v for k, v in labels.items() if v is not None}
        description = t.get("description")
        arabic = self.m.locale.lower().startswith("ar")
        badges = list(row.lists.get("badges", ()))
        ingredients = t.get("ingredients")
        self.c.execute(
            "INSERT INTO listing_content (listing_id, observed_at, description, description_ar,"
            " ingredients, badges, labels, content_hash) SELECT %s,%s,%s,%s,%s,%s,%s,%s"
            # one content per page time, the first written, on replay too
            " WHERE NOT EXISTS (SELECT 1 FROM listing_content"
            " WHERE listing_id=%s AND observed_at=%s)"
            " ON CONFLICT DO NOTHING",
            (
                lid,
                row.observed_at,
                None if arabic else description,
                description if arabic else None,
                ingredients,
                badges,
                Jsonb(labels),
                content_hash(labels, description, badges or None, ingredients),
                lid,
                row.observed_at,
            ),
        )

    def _partition(self, at: datetime) -> None:
        month = at.astimezone(UTC).date().replace(day=1)
        if month not in self._months:
            self.c.execute("SELECT pi_ensure_offer_observation_partition(%s)", (month,))
            self._months.add(month)

    def _offer(self, lid: int, row: ImportRow, run: int, evidence: int) -> bool:
        price = row.price_current
        promo = row.price_promo is not None and price == row.price_promo
        price_type = None if price is None else PriceType.PROMOTIONAL if promo else PriceType.FULL
        any_price = any(p is not None for p in (price, row.price_regular, row.price_promo))
        low = row.availability is AvailabilityState.LOW_STOCK
        self._partition(row.observed_at)
        cur = self.c.execute(
            "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
            " source_listing_id, observed_at, ingested_at, price_current, price_regular_stated,"
            " price_promo, price_type, currency, availability_state, low_stock_flag,"
            " badges_at_time, field_state, evidence_id)"
            " VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT DO NOTHING",
            (
                idempotency_key(self.m.source.name, self.report.sha256, row.listing_key),
                run,
                self.context_id,
                lid,
                row.observed_at,
                price,
                row.price_regular,
                row.price_promo,
                price_type,
                self.m.currency if any_price else None,
                row.availability.value,
                True if low else None,
                list(row.lists.get("badges", ())),
                Jsonb(_field_state(row, self.m.prices_mapped)),
                evidence,
            ),
        )
        return cur.rowcount == 1

    # ------------------------------------------------------------ driver
    def load(self) -> dict[str, Any]:
        """Load every accepted row in one transaction; returns counts."""
        now = datetime.now(UTC)
        # Serialises concurrent imports of the same bytes, so a race cannot create two runs.
        self.c.execute(
            "SELECT pg_advisory_xact_lock(hashtext('offline_import'), hashtext(%s))",
            (self.report.sha256,),
        )
        existing = self._existing()
        if existing is not None:  # replay: the first import's run, evidence and URI
            run, evidence, self.uri = existing
        else:
            run, evidence = self._run_and_evidence(now)
        inserted = 0
        for row in self.report.accepted:
            lid = self._listing(row)
            self._content(lid, row)
            inserted += self._offer(lid, row, run, evidence)
        if existing is None:
            self._finish(run, now)
        self.c.commit()
        return {
            "crawl_run_id": run,
            "evidence_id": evidence,
            "replay": existing is not None,
            "observations_inserted": inserted,
            "accepted": len(self.report.accepted),
            "rejected": len(self.report.rejected),
        }

    def _finish(self, run: int, started: datetime) -> None:
        """'succeeded' only for a declared whole catalogue loaded without a single rejected row.

        The export treats the newest succeeded run as the full baseline, so a rejected row in a
        'complete' feed would read as a removal; any rejection makes the run 'partial'.
        """
        r = self.report
        complete = self.m.complete_catalogue and r.rows > 0 and not r.rejected
        status = "succeeded" if complete else "partial"
        self.c.execute(
            "UPDATE crawl_run SET finished_at=GREATEST(%s, now()), status=%s, discovered=%s,"
            " fetched=%s, parsed=%s, accepted=%s, quarantined=%s WHERE id=%s",
            (started, status, r.rows, r.rows, r.rows, len(r.accepted), len(r.rejected), run),
        )
