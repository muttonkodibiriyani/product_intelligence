"""The gold-set precision gate (ADR-0012 §8).

``gold/sample-v1.json`` holds listing pairs that two labellers labelled independently from saved
evidence, with disagreements adjudicated (``gold/adjudication-*.jsonl``). Labels: ``exact``,
``family``, ``related``, ``different``, ``unsure``. Each pair is run through the matcher on its
own, and every class it emits is scored against the label:

- an ``exact`` edge is right only on an ``exact`` label;
- a ``family`` edge on ``family`` or ``exact`` (the line is the same);
- a ``substitute`` edge on ``related``, ``family`` or ``exact`` (never priced, so a closer pair is
  not harmed);
- ``unsure`` labels are left out.

Precision and its Wilson 95% lower bound per class and category may not fall below
``gold/baseline.json``. Lowering the baseline needs the Reviewer's written approval. A third of
the pairs, chosen by hash of the pair id, is reported apart as ``held_out``. The v1 rules were
tuned with all of v1 in view, so that third is not yet a clean hold-out: gold v2, drawn from the
matcher's own outputs, is.

    uv run python -m pi_match.gold            # report
    uv run python -m pi_match.gold --write    # re-pin the baseline (Reviewer approval)
"""

import argparse
import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pi_core.enums import MatchClass
from pi_match.incremental import ALGO_VERSION, run
from pi_match.model import ProductRecord

#: ``packages/pi_match/gold`` (ADR-0012 §8): data for the gate, not shipped in the package.
GOLD = Path(__file__).resolve().parents[2] / "gold"
Z = 1.959964
OVERALL = "*"
#: The labels each emitted class may stand on.
ACCEPTS: Mapping[MatchClass, frozenset[str]] = {
    MatchClass.EXACT: frozenset({"exact"}),
    MatchClass.FAMILY: frozenset({"family", "exact"}),
    MatchClass.SUBSTITUTE: frozenset({"related", "family", "exact"}),
}
#: Each side's fields; ``source_listing_id`` is the listing token (``ProductRecord.source_key``).
_RECORD_FIELDS = ("source", "brand", "name", "url", "size", "category")


@dataclass(frozen=True)
class Tally:
    right: int
    total: int

    @property
    def precision(self) -> float:
        return self.right / self.total if self.total else 0.0

    @property
    def lower_bound(self) -> float:
        return wilson_lower_bound(self.right, self.total)


def wilson_lower_bound(right: int, total: int, z: float = Z) -> float:
    """The Wilson score interval's lower end for ``right`` of ``total``."""
    if total == 0:
        return 0.0
    p = right / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - spread) / (1 + z * z / total)


def held_out(pair_id: str) -> bool:
    """A stable third of the pairs, by hash of the id."""
    return int(hashlib.sha256(pair_id.encode()).hexdigest(), 16) % 3 == 0


def load(name: str = "sample-v1.json") -> list[dict[str, Any]]:
    raw = (GOLD / name).read_text(encoding="utf-8")
    pairs: list[dict[str, Any]] = json.loads(raw)["pairs"]
    return pairs


def _record(side: Mapping[str, Any]) -> ProductRecord:
    fields = {k: side.get(k) for k in _RECORD_FIELDS}
    return ProductRecord.model_validate({**fields, "source_key": side["source_listing_id"]})


def emitted(pair: Mapping[str, Any]) -> MatchClass | None:
    """The class the matcher gives the pair when it sees only these two listings."""
    a, b = _record(pair["a"]), _record(pair["b"])
    m = run(
        {a.source: [a], b.source: [b]},
        None,
        (),
        scope="gold",
        vertical="beauty",
        algo_version=ALGO_VERSION,
        generated_at="1970-01-01T00:00:00Z",
    )
    return m.edges[0].match_class if m.edges else None


def evaluate(pairs: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Tally]]:
    """``{"<class>" or "<class>@held_out": {category or "*": Tally}}`` over labelled pairs."""
    counts: dict[str, dict[str, list[int]]] = {}
    for pair in pairs:
        label = pair["label"]
        cls = emitted(pair)
        if cls is None or label == "unsure":
            continue
        ok = int(label in ACCEPTS[cls])
        scopes = [cls.value, f"{cls.value}@held_out"] if held_out(pair["id"]) else [cls.value]
        for scope in scopes:
            for category in (pair["a"].get("category") or "?", OVERALL):
                tally = counts.setdefault(scope, {}).setdefault(category, [0, 0])
                tally[0] += ok
                tally[1] += 1
    return {
        scope: {c: Tally(k, n) for c, (k, n) in sorted(by.items())}
        for scope, by in sorted(counts.items())
    }


def as_json(result: Mapping[str, Mapping[str, Tally]]) -> dict[str, dict[str, list[int]]]:
    return {s: {c: [t.right, t.total] for c, t in by.items()} for s, by in result.items()}


def regressions(
    result: Mapping[str, Mapping[str, Tally]], baseline: Mapping[str, Mapping[str, Sequence[int]]]
) -> list[str]:
    """Every pinned class and category whose precision or lower bound fell, as text."""
    out: list[str] = []
    for scope, by in baseline.items():
        for category, (right, total) in by.items():
            pinned = Tally(right, total)
            now = result.get(scope, {}).get(category, Tally(0, 0))
            if now.precision < pinned.precision or now.lower_bound < pinned.lower_bound - 1e-9:
                out.append(
                    f"{scope} {category}: {now.right}/{now.total} "
                    f"(LB {now.lower_bound:.3f}) < pinned {right}/{total} "
                    f"(LB {pinned.lower_bound:.3f})"
                )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pi_match.gold", description=__doc__)
    parser.add_argument("--write", action="store_true", help="re-pin gold/baseline.json")
    args = parser.parse_args(argv)
    result = evaluate(load())
    for scope, by in result.items():
        for category, t in by.items():
            print(f"{scope:22} {category:14} {t.right:4}/{t.total:<4} LB {t.lower_bound:.3f}")
    if args.write:
        text = json.dumps(as_json(result), indent=1, sort_keys=True) + "\n"
        (GOLD / "baseline.json").write_text(text, encoding="utf-8")
        return 0
    baseline = json.loads((GOLD / "baseline.json").read_text(encoding="utf-8"))
    failed = regressions(result, baseline)
    for line in failed:
        print("REGRESSION", line)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
