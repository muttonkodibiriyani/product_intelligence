"""Build the ordered plan for a PLAN continuation run (stock-only or AR-only).

Usage::

    python -m sephora_snapshot.plan <snapshot_dir> <out.json.gz> --phase stock|ar|price
        [--done <dir> ...] [--brands <brands.txt>] [--matched <pids.txt>]

``snapshot_dir`` holds the main run's ``seed.json`` and ``pdp_en`` parts. ``--phase stock``
keeps EN seeds only (so the job reads stock and fetches no AR page) and skips products whose
stock was already read (tRPC HTTP 200) in ``snapshot_dir`` or any ``--done`` folder.
``--phase ar`` keeps AR seeds only (run it with ``TRPC=0``) and skips AR pages already fetched.
``--phase price`` keeps every EN seed (a price re-read is a new dated observation, so nothing is
skipped) and adds a ``trpc`` list: only the products whose stock is not read yet, in plan order.

Order: matched P-ids (if given) -> products of the listed brands (if given) -> everything else,
each tier in the main job's seeded-shuffle order, so a cutoff still leaves a fair sample.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SHUFFLE_SEED = 20260930  # the main job's order


def norm_brand(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]", "", folded)


def records(folder: Path, stream: str) -> Iterator[dict[str, Any]]:
    for part in sorted((folder / stream).glob("part-*.jsonl.gz")):
        for line in gzip.decompress(part.read_bytes()).splitlines():
            yield json.loads(line)


def stock_read(rec: dict[str, Any]) -> bool:
    """The loader's condition for a usable stock read: HTTP 200 with a parseable variant list."""
    try:
        data = rec["json"][0]["result"]["data"]["json"]
    except (KeyError, IndexError, TypeError):
        return False
    return rec.get("status") == 200 and isinstance(data, dict)


def done_pids(folders: list[Path], phase: str) -> set[str]:
    """Products this phase already covered: a usable stock read, or an AR page extracted."""
    done: set[str] = set()
    for folder in folders:
        if phase == "stock":
            done |= {r["pid"] for r in records(folder, "trpc") if stock_read(r)}
        else:
            done |= {r["pid"] for r in records(folder, "pdp_ar")}
    return done


def build(  # noqa: PLR0913 - one argument per plan input
    root: Path,
    phase: str,
    done: set[str],
    *,
    brands: set[str] | None = None,
    matched: list[str] | None = None,
    stock_done: set[str] | None = None,
) -> dict[str, Any]:
    """``stock_done`` (price phase) is left out of the plan's ``trpc`` list."""
    lang = "ar" if phase == "ar" else "en"
    full: dict[str, dict[str, str]] = json.loads(gzip.decompress((root / "seed.json").read_bytes()))
    seed = {pid: {lang: urls[lang]} for pid, urls in full.items() if lang in urls}
    base = sorted(seed)
    random.Random(SHUFFLE_SEED).shuffle(base)  # noqa: S311 - ordering, not crypto
    base = [p for p in base if p not in done]
    brand_of = {
        r["pid"]: ((r.get("extract") or {}).get("productDetails") or {}).get("c_brand") or {}
        for r in records(root, "pdp_en")
    }
    wanted = {norm_brand(b) for b in brands or set()}
    first = [p for p in matched or [] if p in seed and p not in done]
    seen = set(first)
    tier = [
        p
        for p in base
        if p not in seen and wanted and norm_brand(brand_of.get(p, {}).get("name") or "") in wanted
    ]
    seen |= set(tier)
    rest = [p for p in base if p not in seen]
    order = first + tier + rest
    out: dict[str, Any] = {"order": order, "seed": {p: seed[p] for p in order}}
    if phase == "price":
        out["trpc"] = [p for p in order if p not in (stock_done or set())]
    out["meta"] = {
        "phase": phase,
        "seeded": len(seed),
        "already_done": len(done & set(seed)),
        "planned": len(order),
        "matched": len(first),
        "brand_tier": len(tier),
        "rest": len(rest),
    }
    if phase == "price":
        out["meta"]["trpc"] = len(out["trpc"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sephora_snapshot.plan")
    ap.add_argument("snapshot_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--phase", choices=["stock", "ar", "price"], required=True)
    ap.add_argument("--done", type=Path, action="append", default=[])
    ap.add_argument("--brands", type=Path)
    ap.add_argument("--matched", type=Path)
    args = ap.parse_args(argv)
    brands = (
        {
            ln.strip()
            for ln in args.brands.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        }
        if args.brands
        else None
    )
    matched = args.matched.read_text().split() if args.matched else None
    folders = [args.snapshot_dir, *args.done]
    if args.phase == "price":
        done: set[str] = set()
        stock_done = done_pids(folders, "stock")
    else:
        done, stock_done = done_pids(folders, args.phase), set()
    plan = build(
        args.snapshot_dir, args.phase, done, brands=brands, matched=matched, stock_done=stock_done
    )
    args.out.write_bytes(gzip.compress(json.dumps(plan, ensure_ascii=False).encode()))
    print(json.dumps(plan["meta"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
