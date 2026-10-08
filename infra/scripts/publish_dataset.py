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
  ``datasets/<country>/<source>/`` (e.g. datasets/ae/sephora_me, datasets/ae/faces_ae,
  datasets/ae/ounass_ae, datasets/ae/bloomingdales_ae), meta in
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
- v3 (ADR-0008, additive): published exactly like v2, to the same per-source prefix and meta doc
  (demo_meta/v2_<country>_<source>, whose summary carries the schema), so Offer.content
  (description, images, variants with gtin) reaches the API. A v3 offer is keyed by context;
  meta.contexts maps it to its source, and the one-source rule and the guard judge sources. The
  first switch of a live per-source file from v2 to v3 is run by Exec Eng/owner after the
  Reviewer has read its ``--dry-run --live-file`` output (coordinator, 2026-10-06).
- ``--versioned --live-datasets <live PI_API_DATASETS>`` (v2/v3; deploy plan v2,
  pi-api-deploy.md §6): one create-only object ``<prefix>/v/<cutoff>-<sha12>.json`` and nothing
  else (no latest.json, no Firestore), so no path the live revision reads ever changes; refused
  if that path is live or the body is in ``REFUSED_BODIES``. The source guard reads the body the
  live PI_API_DATASETS serves for the source. Prints the PI_API_DATASETS value the new revision
  rolls with; rollback is traffic back to the previous revision.
- ``--allow-beauty-versioned`` (with ``--versioned``; ONLY on the owner's P1 answer to form
  01a11c72-16e3, cited in the deploy report): the one exception to "PI never writes ulta_ae
  data". A body whose sources are exactly sephora_me and ulta_ae goes to a new create-only
  ``datasets/<country>/beauty/v/`` object; latest.json and every existing beauty object stay
  untouched. Retention, against the body the live PI_API_DATASETS serves ulta_ae from: every
  live ulta_ae offer (product id + context) and every live (sku, url) pair must be present. With
  ``--reconciled-removals FILE`` (fresh Ulta only), the offer of a product id listed there,
  backed by the capture lane's reconciliation evidence, may be absent; a blocked or not-observed
  read never justifies an absence.

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
SCHEMA_V3 = "pi.dataset/v3"
PER_SOURCE_SCHEMAS = (SCHEMA_V2, SCHEMA_V3)
# The only sources PI publishes; any other source's data is protected (owner, 2026-10-01).
PUBLISH_SOURCES = ("sephora_me", "faces_ae", "ounass_ae", "bloomingdales_ae")
PROTECTED_SOURCES = ("ulta_ae",)  # owner hard rule: never dropped, not even with --drop-source
BEAUTY_SOURCES = ("sephora_me", "ulta_ae")  # the owner's combined file (--allow-beauty-versioned)
BEAUTY = "beauty"
RETAINED = "ulta_ae"  # --allow-beauty-versioned: no live offer of this source may go missing
V1_PREFIX = "datasets/uae"
V1_SOURCE = "sephora_me"
V1_META_DOC = "current"  # demo_meta/current: the legacy dashboard and smoke_demo read it
# sha256 of an input file or its canonical body: never published (deploy plan v2). The BLM export
# of 2026-10-03 predates the per-retailer window keys a window-aware image requires.
REFUSED_BODIES = {
    "b98194beba185c2f4cfaf211cb055a8ef0b58372bc827e3910011b6dcc673382": "BLM 2026-10-03 export "
    "without per-retailer window keys (re-export it)",
}
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


def validate_v3(raw: str, *, allow_test: bool) -> tuple[Any, list[str]]:
    """As ``validate_v2``, with the v3 model: the contract's strict load, then pi-api's own."""
    from pi_dataset import DatasetError, DatasetV3, load_any  # noqa: PLC0415 (v1 runs without it)

    try:
        dataset = load_any(raw, allow_test=allow_test)
    except DatasetError as exc:
        return None, list(exc.errors)
    if not isinstance(dataset, DatasetV3):
        return None, [f"schema must be {SCHEMA_V3!r}"]
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


def v3_by_source(doc: dict[str, Any]) -> dict[str, Any]:
    """A v3 document's products with offers grouped by source: ``{source: {context: offer}}``.

    meta.contexts maps each context to its retailer (the source). Every other product field is
    kept, so ``source_hash`` still covers the whole product. A v2 product hashes differently, so
    a source PI is not publishing never passes the guard across a v2/v3 switch (it HOLDs).
    """
    owner = {c.get("id"): c.get("retailer") for c in (doc.get("meta") or {}).get("contexts") or []}
    products = []
    for product in doc.get("products") or []:
        grouped: dict[str, dict[str, Any]] = {}
        for context, offer in (product.get("offers") or {}).items():
            grouped.setdefault(str(owner.get(context, context)), {})[context] = offer
        products.append(product | {"offers": grouped})
    return {"schema": SCHEMA_V3, "products": products}


def by_source(doc: dict[str, Any]) -> dict[str, Any]:
    """Any schema's document with offers keyed by source, the shape the guard compares."""
    schema = doc.get("schema")
    if schema == SCHEMA_V2:
        return doc
    if schema == SCHEMA_V3:
        return v3_by_source(doc)
    return v1_by_source(doc)


def offer_counts(doc: dict[str, Any]) -> dict[str, int]:
    """Products with an offer per source, in a document keyed by source (see ``by_source``)."""
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
    """The one source a by-source document publishes, or the reasons it can't be published."""
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
    if live is None or live.get("schema") in PER_SOURCE_SCHEMAS:
        return source_guard(None if live is None else by_source(live), new, publishing, drop)
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


def beauty_errors(doc: dict[str, Any]) -> list[str]:
    """Why a by-source document is not the combined beauty file (exactly BEAUTY_SOURCES)."""
    sources = tuple(sorted(offer_counts(doc)))
    if sources != BEAUTY_SOURCES:
        return [f"beauty: offers must come from exactly {BEAUTY_SOURCES}, not {sources}"]
    return []


def package_v2(
    dataset: Any, allowed: tuple[str, ...] = PUBLISH_SOURCES, *, beauty: bool = False
) -> tuple[bytes, list[str], dict[str, Any], str]:
    """v2 or v3 body (canonical dump), paths under datasets/<country>/<source>, summary, and
    the Firestore doc (``v2_<country>_<source>`` for both: the summary says which schema).
    ``beauty``: the combined sephora_me+ulta_ae file, under datasets/<country>/beauty."""
    from pi_dataset import dump_dataset  # noqa: PLC0415

    meta = dataset.meta
    if len(meta.markets) != 1:
        raise ValueError("a multi-market dataset needs a layout decision first (ADR-0007 §6)")
    country = meta.markets[0].country.lower()
    dumped = dump_dataset(dataset, compact=True)
    doc = json.loads(dumped)
    if beauty:
        errors = beauty_errors(by_source(doc))
        source = None if errors else BEAUTY
    else:
        source, errors = publishing_source(by_source(doc), allowed)
    if source is None:
        raise ValueError(errors[0])
    prefix = f"datasets/{country}/{source}"
    body = gzip.compress(dumped, mtime=0)
    cutoff = meta.cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = re.sub(r"[^0-9TZ]", "", cutoff)
    paths = [f"{prefix}/{stamp}.json", f"{prefix}/latest.json"]
    summary = {
        "schema": doc["schema"],
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


def versioned_path(paths: list[str], body: bytes) -> str:
    """The create-only path a ``--versioned`` publish writes: ``<prefix>/v/<cutoff>-<sha12>.json``,
    keyed by the gunzipped body pi_api parses, so a different body never lands on a used path."""
    prefix, snapshot = paths[0].rsplit("/", 1)
    sha = hashlib.sha256(gzip.decompress(body)).hexdigest()
    return f"{prefix}/v/{snapshot.removesuffix('.json')}-{sha[:12]}.json"


def versioned_outside(path: str, *, beauty: bool = False) -> bool:
    """A ``--versioned`` target outside datasets/<cc>/<published source, or beauty>/v/."""
    allowed = (*PUBLISH_SOURCES, BEAUTY) if beauty else PUBLISH_SOURCES
    pattern = rf"datasets/[a-z]{{2}}/({'|'.join(map(re.escape, allowed))})/v/[^/]+\.json"
    return re.fullmatch(pattern, path) is None


def served_path(live: str, source: str) -> str | None:
    """The path the live PI_API_DATASETS serves ``source`` from (``source=path`` entries)."""
    for entry in live.split(","):
        name, eq, path = entry.strip().partition("=")
        if eq and name == source:
            return path
    return None


def source_offers(doc: dict[str, Any], source: str) -> dict[str, dict[str, Any]]:
    """``{"<product id>/<key>": offer}`` for every offer of ``source`` in a v2/v3 document (v2
    keys offers by source, v3 by context, mapped to its retailer through meta.contexts)."""
    owner = {c.get("id"): c.get("retailer") for c in (doc.get("meta") or {}).get("contexts") or []}
    v3 = doc.get("schema") == SCHEMA_V3
    return {
        f"{p.get('id')}/{key}": offer
        for p in doc.get("products") or []
        for key, offer in (p.get("offers") or {}).items()
        if (owner.get(key, key) if v3 else key) == source and isinstance(offer, dict)
    }


def retention_problems(
    live: dict[str, Any] | None, new: dict[str, Any], removals: frozenset[str] = frozenset()
) -> list[str]:
    """HOLDs for live ``RETAINED`` offers the new document lacks, by product id + key and by
    (sku, url); an offer of a product in ``removals`` (reconciled product ids, fresh loads only)
    may be absent."""
    if live is None:
        return [f"HOLD, no live {RETAINED} body to check retention against"]
    before, after = source_offers(live, RETAINED), source_offers(new, RETAINED)
    kept = {k: o for k, o in before.items() if k.partition("/")[0] not in removals}
    problems = []
    if lost := sorted(set(kept) - set(after)):
        problems.append(f"HOLD, {len(lost)} live {RETAINED} offers missing: {lost[:20]}")
    pairs = {(o.get("sku"), o.get("url")) for o in after.values()}
    if gone := sorted({(o.get("sku"), o.get("url")) for o in kept.values()} - pairs, key=str):
        problems.append(f"HOLD, {len(gone)} live {RETAINED} (sku, url) missing: {gone[:20]}")
    print(f"retention {RETAINED}: live {len(before)} new {len(after)} reconciled {len(removals)}")
    return problems


def refused_body(*bodies: bytes) -> str | None:
    """Why one of these bodies (the input file, the canonical body) is never published."""
    for body in bodies:
        if reason := REFUSED_BODIES.get(hashlib.sha256(body).hexdigest()):
            return reason
    return None


def repoint(live: str, sources: list[str], path: str) -> tuple[str, list[str]]:
    """PI_API_DATASETS with ``sources`` served from ``path`` (added if not yet served); every
    other entry verbatim. Errors: the path is already live, or a source is served bare."""
    entries = [e.strip() for e in live.split(",") if e.strip()]
    errors = []
    served = {e.partition("=")[2] or e for e in entries}
    if path in served:
        errors.append(f"{path} is already in the live PI_API_DATASETS: never written")
    out = []
    for entry in entries:
        source, eq, _ = entry.partition("=")
        out.append(f"{source}={path}" if eq and source in sources else entry)
    have = {e.partition("=")[0] for e in entries if "=" in e}
    out += [f"{s}={path}" for s in sources if s not in have]
    if bare := [e for e in entries if "=" not in e]:
        errors.append(f"bare entries {bare}: name each source (source=path) first")
    return ",".join(out), errors


def publish_versioned(bucket: Any, path: str, body: bytes) -> int:
    """Create-only upload of ``path``; an existing different object is never replaced."""
    state = put(bucket, path, body, create_only=True)
    if state == "different":
        print(f"refusing: {path} already exists with different content", file=sys.stderr)
        return 1
    print(f"{state} gs://{bucket.name}/{path}")
    return 0


def admission_line(body: bytes) -> str:
    """What pi_api parses and an admission record keys on (pi-api-deploy.md §6): the gunzipped
    body. ``pi_dataset.admission_sha256``, inlined because v1 runs without pi_dataset."""
    unpacked = gzip.decompress(body)
    return f"admission body={len(unpacked)}B sha256={hashlib.sha256(unpacked).hexdigest()}"


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--versioned",
        action="store_true",
        help="v2/v3: write only a new create-only <prefix>/v/ object (deploy plan v2)",
    )
    parser.add_argument(
        "--live-datasets",
        metavar="VALUE",
        help="with --versioned: the live revision's PI_API_DATASETS, verbatim",
    )
    parser.add_argument(
        "--allow-beauty-versioned",
        action="store_true",
        help="with --versioned: the sephora_me+ulta_ae file to a new beauty/v/ object. "
        "ONLY on the owner's P1 answer (form 01a11c72-16e3)",
    )
    parser.add_argument(
        "--reconciled-removals",
        type=Path,
        metavar="FILE",
        help="with --allow-beauty-versioned, fresh Ulta only: JSON list of product ids whose "
        "ulta_ae offer the capture lane's reconciliation evidence shows removed",
    )
    return parser


def main() -> int:  # noqa: PLR0911, PLR0912, PLR0915 -- one linear gate after another
    parser = build_parser()
    args = parser.parse_args()
    if protected := sorted(set(args.drop_source) & set(PROTECTED_SOURCES)):
        parser.error(
            f"refusing: --drop-source {', '.join(protected)}: never dropped (owner hard rule)"
        )

    if args.versioned and args.live_datasets is None:
        parser.error("--versioned needs --live-datasets (the live PI_API_DATASETS)")
    beauty = args.allow_beauty_versioned
    if beauty and not args.versioned:
        parser.error("--allow-beauty-versioned needs --versioned")
    if args.reconciled_removals and not beauty:
        parser.error("--reconciled-removals needs --allow-beauty-versioned")
    removals = frozenset(
        json.loads(args.reconciled_removals.read_text()) if args.reconciled_removals else ()
    )

    raw = args.path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    v1 = not (isinstance(doc, dict) and doc.get("schema") in PER_SOURCE_SCHEMAS)
    if args.versioned and v1:
        parser.error("--versioned publishes v2/v3 files only")
    if not isinstance(doc, dict):
        errors = ["not a JSON object"]
    elif v1:
        errors = validate(doc, raw, allow_test=args.allow_test) + v1_source_errors(doc)
    else:
        check = validate_v3 if doc["schema"] == SCHEMA_V3 else validate_v2
        dataset, errors = check(raw, allow_test=args.allow_test)
        errors += beauty_errors(by_source(doc)) if beauty else publishing_source(by_source(doc))[1]
    if errors:
        for err in errors[:50]:
            print(f"INVALID: {err}", file=sys.stderr)
        return 1
    if v1:
        body, paths, summary = package(doc, V1_PREFIX)
        source, meta_doc = V1_SOURCE, V1_META_DOC
        packaged = v1_by_source(json.loads(gzip.decompress(body)))
    else:
        body, paths, summary, meta_doc = package_v2(dataset, beauty=beauty)
        source = str(summary["source"])
        # The guard judges exactly what is uploaded.
        packaged = by_source(json.loads(gzip.decompress(body)))
    # belt and braces: the packagers build these (beauty is held to versioned_outside below)
    if not beauty and (outside := outside_prefixes(paths, v1=v1)):
        print(f"refusing: writes outside the source prefixes: {outside}", file=sys.stderr)
        return 1
    if reason := refused_body(args.path.read_bytes(), gzip.decompress(body)):
        print(f"refusing: {reason}", file=sys.stderr)
        return 1
    if args.versioned:
        target = versioned_path(paths, body)
        datasets, problems = repoint(
            args.live_datasets, list(BEAUTY_SOURCES) if beauty else [source], target
        )
        if versioned_outside(target, beauty=beauty):
            problems.append(f"{target} is outside the versioned prefixes")
        if problems:
            for problem in problems:
                print(f"refusing: {problem}", file=sys.stderr)
            return 1
    print(
        json.dumps(summary, ensure_ascii=False),
        f"gzip={len(body)}B",
        admission_line(body),
        sep="\n",
    )
    drop = tuple(args.drop_source)
    # The guard reads what the live revision serves this source (beauty: ulta_ae) from when
    # versioned, else the prefix's latest.json.
    live_path = paths[-1]
    if args.versioned:
        live_path = served_path(args.live_datasets, RETAINED if beauty else source) or live_path
        if beauty and served_path(args.live_datasets, RETAINED) is None:
            print(f"refusing: the live PI_API_DATASETS serves no {RETAINED}", file=sys.stderr)
            return 1

    def judge(live: dict[str, Any] | None) -> int:
        if beauty:
            new = json.loads(gzip.decompress(body))
            return report_guard(retention_problems(live, new, removals), drop)
        return report_guard(guard(live, packaged, source, drop), drop)

    if args.dry_run:
        held = 0
        if args.live_file:
            held = judge(json.loads(args.live_file.read_text(encoding="utf-8")))
        else:
            print(f"source guard: runs against the live {live_path} before upload")
        if args.versioned and not held:
            print(f"would upload gs://<bucket>/{target}", f"PI_API_DATASETS={datasets}", sep="\n")
        return held

    import firebase_admin  # noqa: PLC0415 (lazy: unit tests run without Firebase installed)
    from firebase_admin import firestore, storage  # noqa: PLC0415

    bucket_name = args.bucket or f"{args.project}.firebasestorage.app"
    firebase_admin.initialize_app(options={"projectId": args.project, "storageBucket": bucket_name})
    bucket = storage.bucket()
    live, generation = read_live(bucket, live_path)
    held = judge(live)
    if args.versioned:  # latest.json and Firestore stay as the live revision reads them
        if held or publish_versioned(bucket, target, body):
            return 1
        print(f"PI_API_DATASETS={datasets}")
        return 0
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
