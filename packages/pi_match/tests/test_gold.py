"""ADR-0012 §8: the gold-set precision gate runs on every change to pi_match."""

import json
from pathlib import Path

import pytest

from pi_match import gold
from pi_match.gold import Tally, held_out, regressions, wilson_lower_bound


def test_precision_does_not_fall_below_the_pinned_baseline() -> None:
    baseline = json.loads((gold.GOLD / "baseline.json").read_text(encoding="utf-8"))
    result = gold.evaluate(gold.load())
    assert regressions(result, baseline) == []
    # accuracy first: every exact edge the matcher gives on the gold set is right
    exact = result["exact"][gold.OVERALL]
    assert exact.right == exact.total
    assert exact.lower_bound >= 0.98


def test_gold_is_double_labelled_and_adjudicated() -> None:
    pairs = gold.load()
    assert len(pairs) >= 600
    assert len({p["id"] for p in pairs}) == len(pairs)
    ruled: dict[str, str] = {}
    for name in ("adjudication-quill.jsonl", "adjudication-verifier.jsonl"):
        for line in (gold.GOLD / name).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            ruled.setdefault(row["id"], row.get("ruling") or row["final"])  # verifier | quill
    labels = {"exact", "family", "related", "different", "unsure"}
    for p in pairs:
        assert p["label"] in labels
        assert p["quill_label"] in labels
        assert p["verifier_label"] in labels
        if p["quill_label"] != p["verifier_label"]:
            assert p["id"] in ruled, p["id"]  # every disagreement has a ruling
        sources = {p["a"]["source"], p["b"]["source"]}
        assert len(sources) == 2


def test_wilson_lower_bound() -> None:
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(189, 189) == pytest.approx(0.980, abs=5e-4)
    assert wilson_lower_bound(188, 189) < 0.98
    assert Tally(0, 0).precision == 0.0


def test_held_out_is_a_stable_third() -> None:
    ids = [f"{i:012x}" for i in range(3000)]
    share = sum(map(held_out, ids)) / len(ids)
    assert 0.3 < share < 0.37
    assert held_out("002a77031fa7") == held_out("002a77031fa7")


def test_regressions_name_what_fell() -> None:
    pinned = {"exact": {"*": [10, 10]}, "family": {"*": [5, 5]}}
    now = {"exact": {"*": Tally(9, 10)}, "family": {"*": Tally(6, 6)}}
    assert regressions(now, pinned) == ["exact *: 9/10 (LB 0.596) < pinned 10/10 (LB 0.722)"]
    # losing pairs (recall) also lowers the bound, and fails until the baseline is re-pinned
    assert regressions({"family": {"*": Tally(2, 2)}}, {"family": {"*": [5, 5]}}) != []
    assert regressions({}, {"exact": {"*": [1, 1]}}) != []


def test_main_reports_and_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("sample-v1.json", "baseline.json"):
        (tmp_path / name).write_text((gold.GOLD / name).read_text(encoding="utf-8"))
    monkeypatch.setattr(gold, "GOLD", tmp_path)
    assert gold.main([]) == 0
    assert "exact" in capsys.readouterr().out
    (tmp_path / "baseline.json").write_text(json.dumps({"exact": {"*": [999, 999]}}))
    assert gold.main([]) == 1
    assert "REGRESSION exact *" in capsys.readouterr().out
    assert gold.main(["--write"]) == 0
    assert gold.main([]) == 0
