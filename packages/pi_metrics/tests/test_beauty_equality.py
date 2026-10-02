"""ADR-0008 §4: every metric on ``upgrade(v2, beauty@1)`` equals the pre-v3 output on v2."""

from __future__ import annotations

import json
from pathlib import Path

from beauty_cases import digest, outputs
from pi_dataset import committed_profile, upgrade

GOLDEN: dict[str, str] = json.loads(
    (Path(__file__).parent / "golden" / "beauty_v2.json").read_text()
)


def _mismatches(got: dict[str, str]) -> list[str]:
    assert got.keys() == GOLDEN.keys()
    return sorted(name for name, h in got.items() if h != GOLDEN[name])


def test_metrics_on_the_pinned_beauty_upgrade_equal_the_v2_golden() -> None:
    profile = committed_profile("beauty", 1)
    assert profile is not None
    got = {name: digest(out) for name, out in outputs(lambda d: upgrade(d, profile)).items()}
    assert _mismatches(got) == []


def test_metrics_read_a_v2_document_as_before() -> None:
    got = {name: digest(out) for name, out in outputs(lambda d: d).items()}
    assert _mismatches(got) == []
