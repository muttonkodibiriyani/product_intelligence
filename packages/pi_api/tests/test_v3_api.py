"""The API over a ``pi.dataset/v3`` snapshot with contexts (ADR-0008 step 4b).

``shop_a`` is split into ``shop_a_web`` (online) and ``shop_a_app`` (delivery, at one location),
so a bare ``shop_a`` names no single context. The beauty fixture, one context per retailer,
must never meet ``ambiguous_context``.
"""

from __future__ import annotations

from itertools import permutations
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, served_dataset, write
from metrics_fixture import B
from pi_dataset import DatasetV3
from v3_fixture import APP, APP_PRODUCTS, WEB, offer, profile, size, split_shop_a
from v3_fixture import doc as base_doc

API = "/api/v1"
PLACE = "dxb_marina"


def split_doc() -> dict[str, Any]:
    d = split_shop_a(profile(base_doc(), "food_menu"))
    d["meta"]["test"] = False
    app = next(c for c in d["meta"]["contexts"] if c["id"] == APP)
    app["location"] = {"id": PLACE, "label": {"en": "Dubai Marina"}, "city": "Dubai", "area": None}
    offer(d, "p01", WEB)["size"] = size("50", "ml", "Medium")
    offer(d, "p01", APP)["size"] = size("50", "ml", "M")
    next(p for p in d["products"] if p["id"] == "p01")["attributes"] = {"finish": "Matte"}
    return d


@pytest.fixture
def split(tmp_path: Path) -> Client:
    write(tmp_path, DatasetV3.model_validate(split_doc()))
    return make_client(tmp_path)[0]


@pytest.fixture
def beauty(tmp_path: Path) -> Client:
    write(tmp_path, served_dataset())
    return make_client(tmp_path)[0]


def get(client: Client, path: str, status: int = 200) -> Any:
    response = client.get(f"{API}/{path}", headers=bearer())
    assert response.status_code == status, response.text
    return response.json()


def error(client: Client, path: str) -> str:
    code: str = get(client, path, 422)["error"]["code"]
    return code


# ---------------------------------------------------------------- ambiguous_context


@pytest.mark.parametrize(
    "path",
    [
        "compare?retailers=shop_a,shop_b",
        "index?retailers=shop_b,shop_a",
        "promotions?retailer=shop_a",
        "availability?retailer=shop_a",
        "export/compare?retailers=shop_a,shop_b",
        "products?retailer=shop_a&retailer=shop_b&sort=gap",
    ],
)
def test_a_retailer_with_several_contexts_is_ambiguous(split: Client, path: str) -> None:
    doc = get(split, path, 422)
    assert doc["error"]["code"] == "ambiguous_context"
    assert f"{WEB}, {APP}" in doc["error"]["message"]


@pytest.mark.parametrize(
    "path",
    [
        f"compare?retailers={WEB},shop_b",
        f"index?retailers=shop_b,{APP}",
        f"promotions?retailer={APP}",
        f"availability?retailer={WEB}",
        "coverage?retailer=shop_a",  # coverage is per retailer, listing its contexts
    ],
)
def test_a_context_id_is_accepted(split: Client, path: str) -> None:
    get(split, path)


def test_an_unknown_id_stays_invalid_query(split: Client) -> None:
    assert error(split, "compare?retailers=shop_z,shop_b") == "invalid_query"


def test_beauty_never_meets_ambiguous_context(beauty: Client) -> None:
    """Coordinator condition for 4b: today's beauty data has one context per retailer."""
    shops = [c["id"] for c in get(beauty, "meta")["data"]["contexts"]]
    assert shops == [r["id"] for r in get(beauty, "meta")["data"]["retailers"]]
    for base, other in permutations(shops, 2):
        for path in (
            f"compare?retailers={base},{other}",
            f"index?retailers={base},{other}",
            f"assortment-gaps?missingAt={base}&presentAt={other}",
            f"products?retailer={base}&retailer={other}&sort=gap",
        ):
            assert get(beauty, path)["status"] in {"ok", "not_enough_data", "unavailable"}
    for shop in shops:
        for path in (f"promotions?retailer={shop}", f"availability?retailer={shop}"):
            get(beauty, path)


# ---------------------------------------------------------------- meta and products


def test_meta_lists_contexts_profile_and_attributes(split: Client) -> None:
    data = get(split, "meta")["data"]
    contexts = {c["id"]: c for c in data["contexts"]}
    assert contexts[APP]["retailer"] == contexts[WEB]["retailer"] == "shop_a"
    assert contexts[APP]["location"]["id"] == PLACE
    assert data["profile"]["name"] == "food_menu"
    assert "finish" in {a["key"] for a in data["attributeSet"] if a["facet"]}


def ids(doc: Any) -> list[str]:
    return [item["id"] for item in doc["data"]["items"]]


def test_a_context_id_filters_like_a_retailer(split: Client) -> None:
    by_context = get(split, f"products?retailer={APP}&limit=100")
    assert set(ids(by_context)) <= set(APP_PRODUCTS)
    assert len(ids(get(split, "products?retailer=shop_a&limit=100"))) >= len(ids(by_context))


@pytest.mark.parametrize("query", ["channel=delivery", f"location={PLACE}"])
def test_channel_and_location_narrow_the_offers_shown(split: Client, query: str) -> None:
    doc = get(split, f"products?{query}&limit=100")
    assert set(ids(doc)) <= set(APP_PRODUCTS)
    assert ids(doc)
    assert all(set(item["prices"]) == {APP} for item in doc["data"]["items"])
    retailer_facet = {f["key"]: f["count"] for f in doc["data"]["facets"]["retailer"]}
    assert set(retailer_facet) == {"shop_a"}


def test_a_retailer_facet_counts_a_product_once_across_contexts(split: Client) -> None:
    doc = get(split, "products?limit=100")
    facet = {f["key"]: f["count"] for f in doc["data"]["facets"]["retailer"]}
    assert set(facet) == {r["id"] for r in get(split, "meta")["data"]["retailers"]} & set(facet)
    assert facet["shop_a"] == len(ids(get(split, "products?retailer=shop_a&limit=100")))


def test_attr_filters_on_a_declared_facet(split: Client) -> None:
    assert ids(get(split, "products?attr=finish:matte")) == ["p01"]
    assert ids(get(split, "products?attr=finish:matte&attr=finish:gloss")) == ["p01"]
    assert ids(get(split, "products?attr=finish:matte&attr=concentration:edp")) == []


@pytest.mark.parametrize(
    "query",
    [
        "attr=colour:red",  # not declared
        "attr=finish",  # no value
        "attr=finish:matte%0D",  # a control character in the value
        "attr=finish:a%0Ab",
        "attr=finish:%C2%85",  # C1 NEL
        "attr=finish:a%E2%80%A8b",  # U+2028 line separator
        "attr=finish:a%E2%80%A9b",  # U+2029 paragraph separator
        "&".join(["attr=finish:x"] * 26),
        "location=" + "x" * 60,
        "channel=teleport",
    ],
)
def test_bad_v3_filters_are_422(split: Client, query: str) -> None:
    assert error(split, f"products?{query}") in {"invalid_request", "invalid_query"}
    assert "x" * 50 not in get(split, f"products?{query}", 422)["error"]["message"]


def test_two_unresolved_retailers_give_no_gap_but_still_filter(split: Client) -> None:
    doc = get(split, "products?retailer=shop_a&retailer=shop_b&limit=100")
    assert ids(doc)
    assert all(item["gap"] is None for item in doc["data"]["items"])


def test_a_context_pair_gap_carries_its_size_labels(split: Client) -> None:
    doc = get(split, f"products?retailer={WEB}&retailer={APP}&limit=100")
    gaps = {item["id"]: item["gap"] for item in doc["data"]["items"]}
    assert gaps["p01"]["base"] == WEB
    assert gaps["p01"]["sizeLabels"] == ["Medium", "M"]
    p01 = next(item for item in doc["data"]["items"] if item["id"] == "p01")
    assert p01["size"] == {"value": "50", "unit": "ml"}
    assert p01["sizeLabel"] in {"Medium", "M"}
    assert p01["sizeSystem"] is None


# ---------------------------------------------------------------- detail and history


def test_detail_has_one_offer_view_per_context_and_context_pairs(split: Client) -> None:
    data = get(split, "products/p01")["data"]
    offers = {o["context"]: o for o in data["offers"]}
    assert offers[APP]["retailer"] == offers[WEB]["retailer"] == "shop_a"
    assert (offers[APP]["channel"], offers[APP]["location"]) == ("delivery", PLACE)
    assert (offers[WEB]["channel"], offers[WEB]["location"]) == ("online", None)
    assert (offers[APP]["sizeLabel"], offers[APP]["sizeSystem"]) == ("M", None)
    pairs = {(p["base"], p["other"]): p for p in data["pairs"]}
    assert pairs[(APP, WEB)]["sizeLabels"] == ["M", "Medium"]
    assert pairs[(APP, WEB)]["gap"] is not None
    assert (APP, B) in pairs


def test_history_is_keyed_by_context(split: Client) -> None:
    series = get(split, "products/p01/history")["data"]["series"]
    assert {APP, WEB} <= set(series)
    assert "shop_a" not in series


def faceted_doc() -> dict[str, Any]:
    d = split_doc()
    attrs = {
        "p01": {"finish": "Matte", "concentration": "EDP"},
        "p02": {"finish": "matte", "shadeFamilies": ["Nude"]},
        "p03": {"finish": "Gloss", "shadeFamilies": ["Red", "red", "Nude"]},
    }
    for product in d["products"]:
        product["attributes"] = attrs.get(product["id"], {})
    return d


@pytest.fixture
def faceted(tmp_path: Path) -> Client:
    write(tmp_path, DatasetV3.model_validate(faceted_doc()))
    return make_client(tmp_path)[0]


def attr_facets(client: Client, query: str = "") -> dict[str, dict[str, int]]:
    facets = get(client, f"products?{query}")["data"]["facets"]["attributes"]
    return {k: {f["key"]: f["count"] for f in v} for k, v in facets.items()}


def test_attribute_facets_count_products_per_folded_value(faceted: Client) -> None:
    facets = attr_facets(faceted)
    assert list(facets) == ["finish", "concentration", "shadeFamilies"]  # attributeSet order
    assert facets["finish"] == {"Gloss": 1, "Matte": 2}  # "matte" folds into the least raw form
    assert facets["concentration"] == {"EDP": 1}
    assert facets["shadeFamilies"] == {"Nude": 2, "Red": 1}  # a list counts a product once


def test_an_attribute_facet_drops_only_its_own_filter(faceted: Client) -> None:
    facets = attr_facets(faceted, "attr=finish:matte")
    assert facets["finish"] == {"Gloss": 1, "Matte": 2}
    assert facets["concentration"] == {"EDP": 1}
    assert facets["shadeFamilies"] == {"Nude": 1}
    assert attr_facets(faceted, "attr=concentration:edp")["finish"] == {"Matte": 1}
    assert attr_facets(faceted, "brand=no-such-brand")["finish"] == {}


def test_a_facet_value_round_trips_as_a_filter(faceted: Client) -> None:
    for key, values in attr_facets(faceted).items():
        for value, count in values.items():
            assert len(ids(get(faceted, f"products?attr={key}:{value}&limit=100"))) == count


def test_beauty_lists_every_facet_attribute(beauty: Client) -> None:
    facets = get(beauty, "products")["data"]["facets"]["attributes"]
    keys = [a["key"] for a in get(beauty, "meta")["data"]["attributeSet"] if a["facet"]]
    assert list(facets) == keys
