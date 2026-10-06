"""``pi-match-run``: the next ``pi.matches/v1`` file from the published source files (ADR-0012).

    uv run pi-match-run \\
        --source ulta_ae=beauty.json --source sephora_me=beauty.json \\
        --source faces_ae=faces.json --previous matches.json --decisions decisions.jsonl \\
        --generated-at 2026-10-03T18:00:00Z --out matches.next.json

Source files are only read (the owner's combined file included). Each ``--decisions`` line is one
``Decision`` as JSON. The output is canonical JSON, so the same inputs give the same bytes, and
``--generated-at`` is a label, never a clock. Nothing is published: that is the operator's step.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pi_match.incremental import ALGO_VERSION, dump, run
from pi_match.listings import listings
from pi_match.matchfile import Decision, MatchFile
from pi_match.model import ProductRecord


def _source(text: str) -> tuple[str, Path]:
    retailer, sep, path = text.partition("=")
    if not sep or not retailer or not path:
        msg = f"expected <retailer>=<path>, got {text!r}"
        raise argparse.ArgumentTypeError(msg)
    return retailer, Path(path)


def load_decisions(path: Path) -> tuple[Decision, ...]:
    """Every non-empty line; a bad line fails the run with its line number."""
    out: list[Decision] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(Decision.model_validate_json(line))
        except ValueError as exc:
            raise SystemExit(f"{path}:{number}: invalid decision: {exc}") from exc
    return tuple(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-match-run", description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=_source, action="append", required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--auto-accept", action="append", default=[], metavar="CATEGORY")
    parser.add_argument("--scope", default="ae")
    parser.add_argument("--vertical", default="beauty")
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    sources: list[tuple[str, Path]] = args.source
    retailers = [r for r, _ in sources]
    if len(set(retailers)) != len(retailers):
        parser.error(f"a retailer is given twice: {retailers}")
    files: dict[Path, Any] = {}
    found: dict[str, tuple[ProductRecord, ...]] = {}
    unkeyed: dict[str, int] = {}
    for retailer, path in sources:
        if path not in files:
            files[path] = json.loads(path.read_text(encoding="utf-8"))
        found[retailer], unkeyed[retailer] = listings(files[path], retailer)
    previous = None
    if args.previous is not None:
        previous = MatchFile.model_validate_json(args.previous.read_text(encoding="utf-8"))
    result = run(
        found,
        previous,
        load_decisions(args.decisions) if args.decisions is not None else (),
        scope=args.scope,
        vertical=args.vertical,
        algo_version=ALGO_VERSION,
        generated_at=args.generated_at,
        auto_accept=args.auto_accept,
        unkeyed=unkeyed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump(result), encoding="utf-8")
    print(json.dumps(summary(result), sort_keys=True))
    return 0


def summary(file: MatchFile) -> dict[str, Any]:
    """Counts per retailer pair and class, review reasons, listings and unkeyed offers."""
    edges: dict[str, int] = {}
    for e in file.edges:
        key = f"{e.a.retailer}|{e.b.retailer}|{e.match_class.value}|{e.review_state.value}"
        edges[key] = edges.get(key, 0) + 1
    review: dict[str, int] = {}
    for r in file.review:
        review[r.reason.value] = review.get(r.reason.value, 0) + 1
    return {
        "listings": {r: len(t) for r, t in file.listings.items()},
        "unkeyed": dict(file.unkeyed),
        "candidates": len(file.candidates),
        "decisions": len(file.decisions),
        "edges": dict(sorted(edges.items())),
        "review": dict(sorted(review.items())),
    }


if __name__ == "__main__":
    raise SystemExit(main())
