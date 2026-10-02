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
  needs the owner's explicit approval for that publish. It is refused outright for ulta_ae: the
  owner's Ulta rows are never dropped (owner hard rule).
- v1 (the legacy root dashboard's input): Sephora only, to datasets/uae/ (latest.json plus the
  create-only cutoff snapshot), meta in demo_meta/current. Offers are keyed by retailer id; the
  ids map to sources through meta.retailers, and a null offer (a blocked retailer's placeholder)
  carries no data. The new file may carry data from sephora_me only, and the publish is HELD if
  the live v1 carries any other source's data or the guard above finds a loss.
- latest.json is replaced only if it is still the generation the guard read.
- A v2 file must also load through pi-api's own serving parse (``pi_api.source.parse``, which
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "pi.dataset/v1"
SCHEMA_V2 = "pi.dataset/v2"
# The only sources PI publishes; any other source's data is protected (owner, 2026-10-01).
PUBLISH_SOURCES = ("sephora_me",)
PROTECTED_SOURCES = ("ulta_ae",)  # owner hard rule: never dropped, not even with --drop-source
V1_PREFIX = "datasets/uae"
V1_SOURCE = "sephora_me"
V1_META_DOC = "current"  # demo_meta/current: the legacy dashboard and smoke_demo read it
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


def outside_prefixes(
    paths: list[str], allowed: tuple[str, ...] = PUBLISH_SOURCES, *, v1: bool = False
) -> list[str]:
    """Paths outside datasets/<country>/<allowed source>/ (v1: datasets/uae/): never written."""
    pattern = re.compile(
        rf"{re.escape(V1_PREFIX)}/[^/]+\.json"
        if v1
        else rf"datasets/[a-z]{{2}}/({'|'.join(map(re.escape, allowed))})/[^/]+\.json"
    )
    return [p for p in paths if not pattern.fullmatch(p)]  # fullmatch: no trailing newline


def v1_by_source(doc: dict[str, Any]) -> dict[str, Any]:
    """A v1 document's products with offers keyed by source (meta.retailers key), nulls dropped."""
    keys = {
        r.get("id"): r.get("key") or r.get("id")
        for r in (doc.get("meta") or {}).get("retailers") or []
    }
    return {
        "products": [
            {
                "id": p.get("id"),
                "offers": {
                    keys.get(rid, rid): o
                    for rid, o in (p.get("offers") or {}).items()
                    if o is not None
                },
            }
            for p in doc.get("products") or []
        ]
    }


def v1_source_errors(doc: dict[str, Any]) -> list[str]:
    """Why a v1 file can't be published: it must carry sephora_me data and nothing else."""
    sources = sorted(offer_counts(v1_by_source(doc)))
    if sources != [V1_SOURCE]:
        return [f"v1 publishes {V1_SOURCE} data only: offers come from {sources or 'no source'}"]
    return []


def guard(
    live: dict[str, Any] | None, new: dict[str, Any], publishing: str, drop: tuple[str, ...] = ()
) -> list[str]:
    """source_guard for either schema; a live v1 with another source's data is never replaced."""
    drop = unprotected(drop)
    if live is None or live.get("schema") == SCHEMA_V2:
        return source_guard(live, new, publishing, drop)
    live = v1_by_source(live)
    foreign = [
        f"HOLD, live v1 carries {source} data ({n} offers): not PI's to replace"
        for source, n in sorted(offer_counts(live).items())
        if source != V1_SOURCE and source not in drop
    ]
    return foreign or source_guard(live, new, publishing, drop)


def unprotected(drop: tuple[str, ...]) -> tuple[str, ...]:
    """``drop`` without the protected sources: the guard never waives them (main() refuses)."""
    return tuple(source for source in drop if source not in PROTECTED_SOURCES)


def source_guard(
    live: dict[str, Any] | None,
    new: dict[str, Any],
    publishing: str,
    drop: tuple[str, ...] = (),
) -> list[str]:
    """HOLD reasons for replacing ``live`` with ``new``; empty when nothing live is lost."""
    drop = unprotected(drop)
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


def read_live(bucket: Any, path: str) -> tuple[dict[str, Any] | None, int]:
    """The live object at ``path`` (stored gzip or plain) and its generation; (None, 0) if none."""
    blob = bucket.get_blob(path)
    if blob is None:
        return None, 0
    raw = blob.download_as_bytes(raw_download=True)
    live: dict[str, Any] = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    return live, int(blob.generation)


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


def put(
    bucket: Any, path: str, body: bytes, *, create_only: bool, generation: int | None = None
) -> str:
    """Upload body; create-only returns 'unchanged' or 'different' when the path exists.

    ``generation`` (replace only): upload only if the object is still that generation (0: only
    if there is none); a mismatch raises PreconditionFailed.
    """
    blob = bucket.blob(path)
    blob.content_encoding = "gzip"
    blob.cache_control = "private, no-cache"
    if not create_only:
        blob.upload_from_string(
            body, content_type="application/json; charset=utf-8", if_generation_match=generation
        )
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


def upload(bucket: Any, paths: list[str], body: bytes, latest_generation: int | None = None) -> int:
    """Upload to every path in order; a cutoff snapshot is create-only. Returns an exit code.

    ``latest_generation``: replace latest.json only if it is still this generation (0: only if
    there is none), i.e. what the source guard judged; None replaces it unconditionally.

    A cutoff snapshot that already exists with different content is never replaced. The body
    is still published if its generatedAt is strictly later than the snapshot's: as a
    create-only revision copy (rollback keeps both), then latest.json. Otherwise latest.json
    stays untouched.
    """
    for path in paths:
        target = path
        if path.endswith("/latest.json"):
            try:
                state = put(bucket, path, body, create_only=False, generation=latest_generation)
            except Exception as exc:
                if getattr(exc, "code", None) != PRECONDITION_FAILED:
                    raise
                print(f"refusing: {path} changed since the source guard read it", file=sys.stderr)
                return 1
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
        help="let this live source be missing, smaller or changed (repeatable, one ID each). "
        "OWNER APPROVAL REQUIRED; refused for ulta_ae",
    )
    args = parser.parse_args()
    if protected := sorted(set(args.drop_source) & set(PROTECTED_SOURCES)):
        parser.error(
            f"refusing: --drop-source {', '.join(protected)}: never dropped (owner hard rule)"
        )

    raw = args.path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    v1 = not (isinstance(doc, dict) and doc.get("schema") == SCHEMA_V2)
    if not isinstance(doc, dict):
        errors = ["not a JSON object"]
    elif v1:
        errors = validate(doc, raw, allow_test=args.allow_test) + v1_source_errors(doc)
    else:
        dataset, errors = validate_v2(raw, allow_test=args.allow_test)
        errors += publishing_source(doc)[1]
    if errors:
        for err in errors[:50]:
            print(f"INVALID: {err}", file=sys.stderr)
        return 1
    if v1:
        body, paths, summary = package(doc, V1_PREFIX)
        source, meta_doc = V1_SOURCE, V1_META_DOC
        packaged = v1_by_source(json.loads(gzip.decompress(body)))
    else:
        body, paths, summary, meta_doc = package_v2(dataset)
        source = str(summary["source"])
        packaged = json.loads(gzip.decompress(body))  # the guard judges exactly what is uploaded
    if outside := outside_prefixes(paths, v1=v1):  # belt and braces: the packagers build these
        print(f"refusing: writes outside the source prefixes: {outside}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False), f"gzip={len(body)}B", sep="\n")
    drop = tuple(args.drop_source)
    if args.dry_run:
        if args.live_file:
            live = json.loads(args.live_file.read_text(encoding="utf-8"))
            return report_guard(guard(live, packaged, source, drop), drop)
        print(f"source guard: runs against the live {paths[-1]} before upload")
        return 0

    import firebase_admin  # noqa: PLC0415 (lazy: unit tests run without Firebase installed)
    from firebase_admin import firestore, storage  # noqa: PLC0415

    bucket_name = args.bucket or f"{args.project}.firebasestorage.app"
    firebase_admin.initialize_app(options={"projectId": args.project, "storageBucket": bucket_name})
    bucket = storage.bucket()
    live, generation = read_live(bucket, paths[-1])
    held = report_guard(guard(live, packaged, source, drop), drop)
    if held or upload(bucket, paths, body, latest_generation=generation):
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
