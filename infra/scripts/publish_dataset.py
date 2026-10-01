# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "firebase-admin>=6.5", "pi-dataset", "pi-core", "pi-profiles", "pi-metrics", "pi-api",
# ]
#
# [tool.uv.sources]
# pi-dataset = { path = "../../packages/pi_dataset", editable = true }
# pi-core = { path = "../../packages/pi_core", editable = true }
# pi-profiles = { path = "../../packages/pi_profiles", editable = true }
# pi-metrics = { path = "../../packages/pi_metrics", editable = true }
# pi-api = { path = "../../packages/pi_api", editable = true }
# ///
"""Publish a pi.dataset JSON file to the demo app (Storage + a Firestore meta mirror).

Validates the contract, refuses anything that looks like an Algolia credential, then uploads
gzipped to ``<prefix>/latest.json`` plus an immutable copy named after the cutoff (for rollback),
and mirrors meta to Firestore.

- v1 (the dashboard's current input): prefix datasets/uae, meta in demo_meta/current.
- v2 (ADR-0007 §6): checked by pi_dataset's strict ``load_dataset``; prefix
  ``datasets/<country>/<scope>`` (e.g. datasets/ae/beauty), meta in demo_meta/v2_<country>_<scope>.
  v1 stays readable until the dashboard moves to v2, so both are published side by side.
  A v2 file must also load through pi-api's own serving parse (``pi_api.source.parse``, which
  upgrades it to v3). pi-api skips a dataset it can't load, so uploading one would leave the API
  with no data: such a file is held, never uploaded (decision 2026-10-01, after the v3 upgrade
  refused shared-url size variants).

    GOOGLE_APPLICATION_CREDENTIALS=<sa-key.json> uv run --script infra/scripts/publish_dataset.py \
        --project productintelligence-beeb3 dataset.json [--dry-run] [--allow-test]
"""

import argparse
import base64
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "pi.dataset/v1"
SCHEMA_V2 = "pi.dataset/v2"
PRECONDITION_FAILED = 412  # google.api_core PreconditionFailed.code (if_generation_match)
# Never ship Algolia credentials: header/param names, or a 32-hex key next to an Algolia hint.
FORBIDDEN = [
    re.compile(r"x-algolia-(api-key|application-id)", re.I),
    re.compile(r"algolia[^\"]{0,40}\"\s*:\s*\"[A-Za-z0-9]{10,}\"", re.I),
    re.compile(r"\"(api_?key|app_?id|application_?id)\"\s*:", re.I),
]


def validate(doc: dict[str, Any], raw: str, *, allow_test: bool) -> list[str]:
    errors: list[str] = []
    if doc.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")
    meta = doc.get("meta") or {}
    for key in ("kind", "cutoff", "generatedAt", "market", "currency", "dates", "retailers"):
        if key not in meta:
            errors.append(f"meta.{key} missing")
    if meta.get("test") and not allow_test:
        errors.append("meta.test is true; pass --allow-test to publish a fixture")
    n = len(meta.get("dates") or [])
    products = doc.get("products")
    if not isinstance(products, list) or not products:
        errors.append("products must be a non-empty list")
        products = []
    for product in products:
        for rid, offer in (product.get("offers") or {}).items():
            for name, series in ((offer or {}).get("series") or {}).items():
                if len(series) != n:
                    errors.append(
                        f"{product.get('id')}.{rid}.series.{name}: len {len(series)} != {n}"
                    )
    errors += [
        f"forbidden credential-like content: /{p.pattern}/" for p in FORBIDDEN if p.search(raw)
    ]
    return errors


def validate_v2(raw: str, *, allow_test: bool) -> tuple[Any, list[str]]:
    """The contract's own strict load (floats, credentials, every rule); never a partial copy."""
    from pi_dataset import DatasetError, load_dataset  # noqa: PLC0415 (v1 runs without it)

    try:
        dataset = load_dataset(raw, allow_test=allow_test)
    except DatasetError as exc:
        return None, list(exc.errors)
    errors = serve_check(raw, allow_test=allow_test)
    return (None, errors) if errors else (dataset, [])


def serve_check(raw: str, *, allow_test: bool) -> list[str]:
    """pi-api's own load of the file (v2 upgraded to v3); empty when the API can serve it."""
    from pi_api.source import parse  # noqa: PLC0415 (v1 runs without it)

    try:
        parse(raw.encode("utf-8"), allow_test=allow_test)
    except ValueError as exc:  # DatasetError and UpgradeError are ValueErrors
        problems = getattr(exc, "errors", None) or [str(exc)]
        return [f"HOLD, pi-api cannot serve this file ({len(problems)}): {p}" for p in problems]
    return []


def package_v2(dataset: Any) -> tuple[bytes, list[str], dict[str, Any], str]:
    """v2 body (canonical dump), paths under datasets/<country>/<scope>, summary, Firestore doc."""
    from pi_dataset import dump_dataset  # noqa: PLC0415

    meta = dataset.meta
    if len(meta.markets) != 1:
        raise ValueError("a multi-market dataset needs a layout decision first (ADR-0007 §6)")
    country = meta.markets[0].country.lower()
    prefix = f"datasets/{country}/{meta.scope}"
    body = gzip.compress(dump_dataset(dataset), mtime=0)
    cutoff = meta.cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = re.sub(r"[^0-9TZ]", "", cutoff)
    paths = [f"{prefix}/{stamp}.json", f"{prefix}/latest.json"]
    summary = {
        "schema": SCHEMA_V2,
        "kind": meta.kind,
        "test": meta.test,
        "cutoff": cutoff,
        "generatedAt": meta.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market": meta.markets[0].country,
        "scope": meta.scope,
        "products": len(dataset.products),
        "retailers": [
            {
                "id": r.id,
                "name": r.name,
                "status": str(r.status),
                "since": r.since.isoformat() if r.since else None,
            }
            for r in meta.retailers
        ],
        "storagePath": paths[-1],
    }
    return body, paths, summary, f"v2_{country}_{meta.scope}"


def blob_md5(body: bytes) -> str:
    """MD5 in the base64 form GCS reports as blob.md5_hash."""
    return base64.b64encode(hashlib.md5(body).digest()).decode()  # noqa: S324 (GCS checksum)


def package(doc: dict[str, Any], prefix: str) -> tuple[bytes, list[str], dict[str, Any]]:
    """Deterministic gzip body, upload paths (snapshot first) and the Firestore summary."""
    meta = doc["meta"]
    body = gzip.compress(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0
    )
    stamp = re.sub(r"[^0-9TZ]", "", str(meta["cutoff"]))
    # Snapshot first: if that cutoff was already published differently, latest.json stays untouched.
    paths = [f"{prefix}/{stamp}.json", f"{prefix}/latest.json"]
    summary = {
        "schema": SCHEMA,
        "kind": meta["kind"],
        "test": bool(meta.get("test")),
        "cutoff": meta["cutoff"],
        "generatedAt": meta["generatedAt"],
        "market": meta["market"],
        "products": len(doc["products"]),
        "retailers": [
            {k: r.get(k) for k in ("id", "key", "name", "status", "since")}
            for r in meta["retailers"]
        ],
        "storagePath": paths[-1],
    }
    return body, paths, summary


def upload(bucket: Any, paths: list[str], body: bytes) -> int:
    """Upload to every path in order; a cutoff snapshot is create-only. Returns an exit code."""
    for path in paths:
        blob = bucket.blob(path)
        blob.content_encoding = "gzip"
        blob.cache_control = "private, no-cache"
        if path.endswith("/latest.json"):
            blob.upload_from_string(body, content_type="application/json; charset=utf-8")
        else:
            # A cutoff snapshot is immutable: create-only, identical re-publish is a no-op.
            try:
                blob.upload_from_string(
                    body, content_type="application/json; charset=utf-8", if_generation_match=0
                )
            except Exception as exc:
                if getattr(exc, "code", None) != PRECONDITION_FAILED:
                    raise
                existing = bucket.get_blob(path)
                if existing is None or existing.md5_hash != blob_md5(body):
                    print(
                        f"refusing: {path} already exists with different content", file=sys.stderr
                    )
                    return 1
                print(f"unchanged gs://{bucket.name}/{path}")
                continue
        print(f"uploaded gs://{bucket.name}/{path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--bucket", default=None, help="default: <project>.firebasestorage.app")
    parser.add_argument(
        "--prefix", default="datasets/uae", help="v1 Storage folder (v2 derives its own)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-test", action="store_true")
    args = parser.parse_args()

    raw = args.path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    is_v2 = isinstance(doc, dict) and doc.get("schema") == SCHEMA_V2
    if is_v2:
        dataset, errors = validate_v2(raw, allow_test=args.allow_test)
    else:
        errors = validate(doc, raw, allow_test=args.allow_test)
    if errors:
        for err in errors[:50]:
            print(f"INVALID: {err}", file=sys.stderr)
        return 1
    if is_v2:
        body, paths, summary, meta_doc = package_v2(dataset)
    else:
        body, paths, summary = package(doc, args.prefix)
        meta_doc = "current"
    print(json.dumps(summary, ensure_ascii=False), f"gzip={len(body)}B", sep="\n")
    if args.dry_run:
        return 0

    import firebase_admin  # noqa: PLC0415 (lazy: unit tests run without Firebase installed)
    from firebase_admin import firestore, storage  # noqa: PLC0415

    bucket_name = args.bucket or f"{args.project}.firebasestorage.app"
    firebase_admin.initialize_app(options={"projectId": args.project, "storageBucket": bucket_name})
    bucket = storage.bucket()
    if upload(bucket, paths, body) != 0:
        return 1
    firestore.client().collection("demo_meta").document(meta_doc).set(summary)
    print(f"wrote firestore demo_meta/{meta_doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
