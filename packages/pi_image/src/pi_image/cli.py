"""``pi-image``: image-similarity signal for the cross-retailer matcher.

    uv run pi-image refs --dataset beauty.json --dataset faces.json --out refs.jsonl
    uv run pi-image run --refs refs.jsonl --cache /dev/shm/pi-image --out out/image [--offline]
        [--embed siglip] [--k 10] [--phash-max 6]

``run`` writes, sorted and deterministic for the same inputs and cache:

- ``image_status.jsonl``: per listing, ok / placeholder / missing_image / fetch_failed /
  unreadable, with the reason and the hashes.
- ``image_signals.jsonl``: cross-retailer candidate pairs (``pi_image.model.ImageSignal``).
- ``alias_suggestions.jsonl``: image hits whose brands differ, for brand-alias review only.
- ``image_meta.json``: model id and revision, k, thresholds, placeholder hashes, counts.

``--offline`` reads the cache only and never touches the network (what tests and CI use). The
``siglip`` embedder needs the ``embed`` extra (``uv pip install onnxruntime``); its model is
downloaded once from Hugging Face at a pinned revision and SHA-256.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pi_fetch.transports.http import HttpTransport
from pi_image.candidates import DEFAULT_K, PHASH_NEAR, generate
from pi_image.embed import (
    SIGLIP_BASE,
    Embedder,
    EmbeddingCache,
    SiglipOnnx,
    model_file,
    open_session,
)
from pi_image.fetch import APPROVED_HOSTS, ImageCache, ImageFetcher
from pi_image.model import ImageRef
from pi_image.pipeline import analyse, embeddings, prefetch
from pi_image.placeholder import MIN_BRANDS, SHARED_RADIUS
from pi_image.refs import refs_from_dataset
from pi_match.normalise import normalise_brand

VERSION = "pi_image 0.1.0"


def _write_jsonl(path: Path, rows: Sequence[str]) -> None:
    path.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")


def _download(url: str, dest: Path) -> None:  # pragma: no cover - network, offline runs only
    import httpx  # noqa: PLC0415

    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def _siglip(cache: Path) -> Embedder:  # pragma: no cover - needs onnxruntime and the model
    return SiglipOnnx(open_session(model_file(SIGLIP_BASE, cache / "models", _download)))


def cmd_refs(args: argparse.Namespace) -> int:
    """Dataset JSON files -> refs JSONL."""
    refs: dict[tuple[str, str], ImageRef] = {}
    for path in args.dataset:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for ref in refs_from_dataset(data, normalise_brand):
            refs[(ref.source, ref.source_key)] = ref
    rows = [refs[k].model_dump_json() for k in sorted(refs)]
    _write_jsonl(args.out, rows)
    counts = Counter(k[0] for k in refs)
    print(json.dumps({"refs": len(rows), "by_source": dict(sorted(counts.items()))}))
    return 0


def _load_refs(path: Path) -> tuple[ImageRef, ...]:
    refs: list[ImageRef] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                refs.append(ImageRef.model_validate_json(line))
            except ValueError as exc:
                raise SystemExit(f"{path}:{number}: invalid ref: {exc}") from exc
    return tuple(refs)


def cmd_run(args: argparse.Namespace, embedder: Embedder | None = None) -> int:
    """Refs -> status, signals, alias suggestions and meta."""
    refs = _load_refs(args.refs)
    cache_root: Path = args.cache
    transport = None if args.offline else HttpTransport()
    fetcher = ImageFetcher(ImageCache(cache_root / "images"), transport)

    def progress(done: int, total: int) -> None:
        if done % 500 == 0 or done == total:
            print(f"images {done}/{total} requests={fetcher.requests}", file=sys.stderr)

    try:
        if transport is not None:
            print(json.dumps({"prefetch": prefetch(refs, fetcher, progress)}), file=sys.stderr)
        analysis = analyse(refs, fetcher, progress=progress)
        if embedder is None and args.embed == "siglip":  # pragma: no cover - offline runs only
            embedder = _siglip(cache_root)
        vectors = (
            {}
            if embedder is None
            else embeddings(
                analysis.listings,
                fetcher,
                embedder,
                EmbeddingCache(cache_root / "embeddings", embedder.model_id),
            )
        )
    finally:
        if transport is not None:
            transport.close()
    pairs, aliases = generate(analysis.listings, vectors, k=args.k, phash_max=args.phash_max)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "image_status.jsonl", [li.model_dump_json() for li in analysis.listings])
    _write_jsonl(out / "image_signals.jsonl", [p.model_dump_json() for p in pairs])
    _write_jsonl(out / "alias_suggestions.jsonl", [p.model_dump_json() for p in aliases])
    status = Counter((li.source, li.status.value) for li in analysis.listings)
    by_pair = Counter(f"{p.left_source}|{p.right_source}|{p.via.value}" for p in pairs)
    meta = {
        "tool": VERSION,
        "refs": {
            "file": args.refs.name,
            "sha256": hashlib.sha256(args.refs.read_bytes()).hexdigest(),
        },
        "embedder": None if embedder is None else embedder.model_id,
        "model": (
            None
            if embedder is None or embedder.model_id != SIGLIP_BASE.model_id
            else {
                "repo": SIGLIP_BASE.repo,
                "revision": SIGLIP_BASE.revision,
                "file": SIGLIP_BASE.path,
                "sha256": SIGLIP_BASE.sha256,
            }
        ),
        "k": args.k,
        "phash_max": args.phash_max,
        "placeholder": {"radius": SHARED_RADIUS, "min_brands": MIN_BRANDS},
        "placeholder_hashes": analysis.placeholders,
        "approved_hosts": sorted(APPROVED_HOSTS),
        "stopped_hosts": dict(sorted(fetcher.stopped.items())),
        "status": {f"{s}|{v}": n for (s, v), n in sorted(status.items())},
        "fetch": analysis.fetch_counts,
        "pairs": dict(sorted(by_pair.items())),
        "alias_suggestions": len(aliases),
    }
    (out / "image_meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"pairs": len(pairs), "alias_suggestions": len(aliases), "stopped": fetcher.stopped}
        )
    )
    return 1 if fetcher.stopped else 0


def parser() -> argparse.ArgumentParser:
    """The argument parser."""
    root = argparse.ArgumentParser(prog="pi-image", description=__doc__.split("\n")[0])
    sub = root.add_subparsers(dest="command", required=True)
    refs = sub.add_parser("refs", help="dataset JSON -> image refs JSONL")
    refs.add_argument("--dataset", type=Path, action="append", required=True)
    refs.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("run", help="fetch, hash, flag placeholders, embed, pair")
    run.add_argument("--refs", type=Path, required=True)
    run.add_argument("--cache", type=Path, required=True, help="cache dir (e.g. under /dev/shm)")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--offline", action="store_true", help="cache only, no network")
    run.add_argument("--embed", choices=("none", "siglip"), default="none")
    run.add_argument("--k", type=int, default=DEFAULT_K)
    run.add_argument("--phash-max", type=int, default=PHASH_NEAR)
    return root


def main(argv: Sequence[str] | None = None, embedder: Embedder | None = None) -> int:
    """Entry point; ``embedder`` is injectable for tests."""
    args = parser().parse_args(argv)
    if args.command == "refs":
        return cmd_refs(args)
    return cmd_run(args, embedder)


if __name__ == "__main__":
    raise SystemExit(main())
