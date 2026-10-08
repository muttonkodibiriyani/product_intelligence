"""Import a previously captured Ulta UAE JSONL feed; never contact the retailer.

The adapter preserves capture times, parent/variant relationships and downloaded-image
provenance. It uses the established offline loader's source/context and replay contracts.
Run with PYTHONPATH=tools/offline_import python -m offline_import.ulta_feed --help.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from scripts.demo_export.export import DEFAULT_SOURCES, UltaContext, load_rows
from scripts.demo_export.v2 import build_dataset_v2

from offline_import.load import Loader, _sha
from offline_import.mapping import ImportMapping
from offline_import.validate import ImportRow, validate_file
from pi_api.source import parse
from pi_dataset import dump_dataset, load_dataset

ULTA_BLOCKED_SINCE = "2026-09-30T20:55:00Z"


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("capture timestamp must include a time zone")
    return result.astimezone(UTC)


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def price_text(value: Any) -> str | None:
    if value is None:
        return None
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"invalid published price: {value}")
    if amount != amount.quantize(Decimal("0.0001")):
        raise ValueError(f"price finer than database precision: {value}")
    return format(amount, "f")


def prepare(  # noqa: PLR0912, PLR0915 - source transformation
    source: Path, destination: Path, capture_index: Path | None = None
) -> dict[str, Any]:
    """Stream the bulky source once, retaining product fields but excluding raw API copies."""
    products: dict[str, dict[str, Any]] = {}
    captures = json.loads(capture_index.read_text()) if capture_index else {}
    keep = (
        "sku",
        "name",
        "brand",
        "brand_names",
        "product_type",
        "is_variant",
        "is_search_listing",
        "parent_products",
        "variants",
        "url",
        "barcode",
        "description",
        "ingredients",
        "how_to_use",
        "size",
        "size_unit",
        "shade",
        "price",
        "stock",
        "promotions",
        "free_gift_promotions",
        "labels",
        "promotion_labels",
        "promotion_ids",
        "categories",
        "delivery_methods",
        "options",
        "images",
        "video",
        "rating",
        "attributes",
        "provenance",
        "data_completeness",
    )
    with source.open() as stream:
        for line in stream:
            item = json.loads(line, parse_float=Decimal)
            sku = str(item["sku"])
            if sku in products:
                raise ValueError(f"duplicate SKU: {sku}")
            products[sku] = {key: item.get(key) for key in keep}
    rows = []
    issues: list[dict[str, str]] = []
    for sku, item in products.items():
        parent_keys = [str(p["sku"]) for p in item["parent_products"] or []]
        parent = next((products[k] for k in parent_keys if k in products), item)
        children = [str(p["sku"]) for p in item["variants"] or [] if str(p["sku"]) in products]
        price = item["price"] or {}
        stock = item["stock"] or {}
        provenance = item["provenance"] or {}
        supplement = captures.get(sku, {})
        captured = (
            provenance.get("retrieved_at")
            or stock.get("checked_at")
            or supplement.get("retrieved_at")
        )
        if not captured:
            raise ValueError(f"no source capture time for {sku}")
        if not (provenance.get("retrieved_at") or stock.get("checked_at")):
            issues.append({"sku": sku, "issue": "capture time supplied by explicit evidence index"})
            item["supplemental_capture_provenance"] = supplement
        price_at = instant(captured).isoformat()
        stock_at = instant(stock.get("checked_at") or captured).isoformat()
        # Prefer the actual source-reported state over quantity (configurable parents can
        # report qty=0 while at least one child is buyable).
        in_stock = stock.get("in_stock")
        availability = (
            "in_stock" if in_stock is True else "out_of_stock" if in_stock is False else "unknown"
        )
        if in_stock is True and (stock.get("stock_data") or {}).get("few_in_stock") is True:
            availability = "low_stock"
        qty = stock.get("reported_quantity")
        if qty is not None and (Decimal(str(qty)) < 0 or Decimal(str(qty)) != int(qty)):
            issues.append(
                {
                    "sku": sku,
                    "issue": (
                        "invalid quantity retained in source metadata; normalized quantity null"
                    ),
                }
            )
            qty = None
        image = next((i for i in item["images"] or [] if i.get("status") == "downloaded"), None)
        url = item["url"] or parent.get("url")
        product_url_missing = not bool(url)
        if not url:
            # The required listing URL points at the actual catalogue source endpoint;
            # explicitly mark that it is not a product page. The dataset publishes null.
            url = "https://www.ulta.ae/graphql"
            issues.append(
                {
                    "sku": sku,
                    "issue": "no product URL; source endpoint stored, product link remains null",
                }
            )
        normalized_prices = {}
        price_errors = {}
        for field in ("current", "regular"):
            try:
                normalized_prices[field] = price_text(price.get(field))
            except ValueError as error:
                normalized_prices[field] = None
                price_errors[field] = str(error)
                issues.append({"sku": sku, "issue": f"{field}: {error}; source value retained"})
        current = normalized_prices["current"]
        regular = normalized_prices["regular"]
        if any(
            v is not None and Decimal(v) != Decimal(v).quantize(Decimal("0.01"))
            for v in [current, regular]
        ):
            issues.append(
                {
                    "sku": sku,
                    "issue": (
                        "fractional AED below minor unit; exact source price stored, dataset "
                        "price withheld"
                    ),
                }
            )
        promo = current if current and regular and Decimal(current) < Decimal(regular) else None
        size = item.get("size")
        unit = item.get("size_unit")
        size_label = f"{size} {unit}" if size and unit else str(size) if size else None
        categories = item["categories"] or parent.get("categories") or []
        category_names = []
        for category in categories:
            text = (
                category.get("name") or category.get("label") or category.get("path")
                if isinstance(category, dict)
                else category
            )
            if isinstance(text, str) and text:
                category_names.append(text)
        row = {
            "listing_key": sku,
            "sku": sku,
            "gtin": item["barcode"],
            "url": url,
            "name": item["name"] or parent.get("name") or f"SKU {sku}",
            "brand": item["brand"] or parent.get("brand"),
            "category_path": " > ".join(category_names) or None,
            "size": size_label,
            "shade": item["shade"],
            "price_current": current,
            "price_regular": regular,
            "price_promo": promo,
            "price_errors": price_errors,
            "availability": availability,
            "stock_qty": qty,
            "image_url": image.get("download_url") if image else None,
            "observed_at": price_at,
            "stock_observed_at": stock_at,
            "master_id": str(parent["sku"]),
            "product_name": parent.get("name") or item["name"],
            "aggregate_parent": bool(children and item["product_type"] == "configurable"),
            "product_url_missing": product_url_missing,
            "resolved_children": children,
            "source_record": item,
        }
        rows.append(row)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "ulta-import.json"
    path.write_text(encoded(rows) + "\n")
    columns = [
        "listing_key",
        "sku",
        "gtin",
        "url",
        "name",
        "brand",
        "category_path",
        "size",
        "shade",
        "price_current",
        "price_regular",
        "price_promo",
        "availability",
        "stock_qty",
        "image_url",
        "observed_at",
    ]
    mapping = {
        "source": {
            "name": "ulta_ae",
            "kind": "web",
            "base_url": "https://www.ulta.ae",
            "notes": (
                "User-supplied existing Ulta UAE website scrape, Sep30-Oct1 2026. "
                "Imported offline; not an Alshaya systems export. Original extractor "
                "used Scrapling and public storefront catalogue/search/stock sources."
            ),
        },
        "country": "AE",
        "locale": "en-AE",
        "currency": "AED",
        "time_zone": "Asia/Dubai",
        "complete_catalogue": False,
        # The scrape states a regular price on promotional rows (Sephora's shape).
        "regular_stated": "on_promotion",
        "format": "json",
        "columns": {k: k for k in columns},
        "availability_map": {k: k for k in ["in_stock", "out_of_stock", "low_stock", "unknown"]},
    }
    (destination / "mapping.json").write_text(encoded(mapping) + "\n")
    summary = {
        "source_sha256": digest(source),
        "prepared_sha256": digest(path),
        "records": len(rows),
        "aggregate_parents": sum(r["aggregate_parent"] for r in rows),
        "rows_with_price": sum(r["price_current"] is not None for r in rows),
        "rows_with_image": sum(r["image_url"] is not None for r in rows),
        "capture_start": min(r["observed_at"] for r in rows),
        "capture_end": max(max(r["observed_at"], r["stock_observed_at"]) for r in rows),
        "issues": issues,
    }
    (destination / "prepare-report.json").write_text(encoded(summary) + "\n")
    return summary


class UltaLoader(Loader):
    """Retain the richer source data and separate price/stock evidence, without a migration."""

    def __init__(
        self,
        conn: Any,
        mapping: ImportMapping,
        report: Any,
        uri: str,
        records: list[dict[str, Any]],
    ) -> None:
        self.records = {r["listing_key"]: r for r in records}
        self.times = [instant(r[k]) for r in records for k in ("observed_at", "stock_observed_at")]
        self.evidence_ids: dict[datetime, int] = {}
        self.brands: dict[str, int] = {}
        self.inserted = 0
        super().__init__(conn, mapping, report, uri)

    def _run_and_evidence(self, now: datetime) -> tuple[int, int]:
        # Base file evidence represents the end of the recorded collection interval.
        # Per-observation evidence below carries its original source time.
        run, evidence = super()._run_and_evidence(max(self.times))
        self.c.execute(
            "UPDATE crawl_run SET started_at=%s, connector_version=%s WHERE id=%s",
            (min(self.times), "ulta_feed_import/1", run),
        )
        return run, evidence

    def _captured_evidence(self, run: int, captured: datetime) -> int:
        if captured not in self.evidence_ids:
            sha = _sha(self.report.sha256, captured.isoformat())
            existing = self._one(
                "SELECT id FROM evidence WHERE crawl_run_id=%s AND content_hash=%s "
                "ORDER BY id LIMIT 1",
                (run, sha),
            )
            self.evidence_ids[captured] = existing or self._id(
                "INSERT INTO evidence "
                "(crawl_run_id,url,content_hash,storage_uri,retrieved_at,ladder_rung_used,"
                "fetch_method,retention_until) "
                "VALUES (%s,%s,%s,%s,%s,0,'offline_import',%s) RETURNING id",
                (run, self.uri, sha, self.uri, captured, datetime.now(UTC) + timedelta(days=90)),
            )
        return self.evidence_ids[captured]

    def _content(self, lid: int, row: ImportRow) -> None:
        record = self.records[row.listing_key]
        source = record["source_record"]
        labels = {k: v for k, v in record.items() if k not in {"source_record", "observed_at"}}
        labels.update(
            {
                "brand": row.text.get("brand"),
                "gtin": row.text.get("gtin"),
                "import_sha256": self.report.sha256,
                "evidence_uri": self.uri,
                "import_provenance": (
                    "offline import of existing public website scrape; not "
                    "retailer-supplied systems export"
                ),
                "source_fields": source,
                "images": source.get("images") or [],
                "promotions": source.get("promotions") or [],
                "free_gift_promotions": source.get("free_gift_promotions") or [],
            }
        )
        names = source.get("brand_names") or ([row.text["brand"]] if row.text.get("brand") else [])
        brand_ids = []
        for name in names:
            if name not in self.brands:
                self.brands[name] = self._one(
                    "SELECT id FROM brand WHERE name=%s", (name,)
                ) or self._id(
                    "INSERT INTO brand (name,aliases) VALUES (%s,%s) ON CONFLICT (name) DO "
                    "UPDATE SET name=EXCLUDED.name RETURNING id",
                    (name, [f"ulta_ae:{name}"]),
                )
            brand_ids.append(self.brands[name])
        labels["brand_ids"] = brand_ids
        values = [source.get(k) for k in ["description", "ingredients", "how_to_use"]]
        values = [v if isinstance(v, str) or v is None else encoded(v) for v in values]
        content_hash = _sha(encoded(labels), *[v or "" for v in values])
        self.c.execute(
            "INSERT INTO listing_content "
            "(listing_id,observed_at,description,ingredients,how_to_use,labels,content_hash) "
            "SELECT %s,%s,%s,%s,%s,%s,%s "
            # one content per page time, the first written, on replay too
            "WHERE NOT EXISTS (SELECT 1 FROM listing_content "
            "WHERE listing_id=%s AND observed_at=%s) "
            "ON CONFLICT DO NOTHING",
            (lid, row.observed_at, *values, Jsonb(labels), content_hash, lid, row.observed_at),
        )

    def _offer(self, lid: int, row: ImportRow, run: int, evidence: int) -> bool:
        record = self.records[row.listing_key]
        source = record["source_record"]
        price = row.price_current
        range_data = (source.get("price") or {}).get("range") or {}
        minimum = maximum = None
        if record["aggregate_parent"] and range_data:
            minimum = (
                ((range_data.get("minimum") or {}).get("final") or {})
                .get("amount", {})
                .get("value")
            )
            maximum = (
                ((range_data.get("maximum") or {}).get("final") or {})
                .get("amount", {})
                .get("value")
            )
        ranged = (
            minimum is not None
            and maximum is not None
            and 0 < Decimal(str(minimum)) < Decimal(str(maximum))
        )
        kind = (
            "range"
            if ranged
            else "promotional"
            if row.price_promo is not None
            else "full"
            if price is not None
            else None
        )
        if ranged:
            price = None
        stats = ((source.get("rating") or {}).get("statistics") or {}).get("ReviewStatistics") or {}
        rating = stats.get("AverageOverallRating")
        scale = stats.get("OverallRatingRange")
        rating_count = stats.get("TotalReviewCount")
        if rating is None or scale is None or rating_count is None:
            rating = scale = rating_count = None
        previous = self.inserted
        for field, at in [
            ("price", row.observed_at),
            ("stock", instant(record["stock_observed_at"])),
        ]:
            is_price = field == "price"
            reason = (
                "not_applicable"
                if ranged
                else "not_published"
                if (source.get("price") or {}).get("source")
                else "unknown"
            )
            fs = (
                {"availability_state": "not_published"}
                if is_price
                else {
                    "price_current": "unknown",
                    "availability_state": "observed" if row.availability_observed else "unknown",
                }
            )
            if is_price and price is None:
                fs["price_current"] = (
                    "parse_failure" if record.get("price_errors", {}).get("current") else reason
                )
            self._partition(at)
            eid = self._captured_evidence(run, at)
            low = not is_price and row.availability.value == "low_stock"
            current = self.c.execute(
                "INSERT INTO offer_observation "
                "(idempotency_key,crawl_run_id,source_context_id,source_listing_id,observed_at,"
                "ingested_at,price_current,price_regular_stated,price_promo,price_type,"
                "price_range_min,price_range_max,currency,availability_state,low_stock_flag,"
                "field_state,evidence_id,rating_value,rating_scale,rating_count) "
                "VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (
                    _sha(self.m.source.name, self.report.sha256, row.listing_key, field),
                    run,
                    self.context_id,
                    lid,
                    at,
                    price if is_price else None,
                    row.price_regular if is_price else None,
                    row.price_promo if is_price and not ranged else None,
                    kind if is_price else None,
                    Decimal(str(minimum)) if is_price and ranged else None,
                    Decimal(str(maximum)) if is_price and ranged else None,
                    "AED"
                    if is_price and any(v is not None for v in [price, row.price_regular, minimum])
                    else None,
                    "not_observed" if is_price else row.availability.value,
                    True if low else None,
                    Jsonb(fs),
                    eid,
                    rating if is_price else None,
                    scale if is_price else None,
                    rating_count if is_price else None,
                ),
            )
            self.inserted += current.rowcount
        return self.inserted > previous

    def _finish(self, run: int, started: datetime) -> None:
        count = len(self.report.accepted)
        self.c.execute(
            "UPDATE crawl_run SET "
            "finished_at=%s,status='partial',discovered=%s,fetched=%s,parsed=%s,accepted=%s,"
            "quarantined=%s WHERE id=%s",
            (
                max(self.times),
                self.report.rows,
                self.report.rows,
                self.report.rows,
                count,
                len(self.report.rejected),
                run,
            ),
        )


def load(folder: Path, database_url: str) -> dict[str, Any]:
    mapping = ImportMapping.model_validate_json((folder / "mapping.json").read_text())
    path = folder / "ulta-import.json"
    report = validate_file(path, mapping)
    (folder / "validation-report.json").write_text(encoded(report.to_json()) + "\n")
    if report.rejected:
        raise ValueError(
            f"refusing partial load: {len(report.rejected)} rejected rows; "
            "inspect validation-report.json"
        )
    records = json.loads(path.read_text())
    with psycopg.connect(database_url) as conn:
        loader = UltaLoader(conn, mapping, report, path.resolve().as_uri(), records)
        result = loader.load()
        result["observations_inserted"] = loader.inserted
        result["capture_start"] = min(loader.times).isoformat()
        result["capture_end"] = max(loader.times).isoformat()
    return result


def export(
    database_url: str,
    destination: Path,
    *,
    sources: Sequence[str] = DEFAULT_SOURCES,
    ulta: UltaContext | None = None,
) -> dict[str, Any]:
    """Export explicitly selected sources with the shared source, parent and image policies."""
    context = ulta or UltaContext(blocked_since=instant(ULTA_BLOCKED_SINCE))
    if not sources:
        raise ValueError("--sources must name at least one source")
    if "ulta_ae" in sources and context.blocked:
        raise ValueError("--sources ulta_ae needs --ulta-unblocked: Ulta is blocked by ruling")
    rows, matches = load_rows(database_url, sources)
    with psycopg.connect(database_url) as conn:
        content = conn.execute(
            "SELECT s.name, sl.source_listing_key, jsonb_build_object("
            "'product_url_missing',lc.labels->'product_url_missing') FROM source_listing "
            "sl JOIN source s ON s.id=sl.source_id LEFT JOIN LATERAL (SELECT "
            "labels FROM listing_content c WHERE c.listing_id=sl.id ORDER BY "
            "observed_at DESC, recorded_at DESC LIMIT 1) lc ON true WHERE s.name = ANY(%s)",
            (list(sources),),
        ).fetchall()
    labels = {(s, key): data or {} for s, key, data in content}
    # load_rows excludes a parent only when an exported child is present; childless parents stay.
    rows = [replace(r, brand=r.brand or "Unknown brand") for r in rows]
    unpublishable_money = []
    clean_rows = []
    for row in rows:
        bad = any(
            v is not None and v != v.quantize(Decimal("0.01")) for v in [row.price, row.regular]
        )
        if bad:
            unpublishable_money.append(row.source_listing_key)
        clean_rows.append(replace(row, price=None, regular=None) if bad else row)
    rows = clean_rows
    dataset = build_dataset_v2(
        rows,
        matches,
        generated_at=datetime.now(UTC),
        ulta=context,
        ulta_note={
            "en": (
                "User-provided Ulta UAE website snapshot, 30 September-1 October 2026; "
                "imported offline. Coverage is partial; missing records are not "
                "removals."
            ),
            "ar": (
                "لقطة من موقع أولتا الإمارات بتاريخ 30 سبتمبر-1 أكتوبر 2026، مستوردة "
                "دون اتصال. التغطية جزئية وغياب السجلات لا يعني إزالة المنتجات."
            ),
        },
    )
    document = json.loads(dump_dataset(dataset))
    with_images = 0
    for product in document["products"]:
        for source, offer in product["offers"].items():
            label = labels.get((source, offer["sku"]), {})
            # build_dataset_v2 owns per-retailer image allowlisting and image coverage metadata.
            with_images += offer["image"] is not None
            if label.get("product_url_missing"):
                offer["url"] = None
    if unpublishable_money:
        document["meta"]["fields"]["price"] = "partial"
        document["meta"]["fields"]["regular"] = "partial"
    body = encoded(document).encode()
    checked = load_dataset(body)
    served = parse(body)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    counts = {r.id: sum(r.id in p.offers for p in checked.products) for r in checked.meta.retailers}
    return {
        "dataset": str(destination),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "cutoff": checked.meta.cutoff.isoformat(),
        "products": len(checked.products),
        "offers_by_retailer": counts,
        "offers_with_images": with_images,
        "api_parse": "passed",
        "api_products": len(served.products),
        "unpublishable_fractional_aed_skus": unpublishable_money,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("source", type=Path)
    prep.add_argument("destination", type=Path)
    prep.add_argument("--capture-index", type=Path, help="Explicit per-SKU capture provenance JSON")
    for name in ("load", "export"):
        cmd = sub.add_parser(
            name,
            description=(
                "Writes to source ulta_ae and updates existing listing metadata. "
                "Use an isolated database; do not run against protected production rows."
                if name == "load"
                else "Writes a local dataset file; does not publish or deploy it."
            ),
        )
        cmd.add_argument("path", type=Path)
        if name == "export":
            cmd.add_argument(
                "--sources",
                type=lambda value: tuple(name.strip() for name in value.split(",") if name.strip()),
                default=DEFAULT_SOURCES,
                help="comma-separated source names to export (default: sephora_me only)",
            )
            cmd.add_argument("--ulta-blocked-since", default=ULTA_BLOCKED_SINCE)
            cmd.add_argument(
                "--ulta-unblocked",
                action="store_true",
                help="Ulta collection resumed; derive its status from rows (default: blocked)",
            )
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.source, args.destination, args.capture_index)
    elif args.command == "load":
        result = load(args.path, os.environ["PI_DATABASE_URL"])
    else:
        try:
            result = export(
                os.environ["PI_DATABASE_URL"],
                args.path,
                sources=args.sources,
                ulta=UltaContext(
                    blocked_since=instant(args.ulta_blocked_since), blocked=not args.ulta_unblocked
                ),
            )
        except ValueError as error:
            parser.error(str(error))
    print(encoded(result))


if __name__ == "__main__":
    main()
