"""End to end on synthetic datasets: competitors are similar, never the same product."""

from decimal import Decimal

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from pi_dataset import Dataset
from pi_similar.build import build_similar
from pi_similar.model import SimilarFile, dump_similar
from pi_similar.text import unit_rows
from similar_fixtures import NORTH, SOUTH, Off, Prod, WordsEmbedder, dataset

PRICES = ["40.00", "60.00", "80.00", "100.00", "120.00", "140.00", "160.00"]


def _catalogue() -> Dataset:
    north = [
        Prod(f"n{i}", f"Brand{i} Rose Eau de Parfum for Women", ["Fragrance", "Women"],
             {NORTH: Off(PRICES[i])}, brand=f"Brand{i}")
        for i in range(len(PRICES))
    ]  # fmt: skip
    south = [
        Prod(f"s{i}", f"House{i} Rose Eau de Parfum for Women", ["Fragrance", "Women"],
             {SOUTH: Off(PRICES[i])}, brand=f"House{i}")
        for i in range(len(PRICES))
    ]  # fmt: skip
    others = [
        Prod("s-edt", "House9 Rose Eau de Toilette for Women", ["Fragrance"], {SOUTH: Off()}),
        Prod("s-men", "House9 Rose Eau de Parfum for Men", ["Fragrance"], {SOUTH: Off()}),
        Prod("s-mini", "House9 Rose Eau de Parfum Mini for Women", ["Fragrance"], {SOUTH: Off()}),
        Prod("s-lip", "House9 Rose Lipstick", ["Makeup", "Lips"],
             {SOUTH: Off("50.00", ("3", "g"))}),
        Prod("s-gift", "House9 Rose Eau de Parfum for Women", ["Gifts"], {SOUTH: Off()}),
        Prod("both", "Shared Rose Eau de Parfum for Women", ["Fragrance"],
             {NORTH: Off("100.00"), SOUTH: Off("100.00")}, brand="Shared"),
    ]  # fmt: skip
    return dataset([*north, *south, *others])


def _build(doc: Dataset, **options: object) -> SimilarFile:
    return build_similar(
        [doc],
        WordsEmbedder(),
        scope="ae/beauty",
        generated_at="2026-10-06T00:00:00Z",
        **options,  # type: ignore[arg-type]
    )


def test_competitors_are_at_other_retailers_and_never_the_same_product() -> None:
    found = _build(_catalogue())
    by_key = {(s.product, s.retailer): s for s in found.similar}
    n0 = by_key[("n0", NORTH)]
    ids = [c.product for c in n0.competitors]
    assert len(ids) == 5
    assert {c.retailer for c in n0.competitors} == {SOUTH}
    # EDT, men, mini, makeup and an unknown department never compete with a women's EDP
    assert not {"s-edt", "s-men", "s-mini", "s-lip", "s-gift"} & set(ids)
    both = by_key[("both", NORTH)]
    assert "both" not in [c.product for c in both.competitors]  # never its own competitor
    best = n0.competitors[0]
    assert best.signals.price == "1.0000"
    assert best.signals.image is None  # image is phase 2: absent, never imputed
    assert "other_brand" in best.reasons
    assert found.kind == "similar_not_same_product"
    assert found.meta.models == {"text": "test/words@1"}


def test_identity_pairs_are_excluded() -> None:
    doc = _catalogue()
    plain = {c.product for c in _build(doc).similar[0].competitors}
    first = _build(doc).similar[0].product
    excluded = next(iter(plain))
    found = _build(doc, identity={frozenset((first, excluded))})
    assert excluded not in {c.product for c in found.similar[0].competitors}


def test_k_bounds_each_other_retailer_and_a_run_is_deterministic() -> None:
    doc = _catalogue()
    assert all(len(s.competitors) <= 2 for s in _build(doc, k=2).similar)
    assert dump_similar(_build(doc)) == dump_similar(_build(doc))


def test_departments_never_cross_and_items_without_one_are_left_out() -> None:
    found = _build(_catalogue())
    listed = {s.product for s in found.similar}
    assert "s-gift" not in listed
    assert "s-lip" not in listed  # a lipstick with nothing to compete with at the other side


def test_an_empty_catalogue_gives_an_empty_file() -> None:
    doc = dataset([Prod("g", "Gift Card", ["Gifts"], {NORTH: Off()})])
    assert _build(doc).similar == ()


@settings(max_examples=25, deadline=None)
@given(salt=st.text(max_size=4), k=st.integers(1, 6), preselect=st.integers(1, 8))
def test_invariants_hold_for_any_text_model(salt: str, k: int, preselect: int) -> None:
    found = build_similar(
        [_catalogue()],
        WordsEmbedder(salt),
        scope="ae/beauty",
        generated_at="2026-10-06T00:00:00Z",
        k=k,
        preselect=preselect,
    )
    for entry in found.similar:
        assert len(entry.competitors) <= min(k, preselect)
        for c in entry.competitors:
            assert c.retailer != entry.retailer
            assert c.product != entry.product
            assert Decimal(0) <= Decimal(c.score) <= Decimal(1)
            assert c.signals.image is None


def test_unit_rows_keeps_zero_rows_and_scales_tiny_ones() -> None:
    rows = unit_rows(np.array([[0.0, 0.0], [1.46e-22, 0.0]], dtype=np.float32))
    assert rows[0].tolist() == [0.0, 0.0]
    assert np.isclose(np.linalg.norm(rows[1]), 1.0)
