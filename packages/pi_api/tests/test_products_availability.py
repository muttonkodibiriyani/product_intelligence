"""``GET /products?availability=&unavailableBrands=`` (API 1.23.0): each Insights stock count
links to the listings behind it, on the latest date, one listing at a time."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api_fixture import Client, bearer, make_client, write
from pi_dataset import DatasetV3
from v3_fixture import doc

API = "/api/v1"


def client(tmp_path: Path) -> Client:
    """At shop_a: Fixture Beauty is partly out (p01 in, p03 low, p05 out); Sample Labs is out on
    every observed listing (p02, p04; p06 removed is not observed), so the source reports it
    unavailable. Every shop_b listing is in stock."""
    d: dict[str, Any] = doc()
    d["meta"]["test"] = False
    p04 = next(p for p in d["products"] if p["id"] == "p04")
    p04["offers"]["shop_a"]["series"]["availability"][-1] = "out_of_stock"
    write(tmp_path, DatasetV3.model_validate(d))
    return make_client(tmp_path)[0]


def ids(c: Client, query: str) -> set[str]:
    response = c.get(f"{API}/products?limit=100&{query}", headers=bearer())
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["data"]["items"]}


def test_availability_keeps_listings_in_the_states_asked_for(tmp_path: Path) -> None:
    c = client(tmp_path)
    assert ids(c, "retailer=shop_a&availability=out_of_stock") == {"p02", "p04", "p05"}
    assert ids(c, "retailer=shop_a&availability=in_stock&availability=low_stock") == {"p01", "p03"}
    assert ids(c, "retailer=shop_b&availability=out_of_stock") == set()
    assert ids(c, "availability=low_stock") == {"p03"}  # any context when none is named


def test_unavailable_brands_split_matches_the_insights_counts(tmp_path: Path) -> None:
    c = client(tmp_path)
    out = ids(c, "retailer=shop_a&availability=out_of_stock&unavailableBrands=exclude")
    gone = ids(c, "retailer=shop_a&unavailableBrands=only")
    assert (out, gone) == ({"p05"}, {"p02", "p04"})
    response = c.get(f"{API}/insights?retailers=shop_a,shop_b", headers=bearer())
    assert response.status_code == 200, response.text
    a = next(s for s in response.json()["data"]["stockouts"] if s["retailer"] == "shop_a")
    assert (a["outOfStock"], a["unavailableListings"], a["unavailableBrands"]) == (
        len(out),
        len(gone),
        1,
    )


def test_an_unobserved_state_is_not_a_filter_value(tmp_path: Path) -> None:
    response = client(tmp_path).get(f"{API}/products?availability=removed", headers=bearer())
    assert response.status_code == 422
