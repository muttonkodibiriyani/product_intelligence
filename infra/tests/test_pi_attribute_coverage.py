"""Deterministic whole-snapshot attribute coverage receipt."""

from __future__ import annotations

from pathlib import Path

from pi_attribute_coverage import audit

from api_fixture import own_keys, served_dataset
from pi_dataset import dump_dataset


def test_attribute_coverage_reconciles_every_fixture_entity(tmp_path: Path) -> None:
    source = tmp_path / "fixture.json"
    source.write_bytes(dump_dataset(own_keys(served_dataset())))

    first = audit("fixture", source)
    second = audit("fixture", source)

    assert first == second
    assert first["definitionCount"] == 154
    assert first["represented"]["missingProducts"] == 0
    assert first["represented"]["missingTargets"] == 0
    assert first["represented"]["master"] == first["source"]["products"]
    assert first["represented"]["product"] == first["source"]["products"]
    assert first["represented"]["offer"] == first["source"]["offers"]
    assert first["represented"].get("variant", 0) == first["source"]["variants"]
    assert first["slotCount"] == first["represented"]["targets"] * 154
    assert first["sourceEvidenceGaps"] == {"product": {}, "offer": {}}
