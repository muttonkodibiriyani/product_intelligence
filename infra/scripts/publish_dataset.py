# /// script
# requires-python = ">=3.12"
# dependencies = ["firebase-admin>=6.5"]
# ///
"""Publish a pi.dataset/v1 JSON file to the demo app (Storage + a Firestore meta mirror).

Validates the contract, refuses anything that looks like an Algolia credential, then uploads
gzipped to datasets/uae/latest.json plus an immutable copy named after the cutoff (for
rollback), and mirrors meta to Firestore demo_meta/current.

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
    parser.add_argument("--prefix", default="datasets/uae", help="Storage folder (contract path)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-test", action="store_true")
    args = parser.parse_args()

    raw = args.path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    errors = validate(doc, raw, allow_test=args.allow_test)
    if errors:
        for err in errors[:50]:
            print(f"INVALID: {err}", file=sys.stderr)
        return 1
    body, paths, summary = package(doc, args.prefix)
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
    firestore.client().collection("demo_meta").document("current").set(summary)
    print("wrote firestore demo_meta/current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
