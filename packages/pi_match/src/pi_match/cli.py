"""``pi-match``: run the first-pass match on two JSONL snapshots.

    uv run pi-match --left ulta.jsonl --right sephora.jsonl --out out/match --cutoff 2026-09-30

Each input line is one ``ProductRecord`` as JSON. Aggregate rows (``"aggregate": true``) are
skipped and counted in ``summary.json``; nothing is written back anywhere. The run is
deterministic: the same inputs and arguments give identical files. ``--cutoff`` is a label
recorded in the output, never a clock.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pi_match.match import brand_overlap, match, without_aggregates
from pi_match.model import ProductRecord
from pi_match.report import summary, write_outputs


def load_jsonl(path: Path) -> tuple[ProductRecord, ...]:
    """Validate every non-empty line; a bad line fails the run with its line number."""
    records: list[ProductRecord] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(ProductRecord.model_validate(json.loads(line)))
            except ValueError as exc:
                raise SystemExit(f"{path}:{number}: invalid record: {exc}") from exc
    return tuple(records)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-match", description=__doc__.split("\n")[0])
    parser.add_argument("--left", type=Path, required=True, help="left snapshot (e.g. Ulta)")
    parser.add_argument("--right", type=Path, required=True, help="right snapshot (Sephora)")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--cutoff", required=True, help="data cutoff label, e.g. 2026-09-30")
    args = parser.parse_args(argv)
    left_all, right_all = load_jsonl(args.left), load_jsonl(args.right)
    left, right = without_aggregates(left_all), without_aggregates(right_all)
    pairs = match(left, right)
    overlap = brand_overlap(left, right)
    stats = summary(pairs, overlap, len(left), len(right))
    stats["aggregates_skipped"] = {
        "left": len(left_all) - len(left),
        "right": len(right_all) - len(right),
    }
    meta = {
        "cutoff": args.cutoff,
        "left": args.left.name,
        "right": args.right.name,
        "matcher": "pi_match first-pass 0.1.0",
    }
    write_outputs(args.out, pairs, overlap, stats, meta)
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
