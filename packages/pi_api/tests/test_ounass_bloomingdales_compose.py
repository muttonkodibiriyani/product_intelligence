"""Ounass UAE and Bloomingdale's UAE served beside the beauty file and Faces (API 1.25.0).

The value Infra sets is the Faces value plus two ``source=path`` entries, each per-source export
assigned to its own retailer. The composed view is one AE/beauty view of five retailers. The
golden half checks the Ulta/Sephora answers of the composed view equal the whole-file view, so
the only change is the two new shops themselves. Both are always partial: never a launch, their
stock is the page's own statement, and images only from a host pi-api lists for them (none yet
for Ounass).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, make_client
from pi_api.config import Settings, dataset_entries
from pi_dataset import DatasetV3, dump_dataset, load_any
from sources_fixture import snapshot_doc
from test_faces_compose import (
    BEAUTY,
    FACES,
    FACES_PATH,
    LOCAL,
    SCOPED,
    SEPHORA,
    ULTA,
    answer,
    beauty_doc,
    differences,
    faces_file,
    generationless,
)

OUNASS, BLOOMINGDALES = "ounass_ae", "bloomingdales_ae"
OUNASS_PATH = "datasets/ae/ounass_ae/latest.json"
BLM_PATH = "datasets/ae/bloomingdales_ae/latest.json"
NEW_SHOPS = (OUNASS, BLOOMINGDALES)
VALUE = (
    f"{SEPHORA}={BEAUTY},{ULTA}={BEAUTY},{FACES}={FACES_PATH},"
    f"{OUNASS}={OUNASS_PATH},{BLOOMINGDALES}={BLM_PATH}"
)
PATHS = {FACES: FACES_PATH, OUNASS: OUNASS_PATH, BLOOMINGDALES: BLM_PATH}
BLM_HOST = "prodheadless.atgwasl.com"
BLM_IMAGE = f"https://{BLM_HOST}/on/demandware.static/-/Sites-bloomingdales-master-catalog/a.jpg"
OUNASS_IMAGE = "https://www.ounass.ae/a.jpg"
#: pi-api's image hosts after the deploy: Bloomingdale's added, Ounass absent (host unverified).
IMAGE_HOSTS = {
    SEPHORA: frozenset({"img-product.sephora.me"}),
    ULTA: frozenset({"media.alshaya.com"}),
    FACES: frozenset({"www.faces.ae"}),
    BLOOMINGDALES: frozenset({BLM_HOST}),
}
# Market-wide questions: equal once the new shops' (and Faces') own rows are taken out.
WIDE = ("/api/v1/promotions", "/api/v1/launches", "/api/v1/coverage", "/api/v1/meta")
ADDED = {
    "/api/v1/promotions": {"$.cohort.n", "$.data.total"},
    "/api/v1/launches": {"$.caveats[0].params.count", "$.caveats[0].en", "$.caveats[0].ar"},
    "/api/v1/meta": {"$.data.categories", "$.data.sources"},
}


def shop_file(source: str, dates: list[str], *, stock: str = "in_stock") -> DatasetV3:
    """A one-shop export: partial, the page's own stock, a stated was-price, one image."""
    a, b = f"{source}-1", f"{source}-2"
    d = snapshot_doc({a: (source,), b: (source,)}, dates=dates)
    d["meta"]["retailers"][0]["status"] = "partial"
    first = d["products"][0]
    first["offers"][source]["series"]["regular"] = [
        {"amount": "120.00", "minor": 12000, "currency": "AED"}
    ] * len(dates)
    for p in d["products"]:
        p["offers"][source]["series"]["availability"] = [stock] * len(dates)
    first["image"] = BLM_IMAGE if source == BLOOMINGDALES else OUNASS_IMAGE
    return DatasetV3.model_validate(d)


def install(root: Path, files: Mapping[str, bytes]) -> list[str]:
    for path, body in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return [r.id for r in load_any(files[BEAUTY]).meta.retailers]


def files(dates: list[str], *, stock: str = "in_stock") -> dict[str, bytes]:
    beauty = beauty_doc()
    return {
        BEAUTY: beauty,
        FACES_PATH: dump_dataset(faces_file(dates)),
        OUNASS_PATH: dump_dataset(shop_file(OUNASS, dates, stock=stock)),
        BLM_PATH: dump_dataset(shop_file(BLOOMINGDALES, dates, stock=stock)),
    }


def beauty_dates() -> list[str]:
    return [str(d) for d in load_any(beauty_doc()).meta.dates]


def clients(root: Path, retailers: list[str], with_new: bool = True) -> tuple[Client, Client]:
    """The Faces composition (before) and the five-entry composition (after)."""
    before = dict.fromkeys(retailers, BEAUTY) | {FACES: FACES_PATH}
    after = before | ({OUNASS: OUNASS_PATH, BLOOMINGDALES: BLM_PATH} if with_new else {})
    old, _ = make_client(root, paths=(), assigned=before, image_hosts=IMAGE_HOSTS)
    new, _ = make_client(root, paths=(), assigned=after, image_hosts=IMAGE_HOSTS)
    return old, new


def is_new_shop(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    params = value.get("params")
    named = {value.get("retailer"), value.get("id")}
    return bool(named & set(NEW_SHOPS)) or (
        isinstance(params, dict) and params.get("retailer") in NEW_SHOPS
    )


def without_new(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: without_new(v) for k, v in value.items() if k not in NEW_SHOPS}
    if isinstance(value, list):
        return [without_new(v) for v in value if not is_new_shop(v)]
    return value


def test_the_value_composes_one_ae_beauty_view_of_five_retailers(tmp_path: Path) -> None:
    paths, assigned = dataset_entries(VALUE)
    assert paths == ()
    assert assigned == {SEPHORA: BEAUTY, ULTA: BEAUTY} | PATHS
    Settings.from_env({**LOCAL, "PI_API_DATASETS": VALUE})
    install(tmp_path, files(["2026-09-29", "2026-09-30"]))
    client, source = make_client(tmp_path, paths=paths, assigned=assigned)
    (view,) = source.datasets()
    dataset = source.select("AE", "beauty").dataset
    assert source.select(None, None).dataset is dataset
    assert [r.id for r in dataset.meta.retailers] == [
        BLOOMINGDALES,
        FACES,
        OUNASS,
        SEPHORA,
        ULTA,
    ]
    assert set(view.path.split(",")) == {f"{s}={p}" for s, p in assigned.items()}
    for shop in NEW_SHOPS:
        own = [p for p in dataset.products if set(p.offers) == {shop}]
        assert [p.id for p in own] == [f"{shop}-1", f"{shop}-2"]
        assert all(not p.matches for p in own)  # no cross-file pairs (later ADR)
        coverage = answer(client, f"/api/v1/coverage?retailer={shop}")["data"]["retailers"]
        assert [(r["id"], r["status"], r["productCount"]) for r in coverage] == [
            (shop, "partial", 2)
        ]


def test_every_other_answer_is_unchanged_when_they_share_the_cutoff(tmp_path: Path) -> None:
    dates = beauty_dates()[-2:]
    old, new = clients(tmp_path, install(tmp_path, files(dates)))
    found: dict[str, list[str]] = {}
    for route in SCOPED:
        a, b = (generationless(answer(c, route)) for c in (old, new))
        found[route] = list(differences(a, b))
    for route in WIDE:
        a, b = (without_new(generationless(answer(c, route))) for c in (old, new))
        added = ADDED.get(route, set())
        found[route] = [p for p in differences(a, b) if not any(p.startswith(x) for x in added)]
    assert {route: paths for route, paths in found.items() if paths} == {}


@pytest.mark.parametrize("shop", NEW_SHOPS)
def test_their_items_are_never_launches(tmp_path: Path, shop: str) -> None:
    _, new = clients(tmp_path, install(tmp_path, files(beauty_dates()[1:])))
    assert answer(new, f"/api/v1/launches?retailer={shop}")["data"]["items"] == []


@pytest.mark.parametrize("shop", NEW_SHOPS)
def test_their_was_prices_are_listed_and_the_share_withheld(tmp_path: Path, shop: str) -> None:
    _, new = clients(tmp_path, install(tmp_path, files(beauty_dates())))
    body = answer(new, f"/api/v1/promotions?retailer={shop}")
    assert [i["id"] for i in body["data"]["items"]] == [f"{shop}-1"]
    (row,) = body["data"]["retailers"]
    assert (row["share"], row["reason"]) == (None, "retailer_partial")


@pytest.mark.parametrize("shop", NEW_SHOPS)
def test_an_out_of_stock_page_is_served_out_of_stock(tmp_path: Path, shop: str) -> None:
    _, new = clients(tmp_path, install(tmp_path, files(beauty_dates(), stock="out_of_stock")))
    detail = answer(new, f"/api/v1/products/{shop}-2")["data"]
    (offer,) = [o for o in detail["offers"] if o["retailer"] == shop]
    assert offer["availability"] == "out_of_stock"


def test_bloomingdales_image_served_from_its_host_ounass_image_never(tmp_path: Path) -> None:
    _, new = clients(tmp_path, install(tmp_path, files(beauty_dates())))
    cards = {
        i["id"]: i["image"]
        for i in answer(new, "/api/v1/products?limit=100")["data"]["items"]
        if i["id"].startswith((OUNASS, BLOOMINGDALES))
    }
    assert cards == {
        f"{BLOOMINGDALES}-1": BLM_IMAGE,
        f"{BLOOMINGDALES}-2": None,
        f"{OUNASS}-1": None,  # TODO(ounass image host): no host listed, so never served
        f"{OUNASS}-2": None,
    }
