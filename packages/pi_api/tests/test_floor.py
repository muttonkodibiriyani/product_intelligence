"""The read-time price floor (``pi_api.floor``, API 1.7.1): 0.01 or less is withheld as invalid.

The fixture serves ``shop_a`` (collected, Sephora-like) beside ``ulta_ae`` (imported). ``p01``'s
latest ``shop_a`` price and ``p02``'s latest Ulta price are 0.01, and one of ``p03``'s Ulta
regular prices is 0.01. Every response must read them exactly as not observed: the same figures
as a file where those values are null, plus ``priceFlag`` and ``invalid_price_excluded``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from api_fixture import Client, bearer, make_client, write
from pi_api import source as source_module
from pi_api.floor import FLOOR, FloorView, PriceFlag, caveats, floor_view
from pi_dataset import DatasetV3
from pi_metrics import CaveatCode
from v3_fixture import doc, load, offer

API = "/api/v1"
ULTA = "ulta_ae"
SHOP = "shop_a"
LOW = {"amount": "0.01", "minor": 1, "currency": "AED"}
ZERO = {"amount": "0.00", "minor": 0, "currency": "AED"}
#: (product, context, series, index) of each 0.01 in the fixture.
PLANTED = (("p01", SHOP, "price", -1), ("p02", ULTA, "price", -1), ("p03", ULTA, "regular", 0))

#: Every endpoint that shows or aggregates prices, as the app's clients call them.
PRICED = (
    "/products?limit=50",
    "/products?limit=50&sort=price_asc",
    f"/products?retailer={SHOP}&retailer={ULTA}&sort=gap&limit=50",
    "/products/p01",
    "/products/p02",
    "/products/p03",
    "/products/p01/history",
    "/products/p02/history",
    f"/compare?retailers={SHOP},{ULTA}",
    f"/compare?retailers={SHOP},{ULTA}&groupBy=brand",
    f"/compare?retailers={SHOP},{ULTA}&date=2026-09-29",
    f"/index?retailers={SHOP},{ULTA}",
    "/promotions",
    f"/summary?retailer={SHOP}",
    f"/summary?retailer={ULTA}",
)
#: The rest, for the walk that no response anywhere shows a price at or below the floor.
OTHERS = (
    "/meta",
    "/coverage",
    "/availability",
    "/launches",
    "/reviews-summary",
    f"/assortment-gaps?missingAt={ULTA}&presentAt={SHOP}",
    "/matches?limit=50",
)
EXPORTS = (
    "/export/products?format=jsonl",
    f"/export/compare?retailers={SHOP},{ULTA}&format=jsonl",
    f"/export/index?retailers={SHOP},{ULTA}&format=jsonl",
    "/export/promotions?format=jsonl",
)


def base_doc() -> dict[str, Any]:
    d: dict[str, Any] = json.loads(json.dumps(doc()).replace('"shop_b"', f'"{ULTA}"'))
    d["meta"]["test"] = False
    for product in d["products"]:
        for edge in product["matches"]:
            if edge["a"] > edge["b"]:  # edges are ordered a < b
                edge["a"], edge["b"] = edge["b"], edge["a"]
    return d


def planted(value: dict[str, Any] | None) -> dict[str, Any]:
    d = base_doc()
    for product, context, series, index in PLANTED:
        offer(d, product, context)["series"][series][index] = value
    return d


def serve(tmp_path: Path, d: dict[str, Any]) -> Client:
    write(tmp_path, load(d))
    return make_client(tmp_path)[0]


def get(client: Client, path: str) -> Any:
    response = client.get(f"{API}{path}", headers=bearer())
    assert response.status_code == 200, (path, response.text)
    if "format=jsonl" in path:
        return [json.loads(line) for line in response.text.splitlines()]
    return response.json()


def without_floor(body: Any) -> Any:
    """``body`` without what the floor adds (flags and its caveat) and without the file's
    generation, which differs between any two files."""
    if isinstance(body, dict):
        return {
            k: without_floor(v)
            for k, v in body.items()
            if k not in {"priceFlag", "priceFlags", "generation"}
        } | (
            {"caveats": [c for c in body["caveats"] if c.get("code") != "invalid_price_excluded"]}
            if isinstance(body.get("caveats"), list)
            else {}
        )
    if isinstance(body, list):
        return [without_floor(v) for v in body]
    return body


def floor_caveats(body: Any) -> dict[str, str]:
    return {
        c["params"]["retailer"]: c["params"]["count"]
        for c in body["caveats"]
        if c["code"] == "invalid_price_excluded"
    }


def money_at_or_below_floor(body: Any, at: str = "") -> list[str]:
    """Paths of every price in ``body`` at or below the floor. A ``gap`` is a difference of two
    prices, not a price: it can be zero or negative."""
    found: list[str] = []
    if isinstance(body, dict):
        amount = body.get("amount") if "currency" in body else None
        if amount is not None and Decimal(amount) <= FLOOR:
            found.append(at)
        for k, v in body.items():
            if k != "gap":
                found += money_at_or_below_floor(v, f"{at}.{k}")
    elif isinstance(body, list):
        for i, v in enumerate(body):
            found += money_at_or_below_floor(v, f"{at}[{i}]")
    return found


# ---------------------------------------------------------------- the view


def test_a_dataset_without_a_low_price_is_served_as_the_same_object() -> None:
    ds = load(base_doc())
    assert floor_view(ds) == (ds, FloorView())


def test_the_view_nulls_each_low_value_and_counts_offers_per_retailer() -> None:
    served, view = floor_view(load(planted(LOW)))
    assert served == load(planted(None))
    assert {(f.retailer, f.offers) for f in view.floored} == {(SHOP, 1), (ULTA, 2)}
    # Only a latest-date price flags the offer; p03's withheld regular is counted, not flagged.
    assert view.flagged == {("p01", SHOP), ("p02", ULTA)}


def test_a_cent_above_the_floor_is_a_price() -> None:
    d = base_doc()
    offer(d, "p01", SHOP)["series"]["price"][-1] = {"amount": "0.02", "minor": 2, "currency": "AED"}
    assert floor_view(load(d))[1] == FloorView()


def test_caveats_are_scoped_to_priced_endpoints_and_the_retailers_involved() -> None:
    _, view = floor_view(load(planted(LOW)))

    def owed(endpoint: str, selected: frozenset[str]) -> set[str]:
        return {c.params["retailer"] for c in caveats(view, endpoint, selected)}

    assert owed("summary", frozenset()) == {SHOP, ULTA}
    assert owed("compare", frozenset({SHOP})) == {SHOP}
    assert owed("export_products", frozenset({ULTA})) == {ULTA}
    assert owed("coverage", frozenset()) == set()
    assert owed("launches", frozenset()) == set()
    assert {c.code for c in caveats(view, "summary", frozenset())} == {
        CaveatCode.INVALID_PRICE_EXCLUDED
    }


# ---------------------------------------------------------------- 0.00 never reaches the API


@pytest.mark.parametrize("context", [SHOP, ULTA])
@pytest.mark.parametrize("series", ["price", "regular"])
def test_a_zero_price_on_either_retailer_is_refused_by_the_dataset_contract(
    context: str, series: str
) -> None:
    d = base_doc()
    offer(d, "p03", context)["series"][series][-1] = ZERO
    with pytest.raises(ValidationError):
        DatasetV3.model_validate(d)


@pytest.mark.parametrize("context", [SHOP, ULTA])
def test_a_file_with_a_zero_price_is_never_served(tmp_path: Path, context: str) -> None:
    d = base_doc()
    offer(d, "p03", context)["series"]["price"][-1] = ZERO
    target = tmp_path / "datasets/uae/latest.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(d))
    client, _ = make_client(tmp_path)
    response = client.get(f"{API}/products/p03", headers=bearer())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "data_unavailable"


# ---------------------------------------------------------------- 0.01 on both retailers


@pytest.mark.parametrize("path", PRICED + EXPORTS)
def test_every_priced_response_reads_a_low_value_as_not_observed(tmp_path: Path, path: str) -> None:
    """Medians, means, histograms, ladders, brand prices, promotion depths, gaps, the index and
    exports: each equals the response for a file with those values null."""
    floored = get(serve(tmp_path / "low", planted(LOW)), path)
    nulled = get(serve(tmp_path / "null", planted(None)), path)
    assert without_floor(floored) == without_floor(nulled)


@pytest.mark.parametrize(
    "path",
    [
        f"/summary?retailer={SHOP}",
        f"/summary?retailer={ULTA}",
        f"/compare?retailers={SHOP},{ULTA}",
        f"/index?retailers={SHOP},{ULTA}",
        "/promotions",
        "/products/p01",
        "/products/p01/history",
    ],
)
def test_without_the_floor_the_low_value_would_be_measured(
    tmp_path: Path, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The equality above is not vacuous: unfloored, 0.01 changes each of these responses."""
    floored = get(serve(tmp_path / "low", planted(LOW)), path)
    monkeypatch.setattr(source_module, "floor_view", lambda ds: (ds, FloorView()))
    raw = get(serve(tmp_path / "raw", planted(LOW)), path)
    assert without_floor(raw) != without_floor(floored)


@pytest.mark.parametrize("path", PRICED + OTHERS + EXPORTS)
def test_no_response_anywhere_shows_a_price_at_or_below_the_floor(
    tmp_path: Path, path: str
) -> None:
    assert money_at_or_below_floor(get(serve(tmp_path, planted(LOW)), path)) == []


def test_a_product_flags_its_withheld_offer_and_owes_both_retailers_caveats(
    tmp_path: Path,
) -> None:
    client = serve(tmp_path, planted(LOW))
    body = get(client, "/products/p01")
    offers = {o["retailer"]: o for o in body["data"]["offers"]}
    assert offers[SHOP]["price"] is None
    assert offers[SHOP]["priceFlag"] == PriceFlag.INVALID_LOW
    assert offers[ULTA]["price"] is not None
    assert offers[ULTA]["priceFlag"] is None
    assert floor_caveats(body) == {SHOP: "1", ULTA: "2"}
    ulta = get(client, "/products/p02")["data"]["offers"]
    assert {o["retailer"]: o["priceFlag"] for o in ulta} == {SHOP: None, ULTA: "invalid_low"}


def test_cards_flag_withheld_prices_by_context(tmp_path: Path) -> None:
    cards = {
        c["id"]: c
        for c in get(serve(tmp_path, planted(LOW)), "/products?limit=50")["data"]["items"]
    }
    assert cards["p01"]["priceFlags"] == {SHOP: "invalid_low"}
    assert cards["p02"]["priceFlags"] == {ULTA: "invalid_low"}
    assert cards["p03"]["priceFlags"] == {}  # a withheld regular price only: nothing shown null


def test_the_caveat_names_only_the_retailers_a_request_involves(tmp_path: Path) -> None:
    client = serve(tmp_path, planted(LOW))
    assert floor_caveats(get(client, f"/summary?retailer={SHOP}")) == {SHOP: "1"}
    assert floor_caveats(get(client, f"/summary?retailer={ULTA}")) == {ULTA: "2"}
    assert floor_caveats(get(client, "/coverage")) == {}
    text = next(
        c
        for c in get(client, f"/summary?retailer={ULTA}")["caveats"]
        if c["code"] == "invalid_price_excluded"
    )["en"]
    assert text.startswith(f"2 {ULTA} items had a price of 0.01 or less")


def test_a_file_without_low_values_is_served_unchanged(tmp_path: Path) -> None:
    body = get(serve(tmp_path, base_doc()), "/products/p01")
    assert floor_caveats(body) == {}
    assert {o["priceFlag"] for o in body["data"]["offers"]} == {None}
