"""Load a downloaded Sephora snapshot (jsonl.gz parts) into pi_db, append-only and idempotent.

Usage: python -m sephora_snapshot.load <local_snapshot_dir> <gcs_uri_prefix> [--finish]
       [--country AE|SA]

--country picks the storefront the snapshot was taken from (default AE). Each country is its own
source (sephora_me for the UAE, sephora_sa for Saudi Arabia): a Saudi load never upserts, touches
or re-dates a UAE listing, and the two never share an idempotency key. A price in any currency
other than the country's own is recorded as unknown, never converted.

Grain: one source_listing per Sephora variant id (SourceListingKey = SKU id, e.g. "712845";
the master product id "P…" is kept in listing_content.labels). One offer_observation per
variant per fetch: PDP rows carry price/rating (availability 'not_observed' — the PDP is not
used as a stock signal); tRPC rows carry availability (price NULL, field_state 'unknown').
observed_at is always the fetch's retrieved_at, never load time. Products not fetched before
the cutoff get NO rows (absent, not out of stock). Images: URLs only (not downloaded).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

CONNECTOR_VERSION = "sephora_snapshot/0.1"
RETENTION = timedelta(days=90)
# pi_db FETCH_METHOD_RUNG: the site JSON API is rung 0, the PDP HTML fetch is plain HTTP (rung 1).
METHOD_RUNG = {"site_api": 0, "plain_http": 1}


@dataclass(frozen=True)
class Market:
    """One Sephora storefront: its own pi_db source, context country, time zone and currency."""

    source: str
    country: str
    time_zone: str
    currency: str
    notes: str


MARKETS = {
    "AE": Market(
        "sephora_me",
        "AE",
        "Asia/Dubai",
        "AED",
        "Sephora Middle East; UAE storefront /ae-en, /ae-ar",
    ),
    "SA": Market(
        "sephora_sa",
        "SA",
        "Asia/Riyadh",
        "SAR",
        "Sephora Middle East; Saudi storefront /sa-en, /sa-ar",
    ),
}
SOURCE = MARKETS["AE"].source  # the UAE source name, kept for existing callers


def _money(v: Any) -> Decimal | None:
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) and v > 0:
        return Decimal(str(v))
    return None


def _num(v: Any) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _json_default(v: Any) -> Any:
    if isinstance(v, Decimal):  # records are parsed with parse_float=Decimal
        return int(v) if v == v.to_integral_value() else float(v)
    raise TypeError(f"not JSON serialisable: {type(v).__name__}")


def _jsonb(v: Any) -> Jsonb:
    return Jsonb(v, dumps=lambda o: json.dumps(o, default=_json_default))


# A full run is 'succeeded' only if nothing was skipped: every seeded page and stock read was
# attempted and came back 200 and parsed. Any of these counters > 0 makes the run 'partial'.
_SKIP_PREFIXES = (
    "block_",
    "transport_error",
    "sitemap_fail",
    "pdp_en_http_",
    "pdp_ar_http_",
    "hop_",  # a redirect hop refused (host or robots) or a redirect chain too long
    "host_refused",  # a seed or plan URL off the storefront host, never requested
    "too_large",  # a body over its byte cap, dropped
)
_SKIP_SUFFIXES = ("_parse_error",)


def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _images(d: dict[str, Any], v: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, img in enumerate(v.get("images") or d.get("images") or []):
        url = img.get("disBaseLink") or img.get("link")
        if url:
            out.append({"role": "main" if i == 0 else "alt", "position": i, "url": url})
    if v.get("swatchImage"):
        out.append({"role": "swatch", "position": 0, "url": v["swatchImage"]})
    return out


class Loader:
    def __init__(
        self, conn: psycopg.Connection[Any], root: Path, gcs: str, market: Market = MARKETS["AE"]
    ) -> None:
        self.c = conn
        self.market = market
        self.root = root
        self.gcs = gcs.rstrip("/")
        self.ledger = root.parent / f".loaded-{root.name}.json"  # snapshot dir may be read-only
        self.done: set[str] = (
            set(json.loads(self.ledger.read_text())) if self.ledger.exists() else set()
        )
        self.progress = (
            json.loads((root / "progress.json").read_text())
            if (root / "progress.json").exists()
            else {}
        )
        self.source_id = self._source()
        self.ctx = {lang: self._context(lang) for lang in ("en", "ar")}
        self._runs: dict[str, int] = {}  # crawl_run per lang, created on first row
        self.brands: dict[str, int] = {}
        self.listings: dict[str, int] = {}
        self.stats: dict[str, int] = {}  # data-quality counters, printed after a load
        self.part_complete = True

    def bump(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    # ------------------------------------------------------------ reference rows
    def _one(self, sql: str, args: tuple[Any, ...]) -> int | None:
        row = self.c.execute(sql, args).fetchone()
        return int(row[0]) if row else None

    def _new(self, sql: str, args: tuple[Any, ...]) -> int:
        """An INSERT ... RETURNING id that must yield a row."""
        rid = self._one(sql, args)
        if rid is None:
            raise RuntimeError(f"no id returned: {sql[:60]}")
        return rid

    def _source(self) -> int:
        m = self.market
        sid = self._one("SELECT id FROM source WHERE name=%s", (m.source,))
        return sid or self._new(
            "INSERT INTO source (name, kind, base_url, notes) VALUES (%s,'web',%s,%s) RETURNING id",
            (m.source, "https://www.sephora.me", m.notes),
        )

    def _context(self, lang: str) -> int:
        m = self.market
        locale = f"{lang}-{m.country}"
        cid = self._one(
            "SELECT id FROM source_context WHERE source_id=%s AND country=%s AND locale=%s AND"
            " valid_to IS NULL",
            (self.source_id, m.country, locale),
        )
        return cid or self._new(
            "INSERT INTO source_context (source_id, country, channel, locale, time_zone,"
            " ladder_rung_current,"
            " coverage_status, refresh_policy) VALUES (%s,%s,'online',%s,%s,1,'partial',%s)"
            " RETURNING id",
            (
                self.source_id,
                m.country,
                locale,
                m.time_zone,
                _jsonb({"mode": "on_demand", "note": "owner: baseline + on-demand refresh"}),
            ),
        )

    def _existing_run(self, lang: str) -> int | None:
        manifest = f"{self.gcs}/progress.json#lang={lang}"
        return self._one("SELECT id FROM crawl_run WHERE manifest_uri=%s", (manifest,))

    def run_id(self, lang: str) -> int:
        """The lang's crawl_run, created only once a row is loaded for it.

        A continuation run that fetched no pages in a lang must not leave an empty run behind.
        """
        if lang not in self._runs:
            self._runs[lang] = self._existing_run(lang) or self._run(lang)
        return self._runs[lang]

    def _run(self, lang: str) -> int:
        manifest = f"{self.gcs}/progress.json#lang={lang}"
        started = self.progress.get("started") or datetime.now(UTC).isoformat()
        return self._new(
            "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
            " started_at, manifest_uri)"
            " VALUES (%s,%s,1,%s,%s) RETURNING id",
            (self.ctx[lang], CONNECTOR_VERSION, started, manifest),
        )

    def _brand(self, b: dict[str, Any], lang: str) -> int | None:
        name = (b or {}).get("name")
        bid_key = (b or {}).get("id") or name
        if not name or not bid_key:
            return None
        if bid_key in self.brands:
            return self.brands[bid_key]
        alias = f"{self.market.source}:{bid_key}"
        own = self.market.source.replace("_", "\\_") + ":%"  # LIKE pattern (a bound value)
        if lang == "en":
            # Never write a brand row this loader did not create: another source's load (e.g.
            # ulta_ae) may own a row with the same name, and it must stay untouched (owner rule
            # 2026-10-01). On a name clash the brand is not recorded and the clash is counted.
            self.c.execute(
                "INSERT INTO brand (name, aliases) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (name, [alias]),
            )
            bid = self._one(
                "SELECT id FROM brand WHERE name=%s AND EXISTS"
                " (SELECT 1 FROM unnest(aliases) a WHERE a LIKE %s)",
                (name, own),
            )
            if bid is None:
                self.bump("brand_name_clash")
        else:
            bid = self._one("SELECT id FROM brand WHERE %s = ANY(aliases)", (alias,))
            if bid:
                # Only fill a missing Arabic name on a row Sephora alone owns: a row that also
                # carries another source's alias (e.g. ulta_ae merged in) is never written, and
                # neither is a row whose name_ar is already set (no no-op row versions).
                cur = self.c.execute(
                    "UPDATE brand SET name_ar=%s WHERE id=%s AND name_ar IS NULL AND NOT EXISTS"
                    " (SELECT 1 FROM unnest(aliases) a WHERE a NOT LIKE %s)",
                    (name, bid, own),
                )
                if cur.rowcount == 0:
                    self.bump("brand_name_ar_skipped")
        if bid:
            self.brands[bid_key] = bid
        return bid

    def _evidence(self, lang: str, rec: dict[str, Any], uri: str, method: str) -> int:
        body = json.dumps(
            rec.get("extract") or rec.get("json") or rec.get("text"),
            sort_keys=True,
            ensure_ascii=False,
            default=_json_default,
        )
        at = datetime.fromisoformat(rec["at"])
        existing = self._one("SELECT id FROM evidence WHERE storage_uri=%s", (uri,))
        if existing:
            return existing  # replay: evidence is append-only, never duplicated
        return self._new(
            "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
            " http_status,"
            " ladder_rung_used, fetch_method, retention_until) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " RETURNING id",
            (
                self.run_id(lang),
                rec["url"],
                _sha(body),
                uri,
                at,
                rec.get("status"),
                METHOD_RUNG[method],
                method,
                at + RETENTION,
            ),
        )

    def _listing(  # noqa: PLR0913 - one column per argument
        self,
        key: str,
        url: str,
        name: str,
        lang: str,
        *,
        cat: str | None,
        at: datetime,
        name_ar: str | None = None,
    ) -> int:
        lid = self._new(
            "INSERT INTO source_listing (source_id, source_listing_key, source_sku, url,"
            " name_original, name_ar, lang,"
            " category_path_source, first_seen_at, last_seen_at) VALUES"
            " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (source_id, source_listing_key) DO UPDATE SET"
            " last_seen_at=GREATEST(source_listing.last_seen_at, EXCLUDED.last_seen_at),"
            " first_seen_at=LEAST(source_listing.first_seen_at, EXCLUDED.first_seen_at),"
            " name_ar=COALESCE(EXCLUDED.name_ar, source_listing.name_ar)"
            " RETURNING id",
            (self.source_id, key, key, url, name, name_ar, lang, cat, at, at),
        )
        self.listings[key] = lid
        return lid

    # ------------------------------------------------------------ PDP
    def pdp(self, lang: str, rec: dict[str, Any], uri: str) -> int:
        d = rec["extract"]["productDetails"]
        at = datetime.fromisoformat(rec["at"])
        ev = self._evidence(lang, rec, uri, "plain_http")
        self._brand(d.get("c_brand") or {}, lang)
        master = (d.get("master") or {}).get("masterId") or d["id"]
        crumbs = " > ".join(c.get("name") or "" for c in d.get("c_breadcrumbs") or [])
        ld: dict[str, Any] = next(
            (b for b in rec["extract"].get("jsonld", []) if b.get("@type") == "Product"), {}
        )
        rating = d.get("c_bvAverageRating")
        count = d.get("c_bvReviewCount")
        scale = d.get("c_bvRatingRange") or 5
        has_rating = _num(rating) and isinstance(count, int) and count > 0
        n = 0
        for v in d.get("c_variantsInfo") or []:
            key = str(v["product_id"])
            lid: int | None
            if lang == "en":
                lid = self._listing(
                    key, rec["url"], d.get("name") or "", "en", cat=crumbs or None, at=at
                )
            else:
                lid = self._one(
                    "SELECT id FROM source_listing WHERE source_id=%s AND source_listing_key=%s",
                    (self.source_id, key),
                )
                if lid is None:
                    lid = self._listing(
                        key,
                        rec["url"],
                        d.get("name") or "",
                        "ar",
                        cat=crumbs or None,
                        at=at,
                        name_ar=d.get("name"),
                    )
                else:
                    self.c.execute(
                        "UPDATE source_listing SET name_ar=COALESCE(name_ar,%s) WHERE id=%s",
                        (d.get("name"), lid),
                    )
            labels = {
                "master_id": master,
                "page_product_id": d["id"],
                "lang": lang,
                "brand_id": (d.get("c_brand") or {}).get("id"),
                "brand_name": (d.get("c_brand") or {}).get("name"),
                "product_name": d.get("name"),
                "variant_name": v.get("c_variant_name"),
                "variant_label": v.get("c_variation_attribute_name"),
                "variant_kind": "size" if v.get("c_isSizeVariationTemplate") else "shade",
                # pi_match export keys (PR #24): brand/size/shade/gtin. Sephora publishes no GTIN.
                "brand": (d.get("c_brand") or {}).get("name"),
                "size": v.get("c_variation_attribute_name")
                if v.get("c_isSizeVariationTemplate")
                else None,
                "shade": None
                if v.get("c_isSizeVariationTemplate")
                else v.get("c_variation_attribute_name"),
                "gtin": None,
                "price_per_quantity_unit": v.get("c_pricePerQuantityUnit"),
                "prior_price_flag": v.get("c_isPriorPriceProduct"),
                "variation": v.get("c_variation"),
                # product-level on sephora.me (the variants never carry it)
                "responsible_beauty": d.get("c_responsibleBeauty") or v.get("c_responsibleBeauty"),
                "more_information": d.get("c_moreInformation"),  # free-text claims; internal only
                "notes": d.get("c_notes"),  # fragrance notes
                "breadcrumbs": d.get("c_breadcrumbs"),
                "images": _images(d, v),
                "product_nature": d.get("c_productNature"),
                "product_range": d.get("c_productRange"),
                "promotions": [
                    p.get("promotionTitle")
                    for p in d.get("c_product_promotions") or []
                    if isinstance(p, dict)
                ],
                "variants_count": d.get("c_variantsCount"),
                "evidence_uri": uri,
            }
            desc = ld.get("description") if isinstance(ld, dict) else None
            content = json.dumps(
                labels, sort_keys=True, ensure_ascii=False, default=_json_default
            ) + (desc or "")
            self.c.execute(
                "INSERT INTO listing_content (listing_id, observed_at, description,"
                " description_ar, badges, labels,"
                " content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    lid,
                    at,
                    desc if lang == "en" else None,
                    desc if lang == "ar" else None,
                    [f.get("text1") for f in v.get("c_productFlags") or [] if f.get("text1")],
                    _jsonb(labels),
                    _sha(content),
                ),
            )
            regular = _money(v.get("c_price"))
            sale = _money(v.get("c_salesPrice"))
            promo = sale is not None and regular is not None and sale < regular
            fs: dict[str, str] = {}
            price = sale if promo else regular
            currency = d.get("currency")
            if price is not None and not currency:  # never assume the market's currency
                price = regular = sale = None
                promo = False
                fs["price_current"] = "unknown"
                self.bump("price_without_currency")
            elif price is not None and currency != self.market.currency:
                # e.g. an AED page in a Saudi snapshot: never stored as if it were SAR
                price = regular = sale = None
                promo = False
                fs["price_current"] = "unknown"
                self.bump("price_currency_mismatch")
            elif price is None:
                fs["price_current"] = "not_published"
            if not has_rating:
                fs["rating_value"] = "not_published"
                fs["rating_count"] = "not_published"
            self.c.execute(
                "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
                " source_listing_id,"
                " observed_at, ingested_at, price_current, price_regular_stated, price_promo,"
                " price_type, currency,"
                " availability_state, rating_value, rating_scale, rating_count, badges_at_time,"
                " field_state, evidence_id)"
                " VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,'not_observed',%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (
                    _sha(self.market.source, lang, "pdp", key, rec["at"]),
                    self.run_id(lang),
                    self.ctx[lang],
                    lid,
                    at,
                    price,
                    regular if promo else None,
                    sale if promo else None,
                    ("promotional" if promo else "full") if price is not None else None,
                    currency if price is not None else None,
                    Decimal(str(rating)) if has_rating else None,
                    Decimal(str(scale)) if has_rating else None,
                    count if has_rating else None,
                    [f.get("text1") for f in v.get("c_productFlags") or [] if f.get("text1")],
                    _jsonb(fs),
                    ev,
                ),
            )
            n += 1
        return n

    # ------------------------------------------------------------ tRPC availability
    def trpc(self, rec: dict[str, Any], uri: str) -> int:
        try:
            data = rec["json"][0]["result"]["data"]["json"]
        except (KeyError, IndexError, TypeError):
            if rec.get("status") == 200:  # a 200 we cannot read: never a complete run
                self.bump("trpc_unparsed")
                self.part_complete = False
            return 0
        if not isinstance(data, dict):  # e.g. a 200 with "json": null: no stock read at all
            self.bump("trpc_no_data")
            self.part_complete = False  # keep the part unledgered so --finish still sees it
            return 0
        at = datetime.fromisoformat(rec["at"])
        ev = self._evidence("en", rec, uri, "site_api")
        n = 0
        for v in data.get("c_variantsInfo") or []:
            key = str(v.get("product_id"))
            lid = self.listings.get(key) or self._one(
                "SELECT id FROM source_listing WHERE source_id=%s AND source_listing_key=%s",
                (self.source_id, key),
            )
            if lid is None:  # its PDP is not loaded (yet): keep the part unledgered, retry later
                self.bump("trpc_missing_listing")
                self.part_complete = False
                continue
            in_stock = v.get("inStock")
            if in_stock is None:  # no stock state published: no observation, but counted
                self.bump("trpc_instock_unknown")
                continue
            low = bool(v.get("isLowStock")) if in_stock else False
            state = "low_stock" if low else ("in_stock" if in_stock else "out_of_stock")
            days = (v.get("warehouseStock") or {}).get("daysToDeliver")
            self.c.execute(
                "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
                " source_listing_id,"
                " observed_at, ingested_at, availability_state, low_stock_flag, delivery_promise,"
                " field_state, evidence_id)"
                " VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    _sha(self.market.source, "en", "trpc", key, rec["at"]),
                    self.run_id("en"),
                    self.ctx["en"],
                    lid,
                    at,
                    state,
                    low,
                    f"{days} day(s)" if isinstance(days, int) else None,
                    _jsonb({"availability_state": "observed", "price_current": "unknown"}),
                    ev,
                ),
            )
            n += 1
        return n

    # ------------------------------------------------------------ driver
    def load(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        order = ["pdp_en", "trpc", "pdp_ar"]
        for stream in order:
            for part in (
                sorted((self.root / stream).glob("part-*.jsonl.gz"))
                if (self.root / stream).exists()
                else []
            ):
                rel = f"{stream}/{part.name}"
                if rel in self.done:
                    continue
                self.part_complete = True
                with gzip.open(part, "rt", encoding="utf-8") as fh:
                    for i, line in enumerate(fh):
                        rec = json.loads(line, parse_float=Decimal)
                        uri = f"{self.gcs}/{rel}#L{i + 1}"
                        if stream.startswith("pdp_"):
                            stats[stream] = stats.get(stream, 0) + self.pdp(stream[-2:], rec, uri)
                        else:
                            stats[stream] = stats.get(stream, 0) + self.trpc(rec, uri)
                self.c.commit()
                if not self.part_complete:
                    continue
                self.done.add(rel)
                self.ledger.write_text(json.dumps(sorted(self.done)))
        return stats | self.stats

    def complete_full_run(self) -> bool:
        """True only for an unlimited full run, stock pass on, that skipped nothing.

        Runs written before mode/limit/trpc were recorded in progress.json never qualify.
        """
        p = self.progress
        c: dict[str, int] = p.get("counts", {})
        recorded = (p.get("stopped"), p.get("mode"), p.get("limit"), p.get("trpc"))
        if recorded != ("complete", "full", 0, True):
            return False
        for k, v in c.items():
            skipped = k.startswith(_SKIP_PREFIXES) or k.endswith(_SKIP_SUFFIXES)
            if v and (skipped or (k.startswith("trpc_http_") and k != "trpc_http_200")):
                return False
        seeded = c.get("seed_pids", 0)
        return (
            seeded > 0
            and c.get("sitemap_ok", 0) > 0
            and c.get("pdp_en_ok", 0) == c.get("seed_en", -1)
            and c.get("pdp_ar_ok", 0) == c.get("seed_ar", -1)
            and c.get("trpc_http_200", 0) == seeded
            and not self.stats.get("trpc_missing_listing")
            and not self.stats.get("trpc_unparsed")
            and not self.stats.get("trpc_no_data")
        )

    def finish(self) -> None:
        """Close this folder's crawl_runs. Only a complete full run is 'succeeded'.

        A PLAN continuation run covers a subset of products by design, so it is always
        'partial': absence from it must never read as removal.
        """
        counts = self.progress.get("counts", {})
        status = "succeeded" if self.complete_full_run() else "partial"
        for lang in ("en", "ar"):
            rid = self._runs.get(lang) or self._existing_run(lang)
            if rid is None:  # nothing loaded in this lang
                continue
            ok = counts.get(f"pdp_{lang}_ok", 0)
            self.c.execute(
                "UPDATE crawl_run SET finished_at=%s, status=%s, discovered=%s, fetched=%s,"
                " parsed=%s, blocked_count=%s"
                " WHERE id=%s",
                (
                    self.progress.get("updated"),
                    status,
                    counts.get(f"seed_{lang}", counts.get("plan_pids", 0)),
                    ok,
                    ok,
                    sum(v for k, v in counts.items() if k.startswith("block_")),
                    rid,
                ),
            )
        self.c.commit()


def market_from_args(args: list[str]) -> Market:
    """The --country value (default AE); an unknown or missing value is refused, never guessed."""
    if "--country" not in args:
        return MARKETS["AE"]
    i = args.index("--country")
    code = args[i + 1].upper() if i + 1 < len(args) else ""
    if code not in MARKETS:
        raise SystemExit(f"--country must be one of {', '.join(sorted(MARKETS))}")
    return MARKETS[code]


def main() -> int:
    root, gcs = Path(sys.argv[1]), sys.argv[2]
    market = market_from_args(sys.argv[3:])
    url = os.environ["PI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        ld = Loader(conn, root, gcs, market)
        conn.commit()
        print(json.dumps(ld.load()))
        if "--finish" in sys.argv:
            ld.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
