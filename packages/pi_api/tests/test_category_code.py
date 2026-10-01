"""Category codes only: ``category[0]`` keys the tree, the filters and coverage windows.

From #108 a product's ``category`` is ``(code, L1, L2, L3)``, where ``L1..`` is the retailer's
breadcrumb verbatim. Before it, it is ``(code,)``. A crumb must never read as a code: a
"Makeup" crumb under ``lips`` is not a ``makeup`` product and not a child of ``lips``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, write
from pi_api.catalog import CategoryNode, category_tree
from pi_dataset import DatasetV3
from pi_metrics import ProductFilter, view
from v3_fixture import doc

SHORT = (("lips",), ("lips",), ("makeup",))
FULL = (("lips", "MAKEUP", "Lips", "Lipstick"), ("lips", "Makeup", "Lips"), ("makeup",))


def dataset(categories: tuple[tuple[str, ...], ...]) -> DatasetV3:
    """The fixture with its first products' categories replaced and the rest dropped."""
    d: dict[str, Any] = doc()
    d["meta"]["test"] = False
    d["products"] = d["products"][: len(categories)]
    for p, category in zip(d["products"], categories, strict=True):
        p["category"] = list(category)
        p["matches"] = []
    return DatasetV3.model_validate(d)


@pytest.mark.parametrize("categories", [SHORT, FULL], ids=["code", "code+breadcrumb"])
def test_the_tree_lists_codes_without_breadcrumb_children(
    categories: tuple[tuple[str, ...], ...],
) -> None:
    assert category_tree(dataset(categories).products) == (
        CategoryNode(key="lips", count=2),
        CategoryNode(key="makeup", count=1),
    )


@pytest.mark.parametrize("categories", [SHORT, FULL], ids=["code", "code+breadcrumb"])
def test_the_product_filter_matches_the_code_only(
    categories: tuple[tuple[str, ...], ...],
) -> None:
    products = dataset(categories).products
    assert [ProductFilter(categories=("MAKEUP",)).matches(p) for p in products] == [
        False,
        False,
        True,
    ]
    assert not any(ProductFilter(categories=("lipstick",)).matches(p) for p in products)


@pytest.mark.parametrize("categories", [SHORT, FULL], ids=["code", "code+breadcrumb"])
def test_a_not_observed_window_covers_by_code(categories: tuple[tuple[str, ...], ...]) -> None:
    ds = dataset(categories)
    window = next(w for w in ds.not_observed if w.categories)  # categories: ["skincare"]
    window = window.model_copy(update={"categories": ("makeup",)})
    day = window.start
    assert [view.covers(window, p, day) for p in ds.products] == [False, False, True]
    assert not view.covers(window, ds.products[2], date(2000, 1, 1))


def served(tmp_path: Path, categories: tuple[tuple[str, ...], ...]) -> Client:
    write(tmp_path, dataset(categories))
    return make_client(tmp_path)[0]


@pytest.mark.parametrize("categories", [SHORT, FULL], ids=["code", "code+breadcrumb"])
def test_the_api_filters_and_lists_codes_only(
    tmp_path: Path, categories: tuple[tuple[str, ...], ...]
) -> None:
    client = served(tmp_path, categories)

    def get(path: str) -> Any:
        response = client.get(f"/api/v1/{path}", headers=bearer())
        assert response.status_code == 200, response.text
        return response.json()["data"]

    assert [(n["key"], n["count"], n["children"]) for n in get("meta")["categories"]] == [
        ("lips", 2, []),
        ("makeup", 1, []),
    ]
    makeup = get("products?category=Makeup")
    assert [card["id"] for card in makeup["items"]] == ["p03"]
    facets = {f["key"]: f["count"] for f in makeup["facets"]["category"]}
    assert facets == {"lips": 2, "makeup": 1}
