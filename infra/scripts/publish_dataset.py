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
and mirrors meta to Firestore. A re-export of an already published cutoff (different content,
strictly later generatedAt) gets its own create-only revision copy ``<stamp>-g<generatedAt>.json``;
the original cutoff copy is never replaced.

- v2 (ADR-0007 §6): checked by pi_dataset's strict ``load_dataset``. One file per source: the
  file's offers must all come from one source PI publishes (``PUBLISH_SOURCES``), and it goes to
  ``datasets/<country>/<source>/`` (e.g. datasets/ae/sephora_me), meta in
  demo_meta/v2_<country>_<source>. Nothing is ever written outside those prefixes: other sources'
  data (e.g. ulta_ae in datasets/ae/beauty/latest.json) is not PI's to replace (owner, 2026-10-01).
- Before uploading, the live latest.json at the target is read and the publish is HELD if any
  live source is missing from the new file or has fewer offers, or if any source other than the
  one being published has different products. The only override is ``--drop-source <id>``, which
  needs the owner's explicit approval for that publish.
- A v2 file must also load through pi-api's own serving parse (``pi_api.source.parse``, which
  upgrades it to v3). pi-api skips a dataset it can't load, so uploading one would leave the API
  with no data: such a file is held, never uploaded (decision 2026-10-01, after the v3 upgrade
  refused shared-url size variants).
- v1 (datasets/uae, the legacy dashboard's input) is validated but no longer published: it is a
  write outside the per-source prefixes.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "pi.dataset/v1"
SCHEMA_V2 = "pi.dataset/v2"
# The only sources PI publishes; any other source's data is protected (owner, 2026-10-01).
PUBLISH_SOURCES = ("sephora_me",)
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


def offer_counts(doc: dict[str, Any]) -> dict[str, int]:
    """Offers per source (retailer id) in a v2 document."""
    counts: dict[str, int] = {}
    for product in doc.get("products") or []:
        for source in product.get("offers") or {}:
            counts[source] = counts.get(source, 0) + 1
    return counts


def source_hash(doc: dict[str, Any], source: str) -> str:
    """sha256 over every product carrying an offer from ``source``, order-independent."""
    products = sorted(
        (p for p in doc.get("products") or [] if source in (p.get("offers") or {})),
        key=lambda p: str(p.get("id")),
    )
    canonical = json.dumps(products, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def publishing_source(
    doc: dict[str, Any], allowed: tuple[str, ...] = PUBLISH_SOURCES
) -> tuple[str | None, list[str]]:
    """The one source a v2 file publishes, or the reasons it can't be published."""
    sources = sorted(offer_counts(doc))
    if len(sources) != 1:
        return None, [f"one source per file: offers come from {sources or 'no source'}"]
    if sources[0] not in allowed:
        return None, [f"{sources[0]} is not a source PI publishes ({', '.join(allowed)})"]
    return sources[0], []


def outside_prefixes(paths: list[str], allowed: tuple[str, ...] = PUBLISH_SOURCES) -> list[str]:
    """Paths outside datasets/<country>/<allowed source>/: never written."""
    pattern = re.compile(
        rf"^datasets/[a-z]{{2}}/({'|'.join(map(re.escape, allowed))})/[^/]+\.json$"
    )
    return [p for p in paths if not pattern.match(p)]


def source_guard(
    live: dict[str, Any] | None,
    new: dict[str, Any],
    publishing: str,
    drop: tuple[str, ...] = (),
) -> list[str]:
    """HOLD reasons for replacing ``live`` with ``new``; empty when nothing live is lost."""
    if live is None:
        return []
    live_counts, new_counts = offer_counts(live), offer_counts(new)
    problems = []
    for source, count in sorted(live_counts.items()):
        if source in drop:
            continue
        if source not in new_counts:
            problems.append(f"HOLD, live source {source} ({count} offers) is missing")
        elif new_counts[source] < count:
            problems.append(f"HOLD, {source} drops from {count} to {new_counts[source]} offers")
        elif source != publishing and source_hash(live, source) != source_hash(new, source):
            problems.append(f"HOLD, {source} is not {publishing}'s to change: its products differ")
    return problems


def package_v2(
    dataset: Any, allowed: tuple[str, ...] = PUBLISH_SOURCES
) -> tuple[bytes, list[str], dict[str, Any], str]:
    """v2 body (canonical dump), paths under datasets/<country>/<source>, summary, Firestore doc."""
    from pi_dataset import dump_dataset  # noqa: PLC0415

    meta = dataset.meta
    if len(meta.markets) != 1:
        raise ValueError("a multi-market dataset needs a layout decision first (ADR-0007 §6)")
    country = meta.markets[0].country.lower()
    dumped = dump_dataset(dataset)
    source, errors = publishing_source(json.loads(dumped), allowed)
    if source is None:
        raise ValueError(errors[0])
    prefix = f"datasets/{country}/{source}"
    body = gzip.compress(dumped, mtime=0)
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
        "source": source,
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
    return body, paths, summary, f"v2_{country}_{source}"


def read_live(bucket: Any, path: str) -> dict[str, Any] | None:
    """The live object at ``path`` (stored gzip or plain), or None if there is none yet."""
    blob = bucket.get_blob(path)
    if blob is None:
        return None
    raw = blob.download_as_bytes(raw_download=True)
    live: dict[str, Any] = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    return live


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


def generated_at(body: bytes) -> datetime:
    """meta.generatedAt of a packaged (gzipped) or plain dataset body, in UTC."""
    raw = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    stamp = str(json.loads(raw)["meta"]["generatedAt"])
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"meta.generatedAt {stamp!r} has no timezone")
    return parsed.astimezone(UTC)


def revision_path(snapshot: str, generated: datetime) -> str:
    """Revision copy of a cutoff snapshot, keyed by the new export's generatedAt."""
    return f"{snapshot.removesuffix('.json')}-g{generated.strftime('%Y%m%dT%H%M%SZ')}.json"


def put(bucket: Any, path: str, body: bytes, *, create_only: bool) -> str:
    """Upload body; create-only returns 'unchanged' or 'different' when the path exists."""
    blob = bucket.blob(path)
    blob.content_encoding = "gzip"
    blob.cache_control = "private, no-cache"
    if not create_only:
        blob.upload_from_string(body, content_type="application/json; charset=utf-8")
        return "uploaded"
    try:
        blob.upload_from_string(
            body, content_type="application/json; charset=utf-8", if_generation_match=0
        )
    except Exception as exc:
        if getattr(exc, "code", None) != PRECONDITION_FAILED:
            raise
        existing = bucket.get_blob(path)
        if existing is None or existing.md5_hash != blob_md5(body):
            return "different"
        return "unchanged"
    return "uploaded"


def upload(bucket: Any, paths: list[str], body: bytes) -> int:
    """Upload to every path in order; a cutoff snapshot is create-only. Returns an exit code.

    A cutoff snapshot that already exists with different content is never replaced. The body
    is still published if its generatedAt is strictly later than the snapshot's: as a
    create-only revision copy (rollback keeps both), then latest.json. Otherwise latest.json
    stays untouched.
    """
    for path in paths:
        target = path
        if path.endswith("/latest.json"):
            state = put(bucket, path, body, create_only=False)
        else:
            state = put(bucket, path, body, create_only=True)
            if state == "different":
                old = generated_at(bucket.get_blob(path).download_as_bytes(raw_download=True))
                new = generated_at(body)
                if new <= old:
                    print(
                        f"refusing: {path} already exists with different content "
                        f"(generatedAt {old:%Y-%m-%dT%H:%M:%SZ}; this file "
                        f"{new:%Y-%m-%dT%H:%M:%SZ} is not later)",
                        file=sys.stderr,
                    )
                    return 1
                print(f"kept gs://{bucket.name}/{path} (earlier export of this cutoff)")
                target = revision_path(path, new)
                state = put(bucket, target, body, create_only=True)
                if state == "different":
                    print(
                        f"refusing: {target} already exists with different content",
                        file=sys.stderr,
                    )
                    return 1
        print(f"{state} gs://{bucket.name}/{target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--bucket", default=None, help="default: <project>.firebasestorage.app")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument(
        "--live-file",
        type=Path,
        help="dry run: check the source guard against this copy of the live latest.json",
    )
    parser.add_argument(
        "--drop-source",
        action="append",
        default=[],
        metavar="ID",
        help="let this live source be missing, smaller or changed. OWNER APPROVAL REQUIRED",
    )
    args = parser.parse_args()

    raw = args.path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    if not (isinstance(doc, dict) and doc.get("schema") == SCHEMA_V2):
        errors = validate(doc, raw, allow_test=args.allow_test) if isinstance(doc, dict) else []
        errors.append("v1 is no longer published (datasets/uae is outside the source prefixes)")
    else:
        dataset, errors = validate_v2(raw, allow_test=args.allow_test)
        errors += publishing_source(doc)[1]
    if errors:
        for err in errors[:50]:
            print(f"INVALID: {err}", file=sys.stderr)
        return 1
    body, paths, summary, meta_doc = package_v2(dataset)
    source = str(summary["source"])
    packaged = json.loads(gzip.decompress(body))  # the guard judges exactly what is uploaded
    if outside := outside_prefixes(paths):  # belt and braces: package_v2 builds these paths
        print(f"refusing: writes outside the source prefixes: {outside}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False), f"gzip={len(body)}B", sep="\n")
    drop = tuple(args.drop_source)
    if args.dry_run:
        if args.live_file:
            live = json.loads(args.live_file.read_text(encoding="utf-8"))
            return report_guard(source_guard(live, packaged, source, drop), drop)
        print(f"source guard: runs against the live {paths[-1]} before upload")
        return 0

    import firebase_admin  # noqa: PLC0415 (lazy: unit tests run without Firebase installed)
    from firebase_admin import firestore, storage  # noqa: PLC0415

    bucket_name = args.bucket or f"{args.project}.firebasestorage.app"
    firebase_admin.initialize_app(options={"projectId": args.project, "storageBucket": bucket_name})
    bucket = storage.bucket()
    held = report_guard(source_guard(read_live(bucket, paths[-1]), packaged, source, drop), drop)
    if held or upload(bucket, paths, body):
        return 1  # a HOLD uploads nothing; upload() reports its own refusals
    firestore.client().collection("demo_meta").document(meta_doc).set(summary)
    print(f"wrote firestore demo_meta/{meta_doc}")
    return 0


def report_guard(problems: list[str], drop: tuple[str, ...]) -> int:
    """Print the source guard's verdict; nonzero means nothing may be uploaded."""
    for problem in problems:
        print(problem, file=sys.stderr)
    if drop:
        print(
            f"WARNING: --drop-source {', '.join(drop)} (owner approval required)", file=sys.stderr
        )
    print("source guard:", "HOLD" if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
