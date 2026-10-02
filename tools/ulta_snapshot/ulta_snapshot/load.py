"""Load a downloaded ulta.ae snapshot (jsonl.gz page records) into pi_db, append-only, idempotent.

Usage: python -m ulta_snapshot.load <local_snapshot_dir> <uri_prefix> [--finish]
(env PI_DATABASE_URL; ULTA_USE_PAGE_JSON=1 enables the optional page-JSON path, default off;
it also needs ``<local_snapshot_dir>/robots.txt``, the robots.txt the runner obeyed).
Same loader contract as the Sephora baseline (task 01a0f424).

Input, one JSON object per line under ``pdp/`` (``part-NNNN.jsonl.gz``), written by the rung-5
runner for each product page load::

    {"at": ISO-8601 retrieved_at, "url": page URL, "lang": "en"|"ar", "status": int,
     "engine": "webkit", "egress": "iproyal_ae", "proxy_bytes": int,
     "html": rendered DOM,                                   # primary source
     "captures": [{"url": str, "status": int, "body": str}]} # optional page-loaded JSON

**Never loaded into prod ``ulta_ae``.** The owner's ``ulta_ae`` rows are protected: no PI action
may update, delete or degrade them. ``guard`` runs before the first write and refuses (exit 2,
nothing written) a prod database (``PROD_DATABASES``) and any database where ``ulta_ae`` holds a
row this loader did not write: a crawl run, context, listing, content row, offer or ``ulta_ae:``
brand alias without this loader's provenance (``CONNECTOR_VERSION``, ``CONTEXT_NOTE``,
``labels.loader``).

Primary source is the rendered DOM + JSON-LD (``pi_connector_ulta.dom``). Page-loaded catalog
JSON is read only when the flag is on, only from captures whose URL robots.txt allows (the same
``RobotsTagger`` rules as the fetch; ``Disallow: /*?`` refuses ``GET /graphql?query=...``, and
no robots.txt means no captures are read), and then only to fill what the DOM cannot show
(other variants' prices, EAN, promotions).

Grain: one source_listing per Ulta SKU (the sellable variant; the parent style code is in
listing_content.labels). Per page load, one offer_observation per variant: availability from the
variant's swatch (observed), price only where the page shows it (the selected variant; others
NULL + ``unknown``, never copied), rating from JSON-LD (style level). Free gifts and zero
placeholders are never prices (NULL + ``not_applicable``). Pages not fetched before the cutoff,
or blocked, get no rows (absent, never out of stock). Images: URLs only.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb

from pi_connector_ulta.catalog import CatalogError, UltaProduct, UltaVariant, parse_pdp_payload
from pi_connector_ulta.dom import merge_page_json, parse_pdp_html
from pi_fetch.pacing import RobotsTag, RobotsTagger

SOURCE = "ulta_ae"
CONNECTOR_VERSION = "ulta_snapshot/0.1"
TZ = "Asia/Dubai"
RETENTION = timedelta(days=90)
FETCH_METHOD = "residential_proxy"  # rung 5, ulta.ae only
RUNG = 5
LANGS = ("en", "ar")
HOSTS = frozenset({"ulta.ae", "www.ulta.ae"})
CONTEXT_NOTE = "one snapshot, no recurring crawl"
#: The live pi_db database name (docs/runbooks/db-backup-restore.md). Never loaded.
PROD_DATABASES = frozenset({"pi"})

#: Rows under ulta_ae (or ulta_ae: brand aliases) that this loader did not write. Read only.
FOREIGN_SQL = """
WITH s AS (SELECT id FROM source WHERE name = %(source)s),
ours AS (
    SELECT r.id FROM crawl_run r JOIN source_context c ON c.id = r.source_context_id
    WHERE c.source_id IN (SELECT id FROM s) AND r.connector_version = %(version)s
)
SELECT
  (SELECT count(*) FROM source_context c WHERE c.source_id IN (SELECT id FROM s)
     AND c.refresh_policy->>'note' IS DISTINCT FROM %(note)s),
  (SELECT count(*) FROM crawl_run r JOIN source_context c ON c.id = r.source_context_id
     WHERE c.source_id IN (SELECT id FROM s) AND r.id NOT IN (SELECT id FROM ours)),
  (SELECT count(*) FROM source_listing sl WHERE sl.source_id IN (SELECT id FROM s)
     AND NOT EXISTS (SELECT 1 FROM offer_observation o WHERE o.source_listing_id = sl.id
                     AND o.crawl_run_id IN (SELECT id FROM ours))),
  (SELECT count(*) FROM offer_observation o JOIN source_listing sl ON sl.id = o.source_listing_id
     WHERE sl.source_id IN (SELECT id FROM s)
     AND NOT EXISTS (SELECT 1 FROM ours WHERE ours.id = o.crawl_run_id)),
  (SELECT count(*) FROM listing_content lc JOIN source_listing sl ON sl.id = lc.listing_id
     WHERE sl.source_id IN (SELECT id FROM s)
     AND lc.labels->>'loader' IS DISTINCT FROM %(version)s),
  (SELECT count(*) FROM brand b, unnest(b.aliases) a WHERE a LIKE %(source)s || ':%%'
     AND NOT EXISTS (
       SELECT 1 FROM listing_content lc JOIN source_listing sl ON sl.id = lc.listing_id
       WHERE sl.source_id IN (SELECT id FROM s) AND lc.labels->>'loader' = %(version)s
       AND %(source)s || ':' || (lc.labels->>'brand_key') = a))
"""
FOREIGN_KINDS = (
    "source_context",
    "crawl_run",
    "source_listing",
    "offer_observation",
    "listing_content",
    "brand_alias",
)


class Refused(RuntimeError):  # noqa: N818
    """The loader would touch prod or ulta_ae rows it did not write; nothing was written."""

    def __init__(self, message: str, foreign: dict[str, int] | None = None) -> None:
        super().__init__(message)
        self.foreign = foreign or {}


def guard(conn: psycopg.Connection[Any]) -> None:
    """Hard pre-write guard. Reads only; raises ``Refused`` before any write."""
    name = conn.info.dbname
    if name in PROD_DATABASES:
        raise Refused(f"refused: {name!r} is the prod database; never loaded into prod ulta_ae")
    row = conn.execute(
        FOREIGN_SQL, {"source": SOURCE, "version": CONNECTOR_VERSION, "note": CONTEXT_NOTE}
    ).fetchone()
    foreign = {k: int(n) for k, n in zip(FOREIGN_KINDS, row or (), strict=True) if n}
    if foreign:
        raise Refused(f"refused: {SOURCE} holds rows this loader did not write: {foreign}", foreign)


def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def allowed_captures(
    rec: dict[str, Any], robots: RobotsTagger | None
) -> tuple[list[dict[str, Any]], int]:
    """Captures robots.txt allows (ulta.ae host, 200), and the number refused.

    Fails closed: with no robots rules, or a host whose robots.txt is unknown, nothing is usable.
    A refused capture is never parsed, hashed or stored.
    """
    usable: list[dict[str, Any]] = []
    refused = 0
    for cap in rec.get("captures") or []:
        url = str(cap.get("url") or "")
        parts = urlsplit(url)
        host = (parts.hostname or "").lower() if parts.scheme == "https" else ""
        if (
            robots is None
            or host not in HOSTS
            or robots.tag(host, url) is not RobotsTag.ALLOWED
            or cap.get("status") != 200
        ):
            refused += 1
            continue
        usable.append(cap)
    return usable, refused


def _page_json(
    captures: list[dict[str, Any]], lang: str, sku: str, locale: str
) -> UltaProduct | None:
    for cap in captures:
        try:
            products = parse_pdp_payload(cap.get("body") or "", lang)
        except CatalogError:
            continue
        for product in products:
            if product.sku == sku and product.locale == locale:
                return product
    return None


def page_product(rec: dict[str, Any], robots: RobotsTagger | None = None) -> UltaProduct | None:
    """The page's product from its rendered DOM. Page JSON fills DOM gaps only when ``robots``
    is given (the page-JSON flag is on), and only from captures it allows."""
    try:
        product = parse_pdp_html(rec.get("html") or "", rec["lang"])
    except CatalogError:
        return None
    if robots is not None:
        captures, _ = allowed_captures(rec, robots)
        found = _page_json(captures, rec["lang"], product.sku, rec["lang"])
        product = merge_page_json(product, found)
    return product


def robots_for(root: Path, enabled: bool) -> RobotsTagger | None:
    """The robots rules for page-JSON captures: None (page JSON off) unless the flag is on and
    the snapshot carries the robots.txt the runner obeyed."""
    path = root / "robots.txt"
    if not enabled:
        return None
    if not path.exists():
        print("page JSON off: snapshot has no robots.txt", file=sys.stderr)
        return None
    tagger = RobotsTagger()
    for host in HOSTS:
        tagger.add(host, path.read_text())
    return tagger


class Loader:
    def __init__(self, conn: psycopg.Connection[Any], root: Path, uri: str) -> None:
        self.c = conn
        self.root = root
        self.uri = uri.rstrip("/")
        progress = root / "progress.json"
        self.progress = json.loads(progress.read_text()) if progress.exists() else {}
        #: Keyed by the snapshot id when there is one, so later cumulative uploads of the same
        #: snapshot (copied beside this one) skip the parts already loaded.
        key = self.progress.get("snapshot_id") or root.name
        guard(conn)  # before any write, including the ledger's source/context/run rows
        self.ledger = root.parent / f".loaded-{key}.json"  # snapshot dir may be read-only
        self.done: set[str] = (
            set(json.loads(self.ledger.read_text())) if self.ledger.exists() else set()
        )
        self.source_id = self._source()
        self.ctx = {lang: self._context(lang) for lang in LANGS}
        self.run_id = {lang: self._run(lang) for lang in LANGS}
        self.robots = robots_for(root, os.environ.get("ULTA_USE_PAGE_JSON") == "1")

    # ------------------------------------------------------------ reference rows
    def _one(self, sql: str, args: tuple[Any, ...]) -> int | None:
        row = self.c.execute(sql, args).fetchone()
        return int(row[0]) if row else None

    def _id(self, sql: str, args: tuple[Any, ...]) -> int:
        """An INSERT ... RETURNING id that always returns a row."""
        found = self._one(sql, args)
        if found is None:
            raise RuntimeError("insert returned no id")
        return found

    def _source(self) -> int:
        sid = self._one("SELECT id FROM source WHERE name=%s", (SOURCE,))
        return sid or self._id(
            "INSERT INTO source (name, kind, base_url, notes) VALUES (%s,'web',%s,%s) RETURNING id",
            (SOURCE, "https://www.ulta.ae", "Ulta Beauty UAE (Alshaya); /en, /ar storefronts"),
        )

    def _context(self, lang: str) -> int:
        locale = f"{lang}-AE"
        cid = self._one(
            "SELECT id FROM source_context WHERE source_id=%s AND country='AE' AND locale=%s"
            " AND valid_to IS NULL",
            (self.source_id, locale),
        )
        return cid or self._id(
            "INSERT INTO source_context (source_id, country, channel, locale, time_zone,"
            " ladder_rung_current, ladder_rung_max_allowed, coverage_status, refresh_policy)"
            " VALUES (%s,'AE','online',%s,%s,%s,%s,'partial',%s) RETURNING id",
            (
                self.source_id,
                locale,
                TZ,
                RUNG,
                RUNG,  # rung 5, ulta.ae only
                Jsonb(
                    {
                        "mode": "on_demand",
                        "note": CONTEXT_NOTE,
                    }
                ),
            ),
        )

    def _run(self, lang: str) -> int:
        manifest = f"{self.uri}/progress.json#lang={lang}"
        rid = self._one("SELECT id FROM crawl_run WHERE manifest_uri=%s", (manifest,))
        started = self.progress.get("started") or datetime.now(UTC).isoformat()
        return rid or self._id(
            "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
            " started_at, manifest_uri) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (self.ctx[lang], CONNECTOR_VERSION, RUNG, started, manifest),
        )

    def _brand(self, p: UltaProduct) -> None:
        if not p.brand_key or not p.brand:
            return
        alias = f"{SOURCE}:{p.brand_key}"
        bid = self._one("SELECT id FROM brand WHERE %s = ANY(aliases)", (alias,))
        if p.locale == "en":
            bid = self._one(
                "INSERT INTO brand (name, aliases) VALUES (%s,%s) ON CONFLICT (name) DO UPDATE"
                " SET aliases=(SELECT array_agg(DISTINCT a)"
                " FROM unnest(brand.aliases || EXCLUDED.aliases) a) RETURNING id",
                (p.brand, [alias]),
            )
        elif bid:
            self.c.execute(
                "UPDATE brand SET name_ar=COALESCE(name_ar,%s) WHERE id=%s", (p.brand, bid)
            )

    def _evidence(self, rec: dict[str, Any], uri: str) -> int:
        existing = self._one("SELECT id FROM evidence WHERE storage_uri=%s", (uri,))
        if existing:
            return existing  # replay: evidence is append-only, never duplicated
        at = datetime.fromisoformat(rec["at"])
        captures, _ = allowed_captures(rec, self.robots)
        bodies = [c.get("body") or "" for c in captures]
        return self._id(
            "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
            " http_status, ladder_rung_used, fetch_method, retention_until)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                self.run_id[rec["lang"]],
                rec["url"],
                _sha(rec.get("html") or "", *bodies),  # the rendered DOM is the evidence
                uri,
                at,
                rec.get("status"),
                RUNG,
                FETCH_METHOD,
                at + RETENTION,
            ),
        )

    def _listing(self, v: UltaVariant, p: UltaProduct, url: str, at: datetime) -> int:
        en = p.locale == "en"
        return self._id(
            "INSERT INTO source_listing (source_id, source_listing_key, source_sku, url,"
            " name_original, name_ar, lang, category_path_source, first_seen_at, last_seen_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (source_id, source_listing_key) DO UPDATE SET"
            " last_seen_at=GREATEST(source_listing.last_seen_at, EXCLUDED.last_seen_at),"
            " first_seen_at=LEAST(source_listing.first_seen_at, EXCLUDED.first_seen_at),"
            " name_original=CASE WHEN EXCLUDED.lang='en' THEN EXCLUDED.name_original"
            " ELSE source_listing.name_original END,"
            " url=CASE WHEN EXCLUDED.lang='en' THEN EXCLUDED.url ELSE source_listing.url END,"
            " category_path_source=CASE WHEN EXCLUDED.lang='en' THEN EXCLUDED.category_path_source"
            " ELSE source_listing.category_path_source END,"
            " lang=CASE WHEN EXCLUDED.lang='en' THEN 'en' ELSE source_listing.lang END,"
            " name_ar=COALESCE(EXCLUDED.name_ar, source_listing.name_ar)"
            " RETURNING id",
            (
                self.source_id,
                v.sku,
                v.sku,
                url,
                p.name,
                None if en else p.name,
                p.locale,
                p.category_path,
                at,
                at,
            ),
        )

    # ------------------------------------------------------------ PDP
    def pdp(self, rec: dict[str, Any], uri: str) -> int:
        if rec.get("status") != 200:
            return 0
        product = page_product(rec, self.robots)
        if product is None or not product.variants:
            return 0  # block page or not a product: no rows (absent, never out of stock)
        at = datetime.fromisoformat(rec["at"])
        ev = self._evidence(rec, uri)
        self._brand(product)
        url = f"https://www.ulta.ae/{product.locale}/{product.url_key}"
        for v in product.variants:
            lid = self._listing(v, product, url, at)
            self._content(lid, product, v, at, uri)
            self._offer(lid, product, v, rec["at"], ev)
        return len(product.variants)

    def _content(self, lid: int, p: UltaProduct, v: UltaVariant, at: datetime, uri: str) -> None:
        labels = {
            "style_code": p.sku,
            "lang": p.locale,
            "product_name": p.name,
            "variant_name": v.name,
            "category_path": p.category_path,
            "brand_key": p.brand_key,
            "source_path": p.kind,
            # pi_match export keys (PR #24): brand/size/shade/gtin.
            "brand": p.brand,
            "size": " ".join(x for x in (v.size, v.size_uom) if x) or None,
            "shade": v.shade,
            "shade_description": v.shade_description,
            "gtin": v.barcode,
            "variant_label": v.shade or v.size,
            "variant_kind": "shade" if v.shade else ("size" if v.size else None),
            "images": [
                {"role": "main" if i == 0 else "alt", "position": i, "url": u}
                for i, u in enumerate(v.images)
            ],
            "product_labels": list(v.labels),
            "promotions": list(v.promotions),
            "member_price": str(v.member_price.amount) if v.member_price.amount else None,
            "free_gift": v.free_gift,
            "evidence_uri": uri,
            "loader": CONNECTOR_VERSION,  # provenance read by guard()
        }
        content = json.dumps(labels, sort_keys=True, ensure_ascii=False) + (p.description or "")
        en = p.locale == "en"
        self.c.execute(
            "INSERT INTO listing_content (listing_id, observed_at, description, description_ar,"
            " badges, labels, content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                lid,
                at,
                p.description if en else None,
                None if en else p.description,
                list(v.labels),
                Jsonb(labels),
                _sha(content),
            ),
        )

    def _offer(self, lid: int, p: UltaProduct, v: UltaVariant, at_raw: str, ev: int) -> None:
        at = datetime.fromisoformat(at_raw)
        cur = v.current
        promo = v.promotional
        fs: dict[str, str] = {}
        if cur.amount is None:
            fs["price_current"] = cur.reason or "unknown"
        if p.rating_count is None:
            fs["rating_value"] = fs["rating_count"] = "not_published"
        if v.in_stock is None:
            state = "not_observed"  # no stock shown, or swatches contradict the JSON-LD offer
            fs["availability_state"] = "unknown"
        else:
            state = "in_stock" if v.in_stock else "out_of_stock"
            fs["availability_state"] = "observed"
        priced = cur.amount is not None
        self.c.execute(
            "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
            " source_listing_id, observed_at, ingested_at, price_current, price_regular_stated,"
            " price_promo, price_type, currency, availability_state, rating_value, rating_scale,"
            " rating_count, badges_at_time, field_state, evidence_id)"
            " VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT DO NOTHING",
            (
                _sha(SOURCE, p.locale, "pdp", v.sku, at_raw),
                self.run_id[p.locale],
                self.ctx[p.locale],
                lid,
                at,
                cur.amount,
                v.regular.amount if promo else None,
                v.final.amount if promo else None,
                ("promotional" if promo else "full") if priced else None,
                cur.currency if priced else None,
                state,
                p.rating_average,
                5 if p.rating_count else None,
                p.rating_count,
                list(v.labels) + list(v.promotions),
                Jsonb(fs),
                ev,
            ),
        )

    # ------------------------------------------------------------ driver
    def load(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        for stream in ("pdp",):  # category pages feed discovery only
            folder = self.root / stream
            for part in sorted(folder.glob("part-*.jsonl.gz")) if folder.exists() else []:
                rel = f"{stream}/{part.name}"
                if rel in self.done:
                    continue
                with gzip.open(part, "rt", encoding="utf-8") as fh:
                    for i, line in enumerate(fh):
                        rec = json.loads(line)
                        uri = f"{self.uri}/{rel}#L{i + 1}"
                        stats[stream] = stats.get(stream, 0) + self.pdp(rec, uri)
                self.c.commit()
                self.done.add(rel)
                self.ledger.write_text(json.dumps(sorted(self.done)))
        return stats

    def finish(self) -> None:
        by_lang = self.progress.get("counts", {})  # {"en": {...}, "ar": {...}}
        status = "succeeded" if self.progress.get("stopped") == "complete" else "partial"
        for lang in LANGS:
            counts = by_lang.get(lang) or {}
            blocked = sum(v for k, v in counts.items() if k.startswith("block_"))
            self.c.execute(
                "UPDATE crawl_run SET finished_at=%s, status=%s, discovered=%s, fetched=%s,"
                " parsed=%s, blocked_count=%s WHERE id=%s",
                (
                    self.progress.get("updated"),
                    status,
                    counts.get("discovered", 0),
                    counts.get("pdp_ok", 0),
                    counts.get("pdp_parsed", 0),
                    blocked,
                    self.run_id[lang],
                ),
            )
        self.c.commit()


def main() -> int:
    root, uri = Path(sys.argv[1]), sys.argv[2]
    url = os.environ["PI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        try:
            loader = Loader(conn, root, uri)
        except Refused as exc:
            print(str(exc), file=sys.stderr)
            return 2
        conn.commit()
        print(json.dumps(loader.load()))
        if "--finish" in sys.argv:
            loader.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
