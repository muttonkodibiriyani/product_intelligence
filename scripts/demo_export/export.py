#!/usr/bin/env python3
"""Export a local pi_db snapshot as the frontend's ``pi.dataset/v1`` JSON.

This is deliberately a read-only producer. It never fetches retailer data and it only adds
Ulta early examples when an explicitly supplied, committed/redacted probe fixture is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
    family_id: int
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

    @property
    def retailer(self) -> str:
        if self.source_name.startswith("sephora"):
            return "s"
        if self.source_name.startswith("ulta"):
            return "u"
        raise ValueError(f"unsupported source {self.source_name!r}")


@dataclass(frozen=True)
class GroupKey:
    retailer: str
    family_id: int
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
    score: Decimal | None
    algo_version: str


LATEST_LISTINGS_SQL = """
WITH latest AS (
  SELECT DISTINCT ON (o.source_listing_id)
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
    o.crawl_run_id,
    e.retrieved_at AS evidence_retrieved_at
  FROM offer_observation o
  JOIN source_context sc ON sc.id = o.source_context_id
  LEFT JOIN evidence e ON e.id = o.evidence_id
  WHERE o.currency = 'AED' AND sc.country = 'AE'
  ORDER BY o.source_listing_id, o.observed_at DESC, o.observation_id DESC
)
SELECT
  s.name AS source_name,
  pf.id AS family_id,
  v.id AS variant_id,
  sl.source_listing_key,
  sl.source_sku,
  sl.url,
  pf.name_normalized AS name,
  b.name AS brand,
  t.code AS category,
  sl.category_path_source AS category_path,
  v.shade,
  v.shade_family,
  v.shade_hex,
  v.size_value,
  v.size_unit,
  latest.price_current AS price,
  latest.price_regular_stated AS regular,
  latest.price_type,
  latest.availability_state AS availability,
  latest.rating_value AS rating,
  latest.rating_scale,
  latest.rating_count,
  latest.observed_at,
  latest.evidence_retrieved_at,
  latest.crawl_run_id AS run_id
FROM latest
JOIN source_listing sl ON sl.id = latest.source_listing_id
JOIN source s ON s.id = sl.source_id
JOIN variant v ON v.id = COALESCE(latest.variant_id, sl.variant_id)
JOIN product_family pf ON pf.id = v.family_id
JOIN brand b ON b.id = pf.brand_id
LEFT JOIN taxonomy t ON t.id = pf.category_universal_id
WHERE s.name LIKE 'sephora%' OR s.name LIKE 'ulta%'
ORDER BY s.name, pf.id, v.size_value NULLS FIRST, v.id
"""

MATCHES_SQL = """
SELECT variant_a, variant_b, score, algo_version
FROM match_edge
WHERE valid_to IS NULL
  AND review_state <> 'rejected'
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


def psycopg_database_url(value: str) -> str:
    """Accept the workspace's SQLAlchemy-style psycopg URL as well as a native DSN."""
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def category_for(row: ListingRow) -> str:
    text = " ".join(filter(None, (row.category, row.category_path))).lower()
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
    if row.category and row.category.lower() in ALLOWED_CATEGORIES:
        return row.category.lower()
    return next((result for needle, result in rules if needle in text), "other")


def group_rows(rows: Iterable[ListingRow]) -> dict[GroupKey, list[ListingRow]]:
    groups: dict[GroupKey, list[ListingRow]] = defaultdict(list)
    for row in rows:
        unit = normalise_unit(row.size_unit)
        size = row.size_value if unit is not None else None
        groups[GroupKey(row.retailer, row.family_id, unit, size)].append(row)
    return dict(groups)


def choose_representative(rows: Sequence[ListingRow]) -> ListingRow:
    priced = [row for row in rows if row.price is not None]
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
    captured = representative.evidence_retrieved_at or representative.observed_at
    shade_values = {row.shade for row in rows if row.shade}
    offer: dict[str, Any] = {
        "sku": representative.source_sku or representative.source_listing_key,
        "url": representative.url,
        "size": json_number(representative.size_value),
        "shadeCount": len(shade_values),
        "rating": None,
        "series": {"price": [json_number(representative.price)]},
        "evidence": {
            "capturedAt": utc_text(captured),
            "source": f"{representative.source_name} · local pi_db snapshot",
            "runId": str(representative.run_id),
        },
    }
    if representative.price is not None:
        offer["evidence"]["rawPrice"] = f"AED {representative.price:.2f}"
    if representative.price is not None and representative.regular is not None:
        offer["series"]["regular"] = [json_number(representative.regular)]
        offer["series"]["promo"] = [promo_pct(representative.price, representative.regular)]
    if representative.rating is not None and representative.rating_scale is not None:
        rating = representative.rating * Decimal(5) / representative.rating_scale
        offer["rating"] = [
            json_number(rating.quantize(Decimal("0.01"))),
            representative.rating_count or 0,
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
    product["offers"][key.retailer] = offer_for(rows, early=key.retailer == "u")
    if shades:
        product["shades"] = shades
    if shade_families:
        product["shadeFamilies"] = shade_families
    return product


def matched_products(
    groups: Mapping[GroupKey, Sequence[ListingRow]], matches: Sequence[MatchRow]
) -> list[dict[str, Any]]:
    by_variant = {row.variant_id: key for key, rows in groups.items() for row in rows}
    candidates: dict[tuple[GroupKey, GroupKey], MatchRow] = {}
    for match in matches:
        left = by_variant.get(match.variant_a)
        right = by_variant.get(match.variant_b)
        if left is None or right is None or left.retailer == right.retailer:
            continue
        pair = (left, right) if left.retailer == "u" else (right, left)
        current = candidates.get(pair)
        if current is None or (match.score or Decimal(-1)) > (current.score or Decimal(-1)):
            candidates[pair] = match

    used: set[GroupKey] = set()
    products: list[dict[str, Any]] = []
    ordered = sorted(
        candidates.items(),
        key=lambda item: (
            -(item[1].score or Decimal(-1)),
            item[0][0].stable_token,
            item[0][1].stable_token,
        ),
    )
    for (ulta_key, sephora_key), match in ordered:
        if ulta_key in used or sephora_key in used:
            continue
        ulta_rows = groups[ulta_key]
        sephora_rows = groups[sephora_key]
        base = product_for_group(sephora_key, sephora_rows)
        base["id"] = f"m-{ulta_key.stable_token}-{sephora_key.stable_token}"
        base["offers"]["u"] = offer_for(ulta_rows, early=True)
        base["match"] = {
            "method": match.algo_version,
            "confidence": json_number(match.score),
            "stage": "first-pass",
        }
        products.append(base)
        used.update((ulta_key, sephora_key))

    products.extend(
        product_for_group(key, groups[key])
        for key in sorted(groups, key=lambda item: item.stable_token)
        if key not in used
    )
    return sorted(products, key=lambda product: product["id"])


def load_rows(database_url: str) -> tuple[list[ListingRow], list[MatchRow]]:
    with psycopg.connect(psycopg_database_url(database_url), row_factory=dict_row) as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute(LATEST_LISTINGS_SQL)
            listing_dicts = cursor.fetchall()
            cursor.execute(MATCHES_SQL)
            match_dicts = cursor.fetchall()
    return (
        [ListingRow(**row) for row in listing_dicts],
        [MatchRow(**row) for row in match_dicts],
    )


def parse_ulta_early_fixture(path: Path, captured_at: datetime) -> dict[str, Any]:
    """Parse the redacted PDP JSON-LD fixture without accepting network input."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"no Product JSON-LD found in {path}")
    payload = json.loads(match.group(1))
    if payload.get("@type") != "Product":
        raise ValueError(f"first JSON-LD block in {path} is not a Product")
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
        "category": "cheek",
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
                "series": {"price": [json_number(price)]},
                "evidence": {
                    "capturedAt": utc_text(captured_at),
                    "source": "ulta_ae · committed redacted probe fixture",
                    "runId": "gulf-probe-early",
                    "rawPrice": f"AED {price:.2f}",
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


def build_dataset(
    rows: Sequence[ListingRow],
    matches: Sequence[MatchRow],
    *,
    generated_at: datetime,
    ulta_early: Sequence[dict[str, Any]] = (),
    ulta_blocked_since: datetime,
) -> dict[str, Any]:
    if not rows and not ulta_early:
        raise ValueError("refusing to create an empty demo dataset")
    groups = group_rows(rows)
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
                {
                    "id": "u",
                    "key": "ulta_ae",
                    "name": "Ulta UAE",
                    "status": "blocked",
                    "since": utc_text(ulta_blocked_since),
                    "earlyExamples": bool(ulta_early),
                    "note": {
                        "en": (
                            "3 products were observed only during recon (30 Sep 20:33-20:58 UTC); "
                            "0 Ulta products are in the database. Access is blocked by a "
                            "Cloudflare challenge and the source is in cool-off."
                        ),
                        "ar": (
                            "تمت ملاحظة 3 منتجات أثناء الاستطلاع فقط (30 سبتمبر، 20:33-20:58 "
                            "UTC)؛ لا توجد منتجات من ألتا في قاعدة البيانات. الوصول محجوب "
                            "بتحدّي Cloudflare والمصدر في فترة تهدئة."
                        ),
                    },
                },
                {
                    "id": "s",
                    "key": "sephora_me",
                    "name": "Sephora UAE",
                    "status": "ok" if any(row.retailer == "s" for row in rows) else "pending",
                },
            ],
            "capabilities": {
                "history": False,
                "promotions": True,
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
        "notObserved": [
            {
                "retailer": "u",
                "start": ulta_blocked_since.date().isoformat(),
                "end": cutoff.date().isoformat(),
                "categories": None,
                "why": {
                    "en": "Cloudflare challenge; no blocked result is treated as out of stock.",
                    "ar": "تحدّي Cloudflare؛ لا تُعامل النتيجة المحجوبة على أنها نفاد مخزون.",
                },
            }
        ],
    }
    if contains_secret(dataset):
        raise ValueError("refusing to write a dataset containing secret-like Algolia material")
    return dataset


def write_json(path: Path, dataset: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(dataset, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
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
    result.add_argument("--generated-at")
    result.add_argument("--ulta-blocked-since", default="2026-09-30T20:55:00Z")
    return result


def main() -> None:
    args = parser().parse_args()
    if (args.ulta_early_fixture is None) != (args.ulta_captured_at is None):
        raise SystemExit("--ulta-early-fixture and --ulta-captured-at must be supplied together")
    rows, matches = load_rows(args.database_url)
    early: list[dict[str, Any]] = []
    if args.ulta_early_fixture is not None:
        early.append(
            parse_ulta_early_fixture(args.ulta_early_fixture, parse_utc(args.ulta_captured_at))
        )
    generated_at = parse_utc(args.generated_at) if args.generated_at else datetime.now(UTC)
    dataset = build_dataset(
        rows,
        matches,
        generated_at=generated_at,
        ulta_early=early,
        ulta_blocked_since=parse_utc(args.ulta_blocked_since),
    )
    write_json(args.output, dataset)
    print(
        f"wrote {len(dataset['products'])} products to {args.output} "
        f"sha256={sha256(args.output)} cutoff={dataset['meta']['cutoff']}"
    )


if __name__ == "__main__":
    main()
