"""Field coverage over synthetic datasets built from the committed contract example."""

from __future__ import annotations

# ruff: noqa: S101
import json
from pathlib import Path
from typing import Any

import pytest

from pi_dataset import Dataset, DatasetV3, committed_profile, load_any, load_dataset, upgrade
from scripts.similar_coverage.coverage import CONTENT_COUNTS, coverage, main

EXAMPLE = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "examples" / "ae-pilot.json"
NORTH, SOUTH = "example_north_ae", "example_south_ae"


def _v2() -> dict[str, Any]:
    """The example with a fragrance product, a gendered EDP and an early offer."""
    raw: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    first, second, third = raw["products"]
    first.update(name="Bloom Eau de Parfum for Women", category=["fragrance", "women"])
    first["offers"][NORTH]["image"] = "https://example.com/bloom.jpg"
    second.update(category=["makeup"])
    for offer in third["offers"].values():
        offer["early"] = True
    return raw


def _doc(raw: dict[str, Any]) -> Dataset:
    return load_dataset(json.dumps(raw), allow_test=True)


def _v3(raw: dict[str, Any]) -> DatasetV3:
    profile = committed_profile("beauty", 1)
    assert profile is not None
    dumped: dict[str, Any] = json.loads(upgrade(_doc(raw), profile).model_dump_json(by_alias=True))
    offer = dumped["products"][0]["offers"][NORTH]
    offer["content"] = {
        "captured": ["description", "images"],
        "description": "A floral scent with top notes of pear and a woody base.",
        "images": ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        "family": "fam-1",
    }
    doc = load_any(json.dumps(dumped), allow_test=True)
    assert isinstance(doc, DatasetV3)
    return doc


def test_v2_counts_per_retailer_and_scope_and_skips_early_offers() -> None:
    raw = _v2()
    report = coverage([_doc(raw)])
    assert sorted(report) == [NORTH, SOUTH]
    north = report[NORTH]
    expected_offers = sum(
        1 for p in raw["products"] if NORTH in p["offers"] and not p["offers"][NORTH]["early"]
    )
    assert north["all"]["offers"] == north["all"]["products"] == expected_offers
    fragrance = north["fragrance"]
    assert fragrance["offers"] == 1
    assert fragrance["name_concentration"] == fragrance["gender_cue"] == 1
    assert fragrance["image"] == fragrance["category_depth_2"] == 1
    assert fragrance["unit_price_ready"] == fragrance["priced"] == fragrance["measured_size"]
    assert fragrance["attribute_concentration"] == 0


def test_a_v2_file_reports_content_counts_as_null_not_zero() -> None:
    north = coverage([_doc(_v2())])[NORTH]["all"]
    assert {name: north[name] for name in CONTENT_COUNTS} == dict.fromkeys(CONTENT_COUNTS)


def test_v3_content_counts() -> None:
    fragrance = coverage([_v3(_v2())])[NORTH]["fragrance"]
    assert {name: fragrance[name] for name in CONTENT_COUNTS} == dict.fromkeys(CONTENT_COUNTS, 1)
    makeup = coverage([_v3(_v2())])[SOUTH]["all"]
    assert makeup["description"] == makeup["notes_cue"] == 0


def test_a_retailer_in_two_files_fails() -> None:
    with pytest.raises(ValueError, match="more than one file"):
        coverage([_doc(_v2()), _doc(_v2())])


def test_main_prints_counts_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "v3.json"
    path.write_text(_v3(_v2()).model_dump_json(by_alias=True), encoding="utf-8")
    assert main(["--allow-test", str(path)]) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    assert report["files"] == [{"schema": "pi.dataset/v3", "dates": ["2026-09-28", "2026-09-30"]}]
    # Aggregates only: no product text, URL or price leaves the script.
    for leak in ("Bloom", "pear", "example.com", "129.00", "fam-1"):
        assert leak not in out
    assert main([]) == 2
