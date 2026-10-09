"""Re-export a published multi-retailer ``pi.dataset/v2`` body as v3 with each retailer's own
``fields`` and ``capabilities`` (ADR-0013), from the body alone: no database, no crawl.

``pi_dataset.compose.resolved_retailers`` refuses a file of several retailers without them, so
main's pi-api can't serve the owner's combined beauty file (sephora_me + ulta_ae) until it is
re-exported. This is that re-export. It is ``upgrade(v2, <vertical>@1)`` (what pi-api already
reads a v2 body as, ``pi_metrics.view.as_v3``) plus, per retailer, ``v2._states`` over the
retailer's own offers. Products, offers, values and every other meta key are copied unchanged.

The body does not say which retailer's values ``meta.fields`` counted as stale (``v2.Stale``
needs the listing rows), nor how its producer judged a field, so a retailer is never given a
better state than the file states: it keeps the file's state, except for a field none of its own
offers carries, which is the retailer's own ``not_collected`` (or ``not_published``). A
capability is on only where both the file and the retailer's own offers turn it on.

    uv run python -m scripts.demo_export.reexport IN OUT
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
from collections.abc import Mapping
from pathlib import Path

from pi_dataset import Dataset, DatasetV3, FieldStatus, dump_dataset, load_any
from pi_dataset.models import Capabilities, Offer
from pi_dataset.profiles import committed_profile
from pi_dataset.upgrade import upgrade
from scripts.demo_export.v2 import Stale, _states

#: A retailer's own state for a field none of its offers carries (``v2._states``).
ABSENT = frozenset({FieldStatus.NOT_COLLECTED, FieldStatus.NOT_PUBLISHED})


def reexport(v2: Dataset) -> DatasetV3:
    """``v2`` as v3 with per-retailer fields and capabilities; ``ValueError`` if it can't be."""
    if len(v2.meta.dates) != 1:
        raise ValueError(f"a snapshot of one date only, not {len(v2.meta.dates)}")
    if any(r.id not in {c for p in v2.products for c in p.offers} for r in v2.meta.retailers):
        raise ValueError("every retailer must have offers: states come from its own offers")
    profile = committed_profile(v2.meta.vertical, 1)
    if profile is None:
        raise ValueError(f"{v2.meta.vertical}@1 is not a committed profile")
    v3 = upgrade(v2, profile)
    offers: dict[str, list[Offer]] = {r.id: [] for r in v2.meta.retailers}
    for p in v2.products:
        for rid, o in p.offers.items():
            offers[rid].append(o)
    retailers = []
    for r in v3.meta.retailers:
        fields, capabilities = _states(offers[r.id], Stale(v2.meta.dates[-1]), 0)
        retailers.append(
            r.model_copy(
                update={
                    "fields": capped(fields, v2.meta.fields),
                    "capabilities": both(capabilities, v2.meta.capabilities),
                }
            )
        )
    meta = v3.meta.model_copy(update={"retailers": tuple(retailers)})
    return v3.model_copy(update={"meta": meta})


def capped(
    own: Mapping[str, FieldStatus], file: Mapping[str, FieldStatus]
) -> dict[str, FieldStatus]:
    """The file's state of each field, or the retailer's ``own`` where its offers carry none."""
    if own.keys() != file.keys():
        raise ValueError(f"fields {sorted(own)} are not the file's {sorted(file)}")
    return {
        name: own[name] if own[name] in ABSENT and file[name] not in ABSENT else file[name]
        for name in file
    }


def both(own: Capabilities, file: Capabilities) -> Capabilities:
    names = Capabilities.model_fields
    return Capabilities(**{n: getattr(own, n) and getattr(file, n) for n in names})


def read(path: Path) -> Dataset:
    raw = path.read_bytes()
    ds = load_any(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    if not isinstance(ds, Dataset):
        raise SystemExit(f"{path}: not a pi.dataset/v2 body")
    return ds


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="the v2 body (gzip or plain)")
    parser.add_argument("output", type=Path, help="the v3 body, compact (never overwritten)")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise SystemExit(f"{args.output} exists: refusing to overwrite")
    v3 = reexport(read(args.input))
    body = dump_dataset(v3, compact=True)
    if load_any(body) != v3:  # what pi-api reads back must be what was built
        raise SystemExit("the written body does not read back as built")
    args.output.write_bytes(body)
    print(f"sha256 {hashlib.sha256(body).hexdigest()} bytes {len(body)}")
    for r in v3.meta.retailers:
        fields = ", ".join(f"{k}={v}" for k, v in sorted((r.fields or {}).items()))
        print(f"{r.id}: {fields}; promotions={r.capabilities and r.capabilities.promotions}")


if __name__ == "__main__":
    main()
