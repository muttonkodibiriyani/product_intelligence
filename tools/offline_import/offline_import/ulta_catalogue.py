"""Append audited identities to archived Ulta content, then export its full SKU catalogue.

No retailer requests and no price/stock writes. The new content observation describes metadata
normalisation now; its catalogue record retains the original source capture timestamp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
from psycopg.types.json import Jsonb

from offline_import.ulta_feed import digest, encoded
from pi_api.catalogue import LoadedCatalogue, summary
from pi_dataset.catalogue import CatalogueDataset, CatalogueImage, CatalogueRecord, SkuReference

LATEST = """
SELECT sl.id, sl.source_listing_key, lc.observed_at, lc.labels, lc.recorded_at
FROM source_listing sl JOIN source s ON s.id=sl.source_id
JOIN LATERAL (
  SELECT observed_at, recorded_at, labels FROM listing_content c
  WHERE c.listing_id=sl.id ORDER BY observed_at DESC, recorded_at DESC LIMIT 1
) lc ON true
WHERE s.name='ulta_ae' ORDER BY sl.source_listing_key
"""


def image_asset(raw: dict[str, Any]) -> CatalogueImage:
    return CatalogueImage(
        asset_id=raw["asset_id"],
        url=quote(raw["download_url"], safe=":/?=&%#[]@!$'()*+,;~-_"),
        source_url=quote(raw["source_url"], safe=":/?=&%#[]@!$'()*+,;~-_"),
        sha256=raw["sha256"],
        width=raw["width"],
        height=raw["height"],
        bytes=raw["bytes"],
        content_type=raw["content_type"],
        label=raw.get("label") or "",
        roles=tuple(raw.get("roles") or []),
    )


def record(
    audited: dict[str, Any],
    labels: dict[str, Any],
    captured: datetime,
    assets: dict[str, CatalogueImage],
) -> CatalogueRecord:
    source = labels["source_fields"]
    for akey, skey in (("parents", "parent_products"), ("children", "variants")):
        if {r["sku"] for r in audited[akey]} != {r["sku"] for r in source.get(skey) or []}:
            raise ValueError(f"audit relationship differs from stored source: {audited['sku']}")
    if bool(labels.get("aggregate_parent")) != audited["excluded_parent_summary"]:
        raise ValueError("audit parent classification differs from stored source")
    images = [i for i in source.get("images") or [] if i.get("status") == "downloaded"]
    image_ids = tuple(dict.fromkeys(i["asset_id"] for i in images))
    for i in images:
        if i["asset_id"] not in assets or assets[i["asset_id"]].sha256 != i["sha256"]:
            raise ValueError("image manifest differs from stored image evidence")
    old = labels.get("catalogue_record")
    return CatalogueRecord.model_validate(
        {
            "sku": audited["sku"],
            "name": audited["name"],
            "product_type": audited["product_type"],
            "is_variant": audited["is_variant"],
            "source_ids": audited["source_ids"],
            "parents": [
                SkuReference(sku=r["sku"], selections=tuple(r.get("selections") or []))
                for r in audited["parents"]
            ],
            "children": [
                SkuReference(sku=r["sku"], selections=tuple(r.get("selections") or []))
                for r in audited["children"]
            ],
            "grouping_master_sku": audited["grouping_master_sku"],
            "excluded_parent_summary": audited["excluded_parent_summary"],
            "captured_at": old["capturedAt"] if old else captured,
            "image_ids": image_ids,
            "option_values": {
                str(value["id"]): str(value["title"])
                for option in source.get("options") or []
                for value in option.get("values") or []
                if value.get("id") is not None and value.get("title") is not None
            },
        }
    )


def enrich(
    database_url: str,
    audit_path: Path,
    manifest_path: Path,
    source_sha256: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate the whole candidate, then atomically append changes. Exact replays add zero rows."""
    audited: dict[str, dict[str, Any]] = {}
    for line in audit_path.read_text().splitlines():
        row = json.loads(line)
        if row["sku"] in audited:
            raise ValueError("duplicate audited SKU")
        audited[row["sku"]] = row
    assets = {}
    for raw in json.loads(manifest_path.read_text()):
        if raw["status"] != "downloaded":
            continue
        asset = image_asset(raw)
        if asset.asset_id in assets:
            raise ValueError("duplicate manifest asset ID")
        assets[asset.asset_id] = asset
    now = datetime.now(UTC)
    records = {}
    pending = []
    with psycopg.connect(database_url) as conn:
        # One writer for this normalisation job; existing source observations stay immutable.
        if apply:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('ulta-catalogue-import'))")
        with conn.cursor(name="catalogue_source") as cursor:
            cursor.execute(LATEST)
            for lid, sku, captured, labels, recorded in cursor:
                if sku not in audited:
                    raise ValueError(f"stored SKU absent from audit: {sku}")
                item = record(audited[sku], labels, captured, assets)
                records[sku] = item
                payload = {
                    "catalogue_record": item.model_dump(mode="json"),
                    "catalogue_images": [assets[k].model_dump(mode="json") for k in item.image_ids],
                    "catalogue_source_sha256": source_sha256,
                    "catalogue_operation": "normalization_of_archived_source",
                }
                if all(labels.get(k) == v for k, v in payload.items()):
                    continue
                payload["catalogue_imported_at"] = now.isoformat()
                pending.append((lid, captured, recorded, payload))
        if records.keys() != audited.keys():
            raise ValueError("audit and database SKU sets differ")
        candidate = CatalogueDataset(
            retailer="ulta_ae",
            market="AE",
            scope="beauty",
            generated_at=now,
            imported_at=now,
            source_sha256=source_sha256,
            records=records,
            assets=assets,
        )
        if apply:
            for lid, previous_at, previous_recorded, payload in pending:
                content_hash = hashlib.sha256(encoded(payload).encode()).hexdigest()
                conn.execute(
                    "INSERT INTO listing_content "
                    "(listing_id,observed_at,description,description_ar,ingredients,how_to_use,"
                    "benefits,claims,badges,labels,content_hash) "
                    "SELECT listing_id,%s,description,description_ar,ingredients,how_to_use,"
                    "benefits,claims,badges,labels || %s,%s FROM listing_content "
                    "WHERE listing_id=%s AND observed_at=%s AND recorded_at=%s "
                    "ON CONFLICT DO NOTHING",
                    (now, Jsonb(payload), content_hash, lid, previous_at, previous_recorded),
                )
    return {
        "mode": "append" if apply else "dry_run",
        "content_rows_to_append": len(pending),
        "price_stock_writes": 0,
        "audit_sha256": digest(audit_path),
        "manifest_sha256": digest(manifest_path),
        "catalogue": summary(LoadedCatalogue(candidate, "candidate")).model_dump(mode="json"),
    }


def export(database_url: str, destination: Path) -> dict[str, Any]:
    """Publishable data comes entirely from the database's latest archived metadata."""
    records: dict[str, CatalogueRecord] = {}
    assets: dict[str, CatalogueImage] = {}
    source_hashes: set[str] = set()
    imports: list[datetime] = []
    with psycopg.connect(database_url) as conn, conn.cursor(name="catalogue_export") as cursor:
        cursor.execute(LATEST)
        for _, sku, _, labels, _ in cursor:
            if "catalogue_record" not in labels:
                raise ValueError(f"SKU has no audited catalogue metadata: {sku}")
            records[sku] = CatalogueRecord.model_validate(labels["catalogue_record"])
            source_hashes.add(labels["catalogue_source_sha256"])
            imports.append(datetime.fromisoformat(labels["catalogue_imported_at"]))
            for raw in labels["catalogue_images"]:
                image = CatalogueImage.model_validate(raw)
                if image.asset_id in assets and assets[image.asset_id] != image:
                    raise ValueError("conflicting image asset metadata")
                assets[image.asset_id] = image
    if len(source_hashes) != 1:
        raise ValueError("expected one archived source hash")
    catalogue = CatalogueDataset(
        retailer="ulta_ae",
        market="AE",
        scope="beauty",
        generated_at=datetime.now(UTC),
        imported_at=max(imports),
        source_sha256=source_hashes.pop(),
        records=records,
        assets=assets,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(catalogue.model_dump_json() + "\n")
    return {
        "sha256": digest(destination),
        "path": str(destination),
        "catalogue": summary(LoadedCatalogue(catalogue, "export")).model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    add = subs.add_parser(
        "enrich",
        description=(
            "Dry run by default. --apply appends content to existing ulta_ae listings. "
            "Use an isolated database; do not apply to protected production rows."
        ),
    )
    add.add_argument("--audit", type=Path, required=True)
    add.add_argument("--manifest", type=Path, required=True)
    add.add_argument("--source-sha256", required=True)
    add.add_argument("--apply", action="store_true")
    out = subs.add_parser("export")
    out.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ["PI_DATABASE_URL"]
    result = (
        enrich(url, args.audit, args.manifest, args.source_sha256, apply=args.apply)
        if args.command == "enrich"
        else export(url, args.output)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI smoke tested separately
    main()
