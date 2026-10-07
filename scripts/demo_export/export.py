#!/usr/bin/env python3
"""Export a local pi_db snapshot as the frontend's ``pi.dataset/v1`` JSON (and, with
``--output-v2``, the ``pi.dataset/v2`` snapshot built by ``v2.py``; with ``--output-v3``, that
snapshot upgraded to ``pi.dataset/v3`` with each offer's ``listingCount``).

This is deliberately a read-only producer. It never fetches retailer data and it only adds
Ulta early examples when an explicitly supplied, committed/redacted probe fixture is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from pi_dataset.gate import V3_MAX_BYTES

DATASET_SCHEMA = "pi.dataset/v1"
ALLOWED_CATEGORIES = {
    "foundation",
    "concealer",
    "lips",
    "cheek",
    "eyes",
    "skincare",
    "fragrance",
    "body",
    "other",
}
KNOWN_UNITS = {"ml", "g", "pc"}
IN_STOCK = {"in_stock", "low_stock"}
UNKNOWN_STOCK = {"unknown", "blocked", "not_observed"}
#: A price at or below this (AED) is not a real offer (owner ruling, 1 Oct 2026). pi_api withholds
#: and flags it (``priceFlag = "invalid_low"``); the exporter never lets it stand for a variant
#: group that has a valid price, and v1 shows it as null.
PRICE_FLOOR = Decimal("0.01")
SECRET_KEYS = {
    "api_key",
    "apikey",
    "app_id",
    "appid",
    "application_id",
    "x-algolia-api-key",
    "x-algolia-application-id",
}


@dataclass(frozen=True)
class ListingRow:
    source_name: str
    family_id: str
    variant_id: int
    source_listing_key: str
    source_sku: str | None
    url: str
    name: str
    brand: str
    category: str | None
    category_path: str | None
    shade: str | None
    shade_family: str | None
    shade_hex: str | None
    size_value: Decimal | None
    size_unit: str | None
    size_label: str | None
    price: Decimal | None
    regular: Decimal | None
    price_type: str | None
    availability: str
    rating: Decimal | None
    rating_scale: Decimal | None
    rating_count: int | None
    observed_at: datetime
    evidence_retrieved_at: datetime | None
    run_id: int
    run_status: str
    coverage_status: str
    # Provenance of the price, which can be older than the newest row (a later stock read).
    price_observed_at: datetime | None = None
    price_evidence_retrieved_at: datetime | None = None
    price_run_id: int | None = None
    stock_observed_at: datetime | None = None
    stock_evidence_retrieved_at: datetime | None = None
    stock_run_id: int | None = None
    #: The retailer's main image URL from the latest content; only v2 reads it (allowlisted there).
    image: str | None = None
    #: v3 ``Offer.content`` only (2026-10-03), all from the latest content row and the variant:
    #: the barcode as stored (checked in v2), the page's description and ingredients, and the
    #: gallery URLs in the page's order (allowlisted in v2).
    gtin: str | None = None
    description: str | None = None
    ingredients: str | None = None
    images: tuple[str, ...] = ()
    #: The retailer's own gift-with-purchase titles for this product (Sephora: PRODUCT-class
    #: promotions), from the latest content. Not published until the beauty@2 profile declares it.
    gift_with_purchase: tuple[str, ...] = ()
    #: the fragrance concentration (variant, else the page's label); v2 ``attributes`` (beauty@1)
    concentration: str | None = None

    @property
    def price_capture(self) -> tuple[datetime, int]:
        """When and in which run the shown price was captured (the newest row without one)."""
        if self.price_observed_at is None or self.price_run_id is None:
            return self.evidence_retrieved_at or self.observed_at, self.run_id
        return self.price_evidence_retrieved_at or self.price_observed_at, self.price_run_id

    @property
    def stock_capture(self) -> tuple[datetime, int]:
        """When and in which run the shown stock state was observed (the newest row without one)."""
        if self.stock_observed_at is None or self.stock_run_id is None:
            return self.evidence_retrieved_at or self.observed_at, self.run_id
        return self.stock_evidence_retrieved_at or self.stock_observed_at, self.stock_run_id

    @property
    def retailer(self) -> str:
        return slot(self.source_name)

    @property
    def effective_size(self) -> tuple[str | None, Decimal | None]:
        unit = normalise_unit(self.size_unit)
        if unit is not None and self.size_value is not None:
            return unit, self.size_value
        return parse_size_label(self.size_label)


@dataclass(frozen=True)
class GroupKey:
    retailer: str
    family_id: str
    size_unit: str | None
    size_value: Decimal | None

    @property
    def stable_token(self) -> str:
        size = "unknown" if self.size_value is None else decimal_text(self.size_value)
        unit = self.size_unit or "unknown"
        return f"{self.retailer}-{self.family_id}-{size}-{unit}"


@dataclass(frozen=True)
class MatchRow:
    variant_a: int
    variant_b: int
    match_class: str
    score: Decimal | None
    algo_version: str
    review_state: str
    #: A reviewer is recorded (the identity itself is never read or published, SEC-06).
    human: bool = False


#: Source-name prefix -> v1 slot. ``f`` (Faces, 2026-10-03), ``o`` (Ounass) and ``b``
#: (Bloomingdale's, 2026-10-07) are v2/v3 only: v1 stays u/s.
SLOTS = {"sephora": "s", "ulta": "u", "faces": "f", "ounass": "o", "bloomingdales": "b"}
#: Pair naming preference: a matched pair is named by its first slot here (Sephora, as before;
#: each later retailer after those already named, Ulta always last).
NAMING_ORDER = ("s", "f", "o", "b", "u")
#: ``meta.retailers`` order (v2's ``RETAILERS``).
SLOT_ORDER = ("u", "s", "f", "o", "b")


def slot(source_name: str) -> str:
    """The slot (``u``/``s``/``f``/``o``/``b``) of a source name."""
    for prefix, key in SLOTS.items():
        if source_name.startswith(prefix):
            return key
    raise ValueError(f"unsupported source {source_name!r}")


# Owner decision for the pilot (2026-09-30): ulta.ae is blocked; the status line is data (CLI).
ULTA_BLOCKED_NOTE = (
    "ulta.ae: blocked by site security (Cloudflare) via Gulf datacenter and UAE residential; "
    "0 products"
)
ULTA_BLOCKED_NOTE_AR = (
    "ulta.ae: محجوب بواسطة أمان الموقع (Cloudflare) عبر مركز بيانات خليجي وعنوان سكني إماراتي؛ "
    "0 منتجات"
)


#: The sources this process exports by default. Ulta stays out unless it is named explicitly with
#: --sources (owner ruling 2026-10-01: our process never publishes Ulta rows that happen to be in
#: pi_db); a match pair needs both of its sides in the exported sources.
DEFAULT_SOURCES = ("sephora_me",)


@dataclass(frozen=True)
class UltaContext:
    blocked_since: datetime
    #: The owner's statement that ulta.ae is blocked (v2 takes Ulta's status from it, never from
    #: whether Ulta rows exist). ``--ulta-unblocked`` clears it once Ulta is collected again.
    blocked: bool = True
    recon_observed_count: int | None = None
    recon_source: str | None = None
    blocked_note: str = ULTA_BLOCKED_NOTE
    blocked_note_ar: str = ULTA_BLOCKED_NOTE_AR


LATEST_LISTINGS_SQL = """
WITH scoped_runs AS (
  SELECT cr.id, cr.source_context_id, cr.status, cr.started_at
  FROM crawl_run cr
  JOIN source_context sc ON sc.id = cr.source_context_id
  JOIN source s ON s.id = sc.source_id
  WHERE sc.country = 'AE'
    AND sc.locale = 'en-AE'
    AND s.name = ANY(%(sources)s)
),
-- The baseline is the newest SUCCEEDED run per context: a running, failed or partial refresh
-- must never hide it (that would publish false removals).
current_runs AS (
  SELECT DISTINCT ON (source_context_id) id, source_context_id, started_at
  FROM scoped_runs
  WHERE status = 'succeeded'
  ORDER BY source_context_id, started_at DESC, id DESC
),
-- Incremental refreshes are partial runs by design. Rows of partial runs started after the
-- baseline are read too, so their newer prices and stock states reach the export. Absence
-- never does: a listing a partial run did not see keeps its baseline row, and only an
-- explicit observation (e.g. availability 'removed' from a page check) changes it. Failed and
-- aborted runs (integrity unknown) and running ones (a half-loaded pass) are left out; a
-- running run counts once --finish closes it as partial.
-- Contexts with no succeeded run yet fall back to the latest observation per listing across
-- all of their runs.
-- History mode (--history) passes one market day as [day_start, day_end): every succeeded or
-- partial run then counts, and only its observations on that day are read (never carried
-- forward). With no day (the default), the rules above apply unchanged.
eligible_runs AS (
  SELECT id FROM current_runs WHERE %(day_start)s::timestamptz IS NULL
  UNION ALL
  SELECT r.id
  FROM scoped_runs r
  JOIN current_runs c ON c.source_context_id = r.source_context_id
  WHERE %(day_start)s::timestamptz IS NULL
    AND r.status = 'partial' AND (r.started_at, r.id) > (c.started_at, c.id)
  UNION ALL
  SELECT r.id
  FROM scoped_runs r
  WHERE %(day_start)s::timestamptz IS NULL AND NOT EXISTS (
    SELECT 1 FROM current_runs c WHERE c.source_context_id = r.source_context_id
  )
  UNION ALL
  SELECT r.id
  FROM scoped_runs r
  WHERE %(day_start)s::timestamptz IS NOT NULL AND r.status IN ('succeeded', 'partial')
),
-- One source may split an offer across rows: a page read carries price and rating with
-- availability 'not_observed'; a stock read carries availability with price unknown
-- (field_state price_current='unknown'). Price and availability therefore each come from their
-- own newest row that observed them, so a newer stock read never blanks the price and a newer
-- page read never hides the stock state. The price row's own time, evidence and run are carried
-- as price_* so a later stock read never makes the price look fresher than it is; likewise the
-- stock row's as stock_*, so a later page read never makes an old stock state look current.
obs AS (
  SELECT
    o.source_listing_id,
    o.variant_id,
    o.price_current,
    o.price_regular_stated,
    o.price_type::text,
    o.availability_state::text,
    o.rating_value,
    o.rating_scale,
    o.rating_count,
    o.observed_at,
    o.observation_id,
    o.field_state,
    o.crawl_run_id,
    cr.status AS run_status,
    sc.coverage_status::text,
    e.retrieved_at AS evidence_retrieved_at
  FROM offer_observation o
  JOIN eligible_runs eligible ON eligible.id = o.crawl_run_id
  JOIN crawl_run cr ON cr.id = o.crawl_run_id
  JOIN source_context sc ON sc.id = o.source_context_id
  LEFT JOIN evidence e ON e.id = o.evidence_id
  WHERE (o.currency = 'AED' OR o.currency IS NULL) AND sc.country = 'AE'
    AND (
      %(day_start)s::timestamptz IS NULL
      OR (o.observed_at >= %(day_start)s::timestamptz AND o.observed_at < %(day_end)s::timestamptz)
    )
),
latest_any AS (
  SELECT DISTINCT ON (source_listing_id) *
  FROM obs
  ORDER BY source_listing_id, observed_at DESC, observation_id DESC
),
latest_price AS (
  SELECT DISTINCT ON (source_listing_id) *
  FROM obs
  -- Not a price observation: field_state price_current unknown, blocked or parse_failure.
  -- not_published, restricted and not_applicable are observations and do win.
  WHERE COALESCE(field_state ->> 'price_current', '') NOT IN ('unknown', 'blocked', 'parse_failure')
  ORDER BY source_listing_id, observed_at DESC, observation_id DESC
),
latest_stock AS (
  SELECT DISTINCT ON (source_listing_id)
    source_listing_id, availability_state, observed_at, observation_id, evidence_retrieved_at,
    crawl_run_id
  FROM obs
  -- Not a stock observation: availability not_observed, unknown or blocked; never replaces a
  -- known state.
  WHERE availability_state NOT IN ('not_observed', 'unknown', 'blocked')
  ORDER BY source_listing_id, observed_at DESC, observation_id DESC
),
latest AS (
  SELECT
    a.source_listing_id,
    COALESCE(p.variant_id, a.variant_id) AS variant_id,
    COALESCE(p.price_current, a.price_current) AS price_current,
    COALESCE(p.price_regular_stated, a.price_regular_stated) AS price_regular_stated,
    COALESCE(p.price_type, a.price_type) AS price_type,
    COALESCE(st.availability_state, a.availability_state) AS availability_state,
    COALESCE(p.rating_value, a.rating_value) AS rating_value,
    COALESCE(p.rating_scale, a.rating_scale) AS rating_scale,
    COALESCE(p.rating_count, a.rating_count) AS rating_count,
    a.observed_at,
    a.crawl_run_id,
    a.run_status,
    a.coverage_status,
    a.evidence_retrieved_at,
    p.observed_at AS price_observed_at,
    p.evidence_retrieved_at AS price_evidence_retrieved_at,
    p.crawl_run_id AS price_run_id,
    st.observed_at AS stock_observed_at,
    st.evidence_retrieved_at AS stock_evidence_retrieved_at,
    st.crawl_run_id AS stock_run_id
  FROM latest_any a
  LEFT JOIN latest_price p ON p.source_listing_id = a.source_listing_id
  LEFT JOIN latest_stock st ON st.source_listing_id = a.source_listing_id
)
SELECT
  s.name AS source_name,
  COALESCE(pf.id::text, lc.labels ->> 'master_id', sl.source_listing_key) AS family_id,
  COALESCE(v.id, -sl.id) AS variant_id,
  sl.source_listing_key,
  sl.source_sku,
  sl.url,
  COALESCE(pf.name_normalized, lc.labels ->> 'product_name', sl.name_original) AS name,
  COALESCE(b.name, lc.labels ->> 'brand_name', lc.labels ->> 'brand') AS brand,
  t.code AS category,
  sl.category_path_source AS category_path,
  COALESCE(v.shade, lc.labels ->> 'shade') AS shade,
  v.shade_family,
  v.shade_hex,
  v.size_value,
  v.size_unit,
  lc.labels ->> 'size' AS size_label,
  COALESCE(v.gtin, lc.labels ->> 'gtin') AS gtin,
  COALESCE(v.concentration, NULLIF(lc.labels ->> 'concentration', '')) AS concentration,
  lc.description,
  lc.ingredients,
  latest.price_current AS price,
  -- A full-price row is its own regular price: Sephora and Faces state a regular only on
  -- promotional rows, and a null there would leave every full-price offer out of the
  -- discount share's cohort (a false "every offer discounted").
  CASE
    WHEN latest.price_regular_stated IS NULL AND latest.price_type = 'full'
    THEN latest.price_current
    ELSE latest.price_regular_stated
  END AS regular,
  latest.price_type,
  latest.availability_state AS availability,
  latest.rating_value AS rating,
  latest.rating_scale,
  latest.rating_count,
  latest.observed_at,
  latest.evidence_retrieved_at,
  latest.crawl_run_id AS run_id,
  latest.run_status,
  latest.coverage_status,
  latest.price_observed_at,
  latest.price_evidence_retrieved_at,
  latest.price_run_id,
  latest.stock_observed_at,
  latest.stock_evidence_retrieved_at,
  latest.stock_run_id,
  -- The main image. Two element shapes are read: the Sephora loader's {role: 'main', url}, and
  -- the owner's ulta_ae load {roles: [..., 'image', ...], download_url} (download_url is the CDN
  -- URL the live combined file carries; local_path is never read). Lowest position wins. With no
  -- such element, the import's single labels.image_url (the faces_ae load) is the main image;
  -- else NULL. v2 then keeps only the source's own host.
  COALESCE((
    SELECT COALESCE(img ->> 'url', img ->> 'download_url')
    FROM jsonb_array_elements(
      CASE WHEN jsonb_typeof(lc.labels -> 'images') = 'array' THEN lc.labels -> 'images' END
    ) img
    WHERE img ->> 'role' = 'main'
      OR (jsonb_typeof(img -> 'roles') = 'array' AND img -> 'roles' ? 'image')
    ORDER BY
      CASE WHEN img ->> 'position' ~ '^[0-9]+$' THEN (img ->> 'position')::int END NULLS LAST,
      COALESCE(img ->> 'url', img ->> 'download_url')
    LIMIT 1
  ), NULLIF(lc.labels ->> 'image_url', '')) AS image,
  -- The gallery: every element of the same two shapes (role 'main' or 'alt'; roles holding
  -- 'image'), swatches left out, in position order; with none, labels.image_url alone. v2 keeps
  -- only the source's own hosts.
  COALESCE(NULLIF(ARRAY(
    SELECT COALESCE(img ->> 'url', img ->> 'download_url')
    FROM jsonb_array_elements(
      CASE WHEN jsonb_typeof(lc.labels -> 'images') = 'array' THEN lc.labels -> 'images' END
    ) img
    WHERE COALESCE(img ->> 'url', img ->> 'download_url') IS NOT NULL
      AND (
        img ->> 'role' IN ('main', 'alt')
        OR (jsonb_typeof(img -> 'roles') = 'array' AND img -> 'roles' ? 'image')
      )
    ORDER BY
      CASE WHEN img ->> 'position' ~ '^[0-9]+$' THEN (img ->> 'position')::int END NULLS LAST,
      COALESCE(img ->> 'url', img ->> 'download_url')
  ), '{}'), ARRAY_REMOVE(ARRAY[NULLIF(lc.labels ->> 'image_url', '')], NULL)) AS images,
  -- Gift-with-purchase titles (labels.gift_with_purchase, a JSON array of strings), in order.
  ARRAY(
    SELECT title
    FROM jsonb_array_elements_text(
      CASE
        WHEN jsonb_typeof(lc.labels -> 'gift_with_purchase') = 'array'
        THEN lc.labels -> 'gift_with_purchase'
      END
    ) WITH ORDINALITY AS gwp(title, n)
    WHERE btrim(title) <> ''
    ORDER BY n
  ) AS gift_with_purchase
FROM latest
JOIN source_listing sl ON sl.id = latest.source_listing_id
JOIN source s ON s.id = sl.source_id
LEFT JOIN variant v ON v.id = COALESCE(latest.variant_id, sl.variant_id)
LEFT JOIN product_family pf ON pf.id = v.family_id
LEFT JOIN brand b ON b.id = pf.brand_id
LEFT JOIN taxonomy t ON t.id = pf.category_universal_id
LEFT JOIN LATERAL (
  SELECT content.labels, content.description, content.ingredients
  FROM listing_content content
  WHERE content.listing_id = sl.id
  ORDER BY content.observed_at DESC, content.recorded_at DESC
  LIMIT 1
) lc ON true
WHERE s.name = ANY(%(sources)s)
  -- An Ulta aggregate parent repeats its variants: it is left out iff at least one of its
  -- resolved children is exported here as a non-parent listing of the same source. A parent
  -- whose children are all absent (or that lists none) stays. A parent is a listing whose
  -- latest content has labels.aggregate_parent JSON true or the text 'true' (owner, option A).
  AND NOT (
    s.name LIKE 'ulta%%'
    AND COALESCE(lc.labels ->> 'aggregate_parent' = 'true', false)
    AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(
        CASE
          WHEN jsonb_typeof(lc.labels -> 'resolved_children') = 'array'
          THEN lc.labels -> 'resolved_children'
        END
      ) AS child(key)
      JOIN source_listing child_listing
        ON child_listing.source_id = sl.source_id AND child_listing.source_listing_key = child.key
      JOIN latest child_latest ON child_latest.source_listing_id = child_listing.id
      WHERE NOT COALESCE(
        (
          SELECT child_content.labels ->> 'aggregate_parent' = 'true'
          FROM listing_content child_content
          WHERE child_content.listing_id = child_listing.id
          ORDER BY child_content.observed_at DESC, child_content.recorded_at DESC
          LIMIT 1
        ),
        false
      )
    )
  )
ORDER BY s.name, pf.id, v.size_value NULLS FIRST, v.id
"""

MATCHES_SQL = """
SELECT variant_a, variant_b, match_class::text, score, algo_version, review_state::text,
       reviewer IS NOT NULL AS human
FROM match_edge
WHERE valid_to IS NULL
  AND review_state <> 'rejected'
  AND match_class = 'exact'
ORDER BY score DESC NULLS LAST, id
"""


def decimal_text(value: Decimal) -> str:
    """Return a stable non-exponent decimal representation."""
    return format(value.normalize(), "f")


def json_number(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def json_money(value: Decimal | None) -> int | float | None:
    """Convert AED Decimal to a JSON number only when it has at most two decimal places."""
    if value is None:
        return None
    if value != value.quantize(Decimal("0.01")):
        raise ValueError(f"AED amount has more than two decimal places: {value}")
    return json_number(value)


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def normalise_unit(value: str | None) -> str | None:
    if value is None:
        return None
    unit = value.strip().lower()
    aliases = {"milliliter": "ml", "millilitre": "ml", "gram": "g", "piece": "pc"}
    unit = aliases.get(unit, unit)
    return unit if unit in KNOWN_UNITS else None


def parse_size_label(value: str | None) -> tuple[str | None, Decimal | None]:
    """Parse a simple published metric size without guessing sets or conversions."""
    if value is None:
        return None, None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ml|g|pc)\s*", value, flags=re.IGNORECASE)
    if match is None:
        return None, None
    return match.group(2).lower(), Decimal(match.group(1))


def psycopg_database_url(value: str) -> str:
    """Accept the workspace's SQLAlchemy-style psycopg URL as well as a native DSN."""
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def category_from_text(text: str) -> str:
    lowered = text.lower()
    rules = (
        ("conceal", "concealer"),
        ("foundation", "foundation"),
        ("lip", "lips"),
        ("blush", "cheek"),
        ("cheek", "cheek"),
        ("eye", "eyes"),
        ("fragrance", "fragrance"),
        ("perfume", "fragrance"),
        ("skin", "skincare"),
        ("body", "body"),
    )
    return next((result for needle, result in rules if needle in lowered), "other")


def category_for(row: ListingRow) -> str:
    if row.category and row.category.lower() in ALLOWED_CATEGORIES:
        return row.category.lower()
    return category_from_text(" ".join(filter(None, (row.category, row.category_path))))


def group_rows(rows: Iterable[ListingRow]) -> dict[GroupKey, list[ListingRow]]:
    groups: dict[GroupKey, list[ListingRow]] = defaultdict(list)
    for row in rows:
        unit, size = row.effective_size
        groups[GroupKey(row.retailer, row.family_id, unit, size)].append(row)
    return dict(groups)


def valid_price(value: Decimal | None) -> bool:
    return value is not None and value > PRICE_FLOOR


def invalid_prices(rows: Iterable[ListingRow]) -> dict[str, int]:
    """Listing rows per retailer slot whose price is at or below ``PRICE_FLOOR`` (run log)."""
    counts = dict.fromkeys(("u", "s"), 0)
    for row in rows:
        counts.setdefault(row.retailer, 0)
        if row.price is not None and not valid_price(row.price):
            counts[row.retailer] += 1
    return counts


def choose_representative(rows: Sequence[ListingRow]) -> ListingRow:
    """The cheapest in-stock (else unknown-stock, else any) priced row. A price at or below
    ``PRICE_FLOOR`` is used only when no row of the group has a valid one, so it never wins
    "cheapest" over a real price."""
    priced = [row for row in rows if valid_price(row.price)] or [
        row for row in rows if row.price is not None
    ]
    if not priced:
        return min(rows, key=lambda row: row.variant_id)
    in_stock = [row for row in priced if row.availability in IN_STOCK]
    unknown = [row for row in priced if row.availability in UNKNOWN_STOCK]
    candidates = in_stock or unknown or priced
    return min(candidates, key=lambda row: (row.price or Decimal("Infinity"), row.variant_id))


def promo_pct(price: Decimal, regular: Decimal | None) -> int:
    if regular is None or regular <= price:
        return 0
    return round((Decimal(1) - price / regular) * 100)


def offer_for(rows: Sequence[ListingRow], *, early: bool = False) -> dict[str, Any]:
    representative = choose_representative(rows)
    _, representative_size = representative.effective_size
    captured, price_run_id = representative.price_capture
    # v1 has no flag: a price at or below the floor is shown as not observed.
    price = representative.price if valid_price(representative.price) else None
    shade_values = {row.shade for row in rows if row.shade}
    offer: dict[str, Any] = {
        "sku": representative.source_sku or representative.source_listing_key,
        "url": representative.url,
        "size": json_number(representative_size),
        "shadeCount": len(shade_values),
        "rating": None,
        "series": {"price": [json_money(price)]},
        "evidence": {
            "capturedAt": utc_text(captured),
            "source": f"{representative.source_name} · local pi_db snapshot",
            "runId": str(price_run_id),
        },
    }
    if price is not None and representative.regular is not None:
        offer["series"]["regular"] = [json_money(representative.regular)]
        offer["series"]["promo"] = [promo_pct(price, representative.regular)]
    if (
        representative.rating is not None
        and representative.rating_scale is not None
        and representative.rating_count is not None
    ):
        rating = representative.rating * Decimal(5) / representative.rating_scale
        offer["rating"] = [
            json_number(rating.quantize(Decimal("0.01"))),
            representative.rating_count,
        ]
    if early:
        offer["early"] = True
    return offer


def product_for_group(key: GroupKey, rows: Sequence[ListingRow]) -> dict[str, Any]:
    representative = choose_representative(rows)
    shades = sorted({row.shade_hex.lower() for row in rows if row.shade_hex})[:12]
    shade_families = sorted({row.shade_family for row in rows if row.shade_family})
    product: dict[str, Any] = {
        "id": key.stable_token,
        "brand": representative.brand,
        "name": representative.name,
        "category": category_for(representative),
        "unit": key.size_unit,
        "match": None,
        "offers": {"u": None, "s": None},
    }
    product["offers"][key.retailer] = offer_for(rows)
    if shades:
        product["shades"] = shades
    if shade_families:
        product["shadeFamilies"] = shade_families
    return product


def pair_groups(
    groups: Mapping[GroupKey, Sequence[ListingRow]], matches: Sequence[MatchRow]
) -> tuple[list[tuple[GroupKey, GroupKey, MatchRow]], list[GroupKey]]:
    """Exact, same-size pairs of two retailers (best score first, each group used once), and the
    groups left unpaired in stable-token order. Shared by the v1 and v2 builders.

    A pair is ``(other, namer)``: the namer is the side first in ``NAMING_ORDER`` (Sephora for
    Ulta/Sephora, as before), so any two retailers pair and no pair assumes which two."""
    by_variant = {row.variant_id: key for key, rows in groups.items() for row in rows}
    candidates: dict[tuple[GroupKey, GroupKey], MatchRow] = {}
    for match in matches:
        if match.match_class != "exact":
            continue
        left = by_variant.get(match.variant_a)
        right = by_variant.get(match.variant_b)
        if left is None or right is None or left.retailer == right.retailer:
            continue
        namer = min((left, right), key=lambda k: NAMING_ORDER.index(k.retailer))
        pair = (right, namer) if namer is left else (left, namer)
        if (
            pair[0].size_unit is None
            or pair[0].size_value is None
            or pair[0].size_unit != pair[1].size_unit
            or pair[0].size_value != pair[1].size_value
        ):
            continue
        current = candidates.get(pair)
        if current is None or (match.score or Decimal(-1)) > (current.score or Decimal(-1)):
            candidates[pair] = match

    used: set[GroupKey] = set()
    pairs: list[tuple[GroupKey, GroupKey, MatchRow]] = []
    ordered = sorted(
        candidates.items(),
        key=lambda item: (
            -(item[1].score or Decimal(-1)),
            item[0][0].stable_token,
            item[0][1].stable_token,
        ),
    )
    for (other, namer), match in ordered:
        if other in used or namer in used:
            continue
        pairs.append((other, namer, match))
        used.update((other, namer))
    unpaired = [
        key for key in sorted(groups, key=lambda item: item.stable_token) if key not in used
    ]
    return pairs, unpaired


def matched_products(
    groups: Mapping[GroupKey, Sequence[ListingRow]], matches: Sequence[MatchRow]
) -> list[dict[str, Any]]:
    pairs, unpaired = pair_groups(groups, matches)
    products: list[dict[str, Any]] = []
    for ulta_key, sephora_key, match in pairs:
        ulta_rows = groups[ulta_key]
        sephora_rows = groups[sephora_key]
        base = product_for_group(sephora_key, sephora_rows)
        base["id"] = f"m-{ulta_key.stable_token}-{sephora_key.stable_token}"
        base["offers"]["u"] = offer_for(ulta_rows)
        base["match"] = {
            "method": match.algo_version,
            "confidence": json_number(match.score),
            "stage": "first-pass",
            "matchClass": match.match_class,
            "reviewState": review_state_for_ui(match.review_state),
        }
        products.append(base)

    products.extend(product_for_group(key, groups[key]) for key in unpaired)
    return sorted(products, key=lambda product: product["id"])


def review_state_for_ui(value: str) -> str:
    mapping = {
        "proposed": "proposed",
        "approved": "accepted",
        "locked": "accepted",
    }
    try:
        return mapping[value]
    except KeyError as error:
        raise ValueError(f"unsupported non-rejected review state {value!r}") from error


def latest_params(
    sources: Sequence[str], day: tuple[datetime, datetime] | None = None
) -> dict[str, Any]:
    """``LATEST_LISTINGS_SQL`` parameters; ``day`` is one market day ``[start, end)`` (history)."""
    start, end = day if day is not None else (None, None)
    return {"sources": list(sources), "day_start": start, "day_end": end}


def load_rows(
    database_url: str, sources: Sequence[str] = DEFAULT_SOURCES
) -> tuple[list[ListingRow], list[MatchRow]]:
    with psycopg.connect(psycopg_database_url(database_url), row_factory=dict_row) as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute(LATEST_LISTINGS_SQL, latest_params(sources))
            listing_dicts = cursor.fetchall()
            cursor.execute(MATCHES_SQL)
            match_dicts = cursor.fetchall()
    for row in listing_dicts:
        row["images"] = tuple(row.get("images") or ())
        row["gift_with_purchase"] = tuple(row.get("gift_with_purchase") or ())
    return (
        in_sources([ListingRow(**row) for row in listing_dicts], sources),
        [MatchRow(**row) for row in match_dicts],
    )


def in_sources(rows: Iterable[ListingRow], sources: Sequence[str]) -> list[ListingRow]:
    """Only the rows of the exported sources (the SQL filters too; this guards other callers).
    Matches need no filter: a pair is emitted only when both of its variants are in the rows."""
    return [row for row in rows if row.source_name in sources]


def parse_ulta_early_fixture(
    path: Path, captured_at: datetime, fixture_commit: str
) -> dict[str, Any]:
    """Parse the redacted PDP JSON-LD fixture without accepting network input."""
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', text, flags=re.DOTALL
    )
    payloads = [json.loads(block) for block in blocks]
    products = [payload for payload in payloads if payload.get("@type") == "Product"]
    if not products:
        raise ValueError(f"no Product JSON-LD found in {path}")
    payload = products[0]
    breadcrumbs: dict[str, Any] = next(
        (payload for payload in payloads if payload.get("@type") == "BreadcrumbList"), {}
    )
    category_text = " ".join(
        str(item.get("item", {}).get("name", "")) for item in breadcrumbs.get("itemListElement", [])
    )
    offers = payload.get("offers") or []
    if not offers:
        raise ValueError(f"Product JSON-LD in {path} has no offer")
    source_offer = offers[0]
    price = Decimal(str(source_offer["price"]))
    rating_payload = payload.get("aggregateRating")
    rating = None
    if rating_payload:
        rating = [
            round(float(rating_payload["ratingValue"]), 2),
            int(rating_payload["reviewCount"]),
        ]
    sku = str(source_offer.get("sku") or payload["sku"])
    product_id = f"u-early-{sku}"
    return {
        "id": product_id,
        "brand": payload["brand"]["name"],
        "name": payload["name"],
        "category": category_from_text(category_text),
        "unit": None,
        "match": None,
        "offers": {
            "u": {
                "sku": sku,
                "url": source_offer.get("url"),
                "size": None,
                "shadeCount": 0,
                "rating": rating,
                "early": True,
                "series": {"price": [json_money(price)]},
                "evidence": {
                    "capturedAt": utc_text(captured_at),
                    "source": f"ulta_ae · recon fixture {path.name} @ {fixture_commit}",
                    "runId": "gulf-probe-early",
                },
            },
            "s": None,
        },
    }


def contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normal = str(key).lower()
            if normal in SECRET_KEYS or (normal.startswith("algolia") and child):
                return True
            if contains_secret(child):
                return True
        return False
    if isinstance(value, list):
        return any(contains_secret(child) for child in value)
    if isinstance(value, str):
        lowered = value.lower()
        markers = (
            "x-algolia-api-key",
            "x-algolia-application-id",
            "api_key=",
            "apikey=",
            "app_id=",
            "application_id=",
        )
        return any(marker in lowered for marker in markers)
    return False


def export_slots(sources: Sequence[str]) -> tuple[str, ...]:
    """The retailers a v2 file lists for ``--sources``: Ulta and Sephora together as before (Ulta
    is the owner's statement even when not exported), any other source on its own."""
    named = {slot(source) for source in sources}
    legacy = bool(named & {"u", "s"})
    return tuple(s for s in SLOT_ORDER if (legacy and s in {"u", "s"}) or s in named)


def v1_rows(rows: Iterable[ListingRow]) -> list[ListingRow]:
    """v1 (the legacy dashboard) carries Ulta and Sephora only; another slot is v2/v3 only."""
    return [row for row in rows if row.retailer in ("u", "s")]


def retailer_status(rows: Sequence[ListingRow], retailer: str) -> str:
    source_rows = [row for row in rows if row.retailer == retailer]
    if not source_rows:
        return "blocked" if retailer == "u" else "pending"
    coverage = {row.coverage_status for row in source_rows}
    runs = {row.run_status for row in source_rows}
    if coverage <= {"supported"} and runs <= {"succeeded"}:
        return "ok"
    return "partial"


def build_dataset(
    rows: Sequence[ListingRow],
    matches: Sequence[MatchRow],
    *,
    generated_at: datetime,
    ulta_early: Sequence[dict[str, Any]] = (),
    ulta: UltaContext,
) -> dict[str, Any]:
    rows = v1_rows(rows)
    if not rows and not ulta_early:
        raise ValueError("refusing to create an empty demo dataset")
    from scripts.demo_export.tidy import tidy_rows  # noqa: PLC0415 - tidy imports ListingRow

    groups = group_rows(tidy_rows(rows))
    products = matched_products(groups, matches)
    existing_ids = {product["id"] for product in products}
    products.extend(product for product in ulta_early if product["id"] not in existing_ids)
    products.sort(key=lambda product: product["id"])

    captures = [row.evidence_retrieved_at or row.observed_at for row in rows]
    for product in ulta_early:
        captured = product["offers"]["u"]["evidence"]["capturedAt"]
        captures.append(parse_utc(captured))
    cutoff = max(captures)
    has_size = any(product["unit"] is not None for product in products)
    all_have_size = all(product["unit"] is not None for product in products)
    offers = [
        offer for product in products for offer in product["offers"].values() if offer is not None
    ]
    series = [offer["series"] for offer in offers]
    if (ulta.recon_observed_count is None) != (ulta.recon_source is None):
        raise ValueError("Ulta recon count and source must be supplied together")
    # The recon sentence appears only when recon metadata is supplied (E6); no recon, no mention.
    recon_note = recon_note_ar = ""
    if ulta.recon_observed_count is not None and ulta.recon_source is not None:
        if ulta.recon_observed_count < 0:
            raise ValueError("Ulta recon observed count cannot be negative")
        recon_note = (
            f"{ulta.recon_observed_count} products were observed only during recon "
            f"(30 Sep 20:33-20:58 UTC); 0 Ulta products are in the database. "
            f"Source: {ulta.recon_source}. "
        )
        recon_note_ar = (
            f"تمت ملاحظة {ulta.recon_observed_count} منتجات أثناء الاستطلاع فقط؛ لا توجد "
            f"منتجات استطلاع في قاعدة البيانات. المصدر: {ulta.recon_source}. "
        )
    # The ruling, not the presence of Ulta rows, decides that Ulta is blocked (as in v2).
    ulta_status = "blocked" if ulta.blocked else retailer_status(rows, "u")
    sephora_status = retailer_status(rows, "s")
    ulta_status_note, ulta_status_note_ar = (
        (ulta.blocked_note, ulta.blocked_note_ar)
        if ulta_status == "blocked"
        else (
            "A partial Ulta snapshot is loaded from pi_db; coverage is incomplete.",
            "تم تحميل لقطة جزئية لألتا من قاعدة البيانات؛ التغطية غير مكتملة.",
        )
        if ulta_status == "partial"
        else (
            "The Ulta snapshot is loaded from pi_db.",
            "تم تحميل لقطة ألتا من قاعدة البيانات.",
        )
    )
    ulta_retailer: dict[str, Any] = {
        "id": "u",
        "key": "ulta_ae",
        "name": "Ulta UAE",
        "status": ulta_status,
        "earlyExamples": bool(ulta_early),
        "note": {"en": recon_note + ulta_status_note, "ar": recon_note_ar + ulta_status_note_ar},
    }
    if ulta_status == "blocked":
        ulta_retailer["since"] = utc_text(ulta.blocked_since)
    dataset: dict[str, Any] = {
        "schema": DATASET_SCHEMA,
        "meta": {
            "kind": "snapshot",
            "cutoff": utc_text(cutoff),
            "generatedAt": utc_text(generated_at),
            "market": "AE",
            "currency": "AED",
            "matchStage": "first-pass",
            "dates": [cutoff.date().isoformat()],
            "retailers": [
                ulta_retailer,
                {
                    "id": "s",
                    "key": "sephora_me",
                    "name": "Sephora UAE",
                    "status": sephora_status,
                },
            ],
            "capabilities": {
                "history": False,
                "promotions": any("promo" in item for item in series),
                "campaigns": False,
                "stock": False,
                "sizes": has_size,
                "shades": any("shades" in product for product in products),
                "coverage": False,
            },
            "fields": {
                "price": "ok"
                if any(item["price"][0] is not None for item in series)
                else "not_collected",
                "regular": "ok" if any("regular" in item for item in series) else "not_collected",
                "promo": "ok" if any("promo" in item for item in series) else "not_collected",
                "stock": "not_collected",
                "size": "ok" if all_have_size else "not_published",
                "shades": (
                    "ok" if any("shades" in product for product in products) else "not_collected"
                ),
                "rating": "ok"
                if any(offer["rating"] is not None for offer in offers)
                else "not_collected",
                "gtin": "not_published",
            },
            "matchCheck": None,
        },
        "products": products,
    }
    if ulta_status == "blocked":
        dataset["notObserved"] = [
            {
                "retailer": "u",
                "start": ulta.blocked_since.date().isoformat(),
                "end": max(ulta.blocked_since.date(), cutoff.date()).isoformat(),
                "categories": None,
                "why": {
                    "en": "Cloudflare challenge; no blocked result is treated as out of stock.",
                    "ar": "تحدّي Cloudflare؛ لا تُعامل النتيجة المحجوبة على أنها نفاد مخزون.",
                },
            }
        ]
    if contains_secret(dataset):
        raise ValueError("refusing to write a dataset containing secret-like Algolia material")
    return dataset


#: The largest v3 file served on the default memory budget, in compact JSON bytes: one number
#: shared with pi_api (``pi_dataset.gate``), fitted in docs/runbooks/pi-api-deploy.md §6. A
#: larger body is refused unless ``--allow-over-gate`` asks for it; it is then written, reported
#: OVER GATE and exits ``OVER_GATE_EXIT``, and pi_api serves it only on a measured admission
#: record for its exact bytes. That flag supersedes the 2026-10-03 "no override" note
#: (Coordinator, 2026-10-07): without the record no file can be measured, so Ounass could never be
#: admitted. The gate is per file; §6 sizes the served files together.


def v3_bytes_by_group(v3: Any, total: int) -> dict[str, int]:
    """The written v3 bytes split three ways, exactly: ``prices`` (everything but
    ``Offer.content``), ``attributes`` (content without description and ingredients) and
    ``description+ingredients``. Measured by re-serialising with those parts emptied."""
    from pi_dataset import dump_dataset  # noqa: PLC0415

    def without(drop_all: bool) -> int:
        products = tuple(
            p.model_copy(
                update={
                    "offers": {
                        cid: o.model_copy(
                            update={
                                "content": None
                                if drop_all or o.content is None
                                else o.content.model_copy(
                                    update={"description": None, "ingredients": None}
                                )
                            }
                        )
                        for cid, o in p.offers.items()
                    }
                }
            )
            for p in v3.products
        )
        return len(dump_dataset(v3.model_copy(update={"products": products}), compact=True))

    prices, mid = without(True), without(False)
    return {
        "prices": prices,
        "attributes": mid - prices,
        "description+ingredients": total - mid,
    }


def format_groups(groups: Mapping[str, int]) -> str:
    return " ".join(f"{name}={size}" for name, size in groups.items())


def check_v3_size(total: int, groups: Mapping[str, int], *, over_gate: bool = False) -> bool:
    """Whether a v3 body is over ``V3_MAX_BYTES``. Over it, refuse (no file written) unless
    ``over_gate`` (``--allow-over-gate``) asks for the file anyway."""
    if total <= V3_MAX_BYTES:
        return False
    if not over_gate:
        raise SystemExit(
            f"refusing to write v3: {total} bytes is over the {V3_MAX_BYTES}-byte pi_api budget "
            f"({format_groups(groups)}); nothing was written. A file over it is served only on a "
            "measured admission record (pi-api-deploy.md §6): write it with --allow-over-gate"
        )
    return True


#: ``--allow-over-gate`` wrote a file over ``V3_MAX_BYTES``: never an ordinary success.
OVER_GATE_EXIT = 3


def write_v3(path: Path, body: bytes, products: int, groups: Mapping[str, int], over: bool) -> None:
    """Write the v3 body and report it. A body over the gate exits ``OVER_GATE_EXIT`` after it
    is written: the file exists to be measured, and pi_api serves it only on an admission record
    for the body the publisher uploads (pi-api-deploy.md §6). The sha256 printed here is of this
    file: advisory, since the publisher re-serialises it."""
    write_bytes(path, body)
    digest = sha256(path)
    print(
        f"wrote v3 {products} products to {path} sha256={digest} bytes={len(body)} "
        f"of {V3_MAX_BYTES} by group: {format_groups(groups)}"
    )
    if over:
        print(f"OVER GATE {path} {len(body)} sha256={digest}")
        print(
            f"over V3_MAX_BYTES={V3_MAX_BYTES}: not served until infra/pi-api/admission/ holds a "
            "passing record for the published body; this file's sha256 is advisory, the record "
            "keys on the body publish_dataset --dry-run reports (pi-api-deploy.md §6)",
            file=sys.stderr,
        )
        raise SystemExit(OVER_GATE_EXIT)


def write_json(path: Path, dataset: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(dataset, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(body)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database-url", required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--ulta-early-fixture", type=Path)
    result.add_argument("--ulta-captured-at")
    result.add_argument("--ulta-fixture-commit")
    result.add_argument("--ulta-recon-observed-count", type=int)
    result.add_argument("--ulta-recon-source")
    result.add_argument("--generated-at")
    result.add_argument(
        "--sources",
        type=lambda value: tuple(name.strip() for name in value.split(",") if name.strip()),
        default=DEFAULT_SOURCES,
        help="comma-separated source names to export (default: sephora_me only)",
    )
    result.add_argument("--ulta-blocked-since", default="2026-09-30T20:55:00Z")
    result.add_argument(
        "--ulta-unblocked",
        action="store_true",
        help="Ulta is collected again; its status then comes from its rows (default: blocked)",
    )
    result.add_argument("--ulta-blocked-note", help="Ulta status line while blocked (EN)")
    result.add_argument("--ulta-blocked-note-ar", help="the same line in Arabic (required with EN)")
    result.add_argument(
        "--output-v2", type=Path, help="also write the pi.dataset/v2 snapshot (ADR-0007 §6)"
    )
    result.add_argument(
        "--output-v3",
        type=Path,
        help="also write the v2 snapshot upgraded to pi.dataset/v3, with offer listingCount",
    )
    result.add_argument(
        "--allow-over-gate",
        action="store_true",
        help=(
            "write a v3 body over V3_MAX_BYTES anyway, then exit 3 (OVER GATE): it is served only "
            "on a measured admission record for its sha256 (pi-api-deploy.md §6)"
        ),
    )
    result.add_argument(
        "--history",
        action="store_true",
        help=(
            "v2/v3 carry every crawl day (Dubai market days) instead of one; days a retailer was "
            "not completely collected go into notObserved windows (history.py)"
        ),
    )
    result.add_argument("--scope", default="beauty", help="v2 meta.scope (a storage path segment)")
    result.add_argument("--producer-commit", help="v2 meta.producer.commit (git sha)")
    return result


def check_args(args: argparse.Namespace) -> None:
    """Reject argument combinations that would publish a contradictory or half-translated note."""
    fixture_args = (args.ulta_early_fixture, args.ulta_captured_at, args.ulta_fixture_commit)
    if any(value is not None for value in fixture_args) and not all(
        value is not None for value in fixture_args
    ):
        raise SystemExit(
            "--ulta-early-fixture, --ulta-captured-at and --ulta-fixture-commit "
            "must be supplied together"
        )
    if args.ulta_early_fixture is not None and args.ulta_recon_observed_count is None:
        # The status line says "0 products"; recon samples need the recon sentence next to it.
        raise SystemExit(
            "--ulta-early-fixture needs --ulta-recon-observed-count and --ulta-recon-source"
        )
    if not args.sources:
        raise SystemExit("--sources must name at least one source")
    if args.history and args.output_v2 is None and args.output_v3 is None:
        raise SystemExit("--history needs --output-v2 or --output-v3 (v1 has one date)")
    if args.history and args.ulta_early_fixture is not None:
        raise SystemExit(
            "--history does not take --ulta-early-fixture (recon samples have no days)"
        )
    if "ulta_ae" in args.sources and not args.ulta_unblocked:
        raise SystemExit("--sources ulta_ae needs --ulta-unblocked: Ulta is blocked by ruling")
    notes = (args.ulta_blocked_note, args.ulta_blocked_note_ar)
    if (notes[0] is None) != (notes[1] is None):
        raise SystemExit("--ulta-blocked-note and --ulta-blocked-note-ar must be supplied together")
    if any(note is not None and not note.strip() for note in notes):
        raise SystemExit("--ulta-blocked-note and --ulta-blocked-note-ar must not be empty")


def build_v1(
    args: argparse.Namespace,
    rows: Sequence[ListingRow],
    matches: Sequence[MatchRow],
    early: Sequence[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    """The v1 dataset, or ``None`` for a Faces-, Ounass- or Bloomingdale's-only export (an
    ADR-0010 per-source file): v1 is Ulta/Sephora only, and such an export must then write v2
    or v3."""
    if not v1_rows(rows) and not early:
        if args.output_v2 is None and args.output_v3 is None:
            raise SystemExit(f"--sources {','.join(args.sources)} has no v1: pass --output-v2/v3")
        return None
    return build_dataset(
        rows,
        matches,
        generated_at=generated_at,
        ulta_early=early,
        ulta=UltaContext(
            blocked_since=parse_utc(args.ulta_blocked_since),
            blocked=not args.ulta_unblocked,
            recon_observed_count=args.ulta_recon_observed_count,
            recon_source=args.ulta_recon_source,
            blocked_note=args.ulta_blocked_note or ULTA_BLOCKED_NOTE,
            blocked_note_ar=args.ulta_blocked_note_ar or ULTA_BLOCKED_NOTE_AR,
        ),
    )


def main() -> None:
    args = parser().parse_args()
    check_args(args)
    rows, matches = load_rows(args.database_url, args.sources)
    early: list[dict[str, Any]] = []
    if args.ulta_early_fixture is not None:
        early.append(
            parse_ulta_early_fixture(
                args.ulta_early_fixture,
                parse_utc(args.ulta_captured_at),
                args.ulta_fixture_commit,
            )
        )
    generated_at = parse_utc(args.generated_at) if args.generated_at else datetime.now(UTC)
    slots = export_slots(args.sources)
    dataset = build_v1(args, rows, matches, early, generated_at)
    ulta_note = dataset["meta"]["retailers"][0]["note"] if dataset is not None else {}
    if args.output_v2 is not None or args.output_v3 is not None:
        # Build v2 (and v3) first: if the contract refuses the data, no file is written.
        from pi_dataset import dump_dataset, load_any, load_dataset  # noqa: PLC0415
        from scripts.demo_export.v2 import (  # noqa: PLC0415
            build_dataset_v2,
            category_notes,
            price_review,
            to_v3,
        )

        v2_ulta = UltaContext(
            blocked_since=parse_utc(args.ulta_blocked_since), blocked=not args.ulta_unblocked
        )
        v2_rows = rows
        if args.history:
            from scripts.demo_export.history import (  # noqa: PLC0415
                Coverage,
                build_history_v2,
                latest_rows,
                load_history,
            )

            spans, days, matches = load_history(args.database_url, args.sources)
            cover = Coverage.of(spans)
            v2 = build_history_v2(
                days,
                cover,
                matches,
                generated_at=generated_at,
                ulta=v2_ulta,
                ulta_note=ulta_note,
                scope=args.scope,
                producer_commit=args.producer_commit,
                slots=slots,
            )
            v2_rows = latest_rows(days)
            complete = {s: sorted(d.isoformat() for d in v) for s, v in cover.complete.items()}
            print(
                f"history: dates={[d.isoformat() for d in v2.meta.dates]} "
                f"history={v2.meta.capabilities.history} complete={complete} "
                f"notObserved={len(v2.not_observed)}"
            )
        else:
            v2 = build_dataset_v2(
                rows,
                matches,
                generated_at=generated_at,
                ulta=v2_ulta,
                ulta_note=ulta_note,
                ulta_early=early,
                scope=args.scope,
                producer_commit=args.producer_commit,
                slots=slots,
            )
        body = dump_dataset(v2, compact=True)
        load_dataset(body)  # the publisher's strict load, credential scan included
        if args.output_v3 is not None:
            v3 = to_v3(v2, v2_rows, matches)
            body_v3 = dump_dataset(v3, compact=True)
            load_any(body_v3)  # the same strict load, as v3
            v3_groups = v3_bytes_by_group(v3, len(body_v3))
            v3_over = check_v3_size(len(body_v3), v3_groups, over_gate=args.allow_over_gate)
    if dataset is None:
        print(f"v1 not written to {args.output}: no Ulta/Sephora rows in {args.sources}")
    else:
        write_json(args.output, dataset)
        print(
            f"wrote {len(dataset['products'])} products to {args.output} "
            f"sha256={sha256(args.output)} cutoff={dataset['meta']['cutoff']}"
        )
    if args.output_v2 is not None:
        write_bytes(args.output_v2, body)
        print(
            f"wrote v2 {len(v2.products)} products to {args.output_v2} "
            f"sha256={sha256(args.output_v2)} cutoff={utc_text(v2.meta.cutoff)} "
            f"category_listings={category_notes(v2_rows)}"
        )
        review = price_review(v2)
        print(
            f"listing rows priced <= {PRICE_FLOOR} AED (shown only when the group has no valid "
            f"price; pi_api withholds them as priceFlag=invalid_low): {invalid_prices(v2_rows)}"
        )
        print(
            f"v2 listing rows={len(v2_rows)}; prices to check by hand (never changed): "
            f"below={len(review['below'])} {review['below'][:20]} "
            f"above={len(review['above'])} {review['above'][:20]}"
        )
    if args.output_v3 is not None:
        write_v3(args.output_v3, body_v3, len(v2.products), v3_groups, v3_over)


if __name__ == "__main__":
    main()
