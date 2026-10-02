"""The committed contract artifacts are exactly what the library generates (drift guard)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_dataset import load_dataset, schema_text
from pi_dataset.examples import render_examples

CONTRACTS = Path(__file__).resolve().parents[3] / "docs" / "contracts"
REGENERATE = "regenerate: uv run pi-dataset schema > docs/contracts/pi-dataset-v2.schema.json"
REGENERATE_V3 = (
    "regenerate: uv run pi-dataset schema --v3 > docs/contracts/pi-dataset-v3.schema.json"
)


def test_committed_schema_matches_the_models() -> None:
    committed = (CONTRACTS / "pi-dataset-v2.schema.json").read_text(encoding="utf-8")
    assert committed == schema_text(), REGENERATE


def test_committed_v3_schema_matches_the_models() -> None:
    committed = (CONTRACTS / "pi-dataset-v3.schema.json").read_text(encoding="utf-8")
    assert committed == schema_text(3), REGENERATE_V3


@pytest.mark.parametrize("name", sorted(render_examples()))
def test_committed_examples_match_the_builder(name: str) -> None:
    committed = (CONTRACTS / "examples" / name).read_bytes()
    assert committed == render_examples()[name], (
        "regenerate: uv run pi-dataset examples docs/contracts/examples"
    )
    assert load_dataset(committed, allow_test=True).meta.test


def test_rules_document_exists() -> None:
    text = (CONTRACTS / "pi-dataset-v2.md").read_text(encoding="utf-8")
    assert "pi.dataset/v2" in text


def test_v3_rules_document_exists() -> None:
    text = (CONTRACTS / "pi-dataset-v3.md").read_text(encoding="utf-8")
    assert "pi.dataset/v3" in text
    assert "0008-vertical-profiles-on-the-wire.md" in text
