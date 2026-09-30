import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_match import Bucket, ProductRecord, brand_overlap, match, name_score, prepare, score_pair
from pi_match.cli import load_jsonl, main
from pi_match.report import precision_sample

FIXTURES = Path(__file__).parent / "fixtures"
LEFT = load_jsonl(FIXTURES / "left.jsonl")
RIGHT = load_jsonl(FIXTURES / "right.jsonl")


def rec(key: str, name: str, **kw: object) -> ProductRecord:
    fields: dict[str, object] = {"source": "s", "source_key": key, "brand": "Brand", "name": name}
    fields.update(kw)
    return ProductRecord.model_validate(fields)


def test_fixture_pairs_and_buckets() -> None:
    pairs = {p.left_key: (p.right_key, p.bucket) for p in match(LEFT, RIGHT)}
    assert pairs == {
        "U1": ("S1", Bucket.EXACT),  # same name, size and shade code across spellings
        "U2": ("S3", Bucket.EXACT),  # YSL Beauty == Yves Saint Laurent; 50 ml EDP, not 90 ml
        "U4": ("S4", Bucket.CANDIDATE),  # renamed product line: needs review
        "U7": ("S7", Bucket.EXACT),  # GTIN-12 == GTIN-13 after padding
        "U8": ("S8", Bucket.CANDIDATE),  # different shade: family only
    }
    # U3 (EDT) never pairs with an EDP; U5 (mini) never with the full size; U6 has no brand.


def test_reasons_and_unit_price_gap() -> None:
    by_left = {p.left_key: p for p in match(LEFT, RIGHT)}
    u1 = by_left["U1"]
    assert "size_same" in u1.reasons
    assert "shade_same" in u1.reasons
    assert u1.price_basis == "unit"
    assert u1.left_unit_price is not None
    assert u1.left_unit_price.unit == "ml"
    assert u1.price_gap_pct == Decimal("4.65")
    assert "gtin_equal" in by_left["U7"].reasons
    assert "family_only" in by_left["U8"].reasons


def test_brand_overlap() -> None:
    overlap = brand_overlap(LEFT, RIGHT)
    assert "ulta beauty collection" in overlap.only_left
    assert "sephora collection" in overlap.only_right
    assert {"estee lauder", "yves saint laurent", "nars", "fenty beauty"} <= set(overlap.both)
    assert overlap.left_brand_count == len(overlap.both) + len(overlap.only_left)


def test_different_valid_gtins_never_match() -> None:
    left = prepare(rec("a", "Same Name Cream 50 ml", gtin="4006381333931"))
    right = prepare(rec("b", "Same Name Cream 50 ml", gtin="020714919443"))
    assert score_pair(left, right) is None


def test_size_differs_is_family_only() -> None:
    left = prepare(rec("a", "Hydra Cream 50 ml"))
    right = prepare(rec("b", "Hydra Cream 100 ml"))
    result = score_pair(left, right)
    assert result is not None
    assert result[0] is Bucket.CANDIDATE
    assert "family_only" in result[2]


def test_unknown_size_is_probable_not_exact() -> None:
    result = score_pair(prepare(rec("a", "Hydra Cream 50 ml")), prepare(rec("b", "Hydra Cream")))
    assert result is not None
    assert result[0] is Bucket.PROBABLE


def test_shade_on_one_side_only_is_not_exact() -> None:
    left = prepare(rec("a", "Skin Tint 30 ml", shade="N12"))
    right = prepare(rec("b", "Skin Tint 30 ml"))
    result = score_pair(left, right)
    assert result is not None
    assert result[0] is Bucket.PROBABLE


def test_weak_names_are_dropped() -> None:
    assert score_pair(prepare(rec("a", "Hydra Cream")), prepare(rec("b", "Lip Liner"))) is None


def test_one_to_one_assignment_prefers_the_better_pair() -> None:
    left = [rec("a", "Hydra Cream 50 ml"), rec("b", "Hydra Cream Rich 50 ml")]
    right = [rec("x", "Hydra Cream 50 ml")]
    (pair,) = match(left, right)
    assert (pair.left_key, pair.bucket) == ("a", Bucket.EXACT)


def test_currency_mismatch_is_not_compared() -> None:
    left = [rec("a", "Hydra Cream 50 ml", price="100", currency="AED")]
    right = [rec("x", "Hydra Cream 50 ml", price="30", currency="SAR")]
    (pair,) = match(left, right)
    assert pair.price_gap_pct is None
    assert pair.price_basis is None
    assert pair.currency is None


def test_item_price_gap_when_size_unknown() -> None:
    left = [rec("a", "Hydra Cream", price="100", currency="AED")]
    right = [rec("x", "Hydra Cream", price="110", currency="AED")]
    (pair,) = match(left, right)
    assert (pair.price_basis, pair.price_gap_pct) == ("item", Decimal("10.00"))
    assert pair.left_unit_price is None


def test_missing_price_is_not_compared() -> None:
    (pair,) = match([rec("a", "Hydra Cream", currency="AED")], [rec("x", "Hydra Cream")])
    assert pair.price_gap_pct is None


@given(st.lists(st.sampled_from(["hydra", "cream", "rich", "night", "lip", "gloss"]), max_size=5))
def test_name_score_bounds_and_identity(words: list[str]) -> None:
    tokens = frozenset(words)
    assert Decimal(0) <= name_score(tokens, frozenset({"hydra", "cream"})) <= Decimal(1)
    if tokens:
        assert name_score(tokens, tokens) == Decimal(1)


def test_precision_sample_round_robin_and_capped() -> None:
    pairs = match(LEFT, RIGHT)
    sample = precision_sample(pairs, size=3)
    assert [p.bucket for p in sample] == [Bucket.EXACT, Bucket.CANDIDATE, Bucket.EXACT]
    assert len(precision_sample(pairs)) == len(pairs)  # fewer than 50 pairs: all of them


def test_cli_is_deterministic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--left", str(FIXTURES / "left.jsonl"), "--right", str(FIXTURES / "right.jsonl")]
    for run in ("a", "b"):
        assert main([*args, "--out", str(tmp_path / run), "--cutoff", "2026-09-30"]) == 0
    for name in ("matches.json", "brand_overlap.json", "summary.json", "precision_sample.csv"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    summary = json.loads((tmp_path / "a" / "summary.json").read_text())
    assert summary["pairs"] == {"exact": 3, "probable": 0, "candidate": 2}
    assert summary["meta"]["cutoff"] == "2026-09-30"
    rows = list(csv.DictReader((tmp_path / "a" / "precision_sample.csv").open()))
    assert len(rows) == 5
    assert all(row["label"] == "" for row in rows)
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["left_products"] == 8


def test_cli_rejects_a_bad_line(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"source": "s"}\n\n', encoding="utf-8")
    with pytest.raises(SystemExit, match=r"bad\.jsonl:1"):
        load_jsonl(bad)
