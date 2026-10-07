"""Combine readings from several passes over one shop into one page each, newest OK reading first.

A shop read in passes (a first wave, a tail of the pages it missed, a gap pass over what was still
missing) has more than one reading for some pages. This keeps, for each page, the newest reading
whose capture ended ``ok``: a newer failed capture (a block, a 404, a timeout) never shadows an
older good one, and a page no pass read well is left out, never inferred.

Pages are matched on the URL without query, fragment, trailing slash or ``www.``, lowercased.
That match must never join two different addresses: if one key covers more than one distinct
URL among the OK readings, it STOPs (exit 2) and writes nothing. Two readings of a page at the
same instant are broken by pass, gap over tail over wave1.

Local files only; nothing here fetches anything::

    python -m capture_read.combine --wave1 <captures.jsonl> --tail <dir> [--gap <dir>] --out <file>

``--tail`` and ``--gap`` are readings directories (``part-*.jsonl.gz``); each one given must hold
at least one part. ``--out`` must not exist yet. The summary goes to stdout as JSON.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

#: tie-break between readings of a page at the same instant: the later pass wins
RANK = {"wave1": 0, "tail": 1, "gap": 2}


@dataclass(frozen=True)
class Observation:
    at: datetime
    source: str
    line: str
    url: str
    state: str | None

    @property
    def order(self) -> tuple[datetime, int]:
        return self.at, RANK[self.source]


class CombineStopError(Exception):
    """The inputs cannot be combined safely; nothing is written."""


def page_key(url: str) -> str:
    """The match key: no query, fragment, trailing slash or ``www.``, lowercased."""
    return (
        url.split("?", maxsplit=1)[0]
        .split("#", maxsplit=1)[0]
        .rstrip("/")
        .replace("://www.", "://")
        .lower()
    )


def parts(directory: Path) -> list[Path]:
    found = sorted(directory.glob("part-*.jsonl.gz"))
    if not found:
        raise CombineStopError(f"{directory}: no part-*.jsonl.gz")
    return found


def _lines(path: Path) -> Iterator[str]:
    opener: Any = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        yield from fh


def read(source: str, files: Sequence[Path]) -> Iterator[Observation]:
    for path in files:
        for line in _lines(path):
            if not line.strip():
                continue
            row = json.loads(line)
            yield Observation(
                at=datetime.fromisoformat(row["retrieved_at"]),
                source=source,
                line=line if line.endswith("\n") else line + "\n",
                url=row["url"],
                state=row.get("capture_state"),
            )


def combine(
    sources: Sequence[tuple[str, Sequence[Path]]],
) -> tuple[list[Observation], dict[str, Any]]:
    """The kept observation per page, newest first, and the summary."""
    states: Counter[tuple[str, str | None]] = Counter()
    ok: list[Observation] = []
    for source, files in sources:
        for obs in read(source, files):
            states[(source, obs.state)] += 1
            if obs.state == "ok":
                ok.append(obs)
    urls: defaultdict[str, set[str]] = defaultdict(set)
    for obs in ok:
        urls[page_key(obs.url)].add(obs.url)
    joined = {k: sorted(v) for k, v in urls.items() if len(v) > 1}
    if joined:
        raise CombineStopError(
            f"{len(joined)} page keys cover more than one URL: {dict(list(joined.items())[:5])}"
        )
    ok.sort(key=lambda o: o.order, reverse=True)
    best: dict[str, Observation] = {}
    for obs in ok:
        best.setdefault(page_key(obs.url), obs)
    kept = sorted(best.values(), key=lambda o: o.order, reverse=True)
    summary = {
        "by_source_state": {f"{s}:{st}": n for (s, st), n in sorted(states.items(), key=str)},
        "ok_observations": len(ok),
        "pages_after_dedupe": len(kept),
        "kept_from": dict(Counter(o.source for o in kept)),
    }
    return kept, summary


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="capture_read.combine", description=__doc__.split("\n")[0])
    ap.add_argument("--wave1", type=Path, required=True, help="the first wave's captures (.jsonl)")
    ap.add_argument("--tail", type=Path, required=True, help="the tail's readings directory")
    ap.add_argument("--gap", type=Path, help="the gap pass's readings directory")
    ap.add_argument("--out", type=Path, required=True, help="combined captures (.jsonl), new")
    args = ap.parse_args(argv)
    try:
        if args.out.exists():
            raise CombineStopError(f"{args.out} exists")
        if not args.wave1.is_file():
            raise CombineStopError(f"{args.wave1}: no such file")
        sources: list[tuple[str, Sequence[Path]]] = [
            ("wave1", [args.wave1]),
            ("tail", parts(args.tail)),
        ]
        if args.gap is not None:
            sources.append(("gap", parts(args.gap)))
        kept, summary = combine(sources)
    except CombineStopError as stop:
        print(f"STOP: {stop}", file=sys.stderr)
        return 2
    with args.out.open("x", encoding="utf-8") as fh:
        fh.writelines(o.line for o in kept)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
