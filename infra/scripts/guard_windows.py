#!/usr/bin/env python3
"""pi_api's window guard (``pi_api.windows.check_windows``) on a served set before a roll.

Pass every body ``PI_API_DATASETS`` will serve, so the gap is judged across all of them; one body
alone proves only its own window. For each retailer it prints the window, ``since`` and its
whole-retailer ``notObserved`` entries, then the problems and the withheld lines. Exit 1 on any
problem, and on no bodies (an empty set proves nothing); exit 2 on a malformed argument.

    guard_windows.py beauty=beauty.v3.json faces_ae=faces_ae.v3.json ounass_ae=ounass.v3.json

The served key is a label only; the paths are local copies (stored gzip or plain).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pi_api.source import parse
from pi_api.windows import check_windows
from pi_dataset import DatasetV3


def describe(key: str, ds: DatasetV3) -> list[str]:
    """One line per retailer of ``ds``: its window, ``since`` and whole-retailer entries."""
    lines = []
    for r in ds.meta.retailers:
        w = r.window
        window = (
            "none" if w is None else f"run {w.run_id} {w.start.isoformat()}..{w.end.isoformat()}"
        )
        whole = [
            f"{n.start}..{n.end}"
            for n in ds.not_observed
            if n.retailer == r.id and n.context is None and n.categories is None
        ]
        lines.append(f"{key} {r.id}: window {window}; since {r.since}; whole-retailer {whole}")
    lines.append(f"{key}: notObserved entries {len(ds.not_observed)}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bodies", nargs="*", metavar="KEY=PATH")
    ap.add_argument("--allow-test", action="store_true", help="accept meta.test bodies")
    args = ap.parse_args(argv)
    served: list[tuple[str, DatasetV3]] = []
    for arg in args.bodies:
        key, _, path = arg.partition("=")
        if not key or not path:
            print(f"FAIL: bad argument {arg!r}: expected KEY=PATH", file=sys.stderr)
            return 2
        ds = parse(Path(path).read_bytes(), allow_test=args.allow_test)
        print(*describe(key, ds), sep="\n")
        served.append((key, ds))
    print(f"bodies {len(served)}")
    if not served:
        print("FAIL: no bodies given: an empty set proves nothing", file=sys.stderr)
        return 1
    check = check_windows(served)
    print(f"problems {len(check.problems)}", *check.problems, sep="\n  ")
    print(f"withheld {len(check.withheld)}", *check.withheld, sep="\n  ")
    print("window guard:", "FAIL" if check.problems else "ok")
    return 1 if check.problems else 0


if __name__ == "__main__":
    sys.exit(main())
