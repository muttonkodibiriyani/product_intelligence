"""Committed contract artifacts (drift guards) and the hosting rewrite rules.

Regenerate after an intended change: ``make openapi``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from api_fixture import DATASET_PATH, bearer, make_client, served_dataset, write
from pi_api.analytics import MatchPage
from pi_api.app import PREFIX
from pi_api.catalog import AdminProductDetail, History, MetaView, ProductDetail, ProductPage
from pi_api.contract import main, openapi, openapi_text
from pi_api.wire import Envelope
from pi_metrics.assortment import AssortmentGaps
from pi_metrics.availability import Availability
from pi_metrics.compare import Comparison
from pi_metrics.coverage import Coverage
from pi_metrics.index import PriceIndex
from pi_metrics.launches import Launches
from pi_metrics.promotions import Promotions
from pi_metrics.reviews import ReviewsSummary

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "docs" / "contracts"
GOLDEN = CONTRACTS / "golden" / "pi-api"
REGENERATE = os.environ.get("PI_API_REGENERATE") == "1"
#: A fixed mtime so the dataset generation (and every cursor) is the same on every run.
GENERATION_NS = 1_790_000_000_000_000_000

GOLDENS: dict[str, tuple[str, type[BaseModel], dict[str, Any]]] = {
    "meta": ("/meta", Envelope[MetaView], {}),
    "products": ("/products?limit=3&sort=price_asc", Envelope[ProductPage], {}),
    "products-filtered": (
        "/products?brand=Sample%20Labs&retailer=shop_c",
        Envelope[ProductPage],
        {},
    ),
    "product": ("/products/p01", Envelope[ProductDetail], {}),
    "admin-product": ("/admin/products/p01", Envelope[AdminProductDetail], {"role": "admin"}),
    "history": ("/products/p05/history", Envelope[History], {}),
    "coverage": ("/coverage", Envelope[Coverage], {}),
    "products-gap": (
        "/products?retailer=shop_a&retailer=shop_b&sort=gap&limit=3",
        Envelope[ProductPage],
        {},
    ),
    "compare": ("/compare?retailers=shop_a,shop_b&groupBy=brand", Envelope[Comparison], {}),
    "compare-blocked": ("/compare?retailers=shop_a,shop_d", Envelope[Comparison], {}),
    "index": ("/index?retailers=shop_a,shop_b", Envelope[PriceIndex], {}),
    "promotions": ("/promotions?minPct=10", Envelope[Promotions], {}),
    "assortment-gaps": (
        "/assortment-gaps?missingAt=shop_b&presentAt=shop_a",
        Envelope[AssortmentGaps],
        {},
    ),
    "availability": ("/availability", Envelope[Availability], {}),
    "launches": ("/launches", Envelope[Launches], {}),
    "reviews-summary": ("/reviews-summary", Envelope[ReviewsSummary], {}),
    "matches": ("/matches?limit=3", Envelope[MatchPage], {}),
    "admin-matches": ("/matches?reviewState=proposed", Envelope[MatchPage], {"role": "admin"}),
    "error-stale-cursor": ("", BaseModel, {}),
}


def test_committed_openapi_matches_the_app() -> None:
    committed = (CONTRACTS / "pi-api.openapi.json").read_text(encoding="utf-8")
    if REGENERATE:
        (CONTRACTS / "pi-api.openapi.json").write_text(openapi_text(), encoding="utf-8")
        return
    assert committed == openapi_text(), "regenerate: make openapi"


def test_no_json_numbers_for_money_or_percentages() -> None:
    """Decimals are strings on the wire; the only numeric type is integer (counts, minor)."""
    assert '"number"' not in openapi_text()


def test_every_route_is_get_and_bearer_protected() -> None:
    spec = openapi()
    assert spec["security"] == [{"firebase": []}]
    for path, operations in spec["paths"].items():
        assert path.startswith(PREFIX)
        assert set(operations) == {"get"}
        responses = operations["get"]["responses"]
        assert {"401", "403", "429", "503"} <= set(responses)
        assert "HTTPValidationError" not in json.dumps(responses)


def test_the_cli_prints_the_spec(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["openapi"]) == 0
    assert capsys.readouterr().out == openapi_text()


@pytest.fixture(scope="module")
def golden_responses(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("golden")
    write(root, served_dataset())
    os.utime(root / DATASET_PATH, ns=(GENERATION_NS, GENERATION_NS))
    client, _ = make_client(root)
    out: dict[str, Any] = {}
    for name, (path, _, overrides) in GOLDENS.items():
        if name == "error-stale-cursor":
            continue
        response = client.get(f"{PREFIX}{path}", headers=bearer(**overrides))
        assert response.status_code == 200, (name, response.text)
        out[name] = response.json()
    cursor = out["products"]["data"]["nextCursor"]
    write(root, served_dataset())
    os.utime(root / DATASET_PATH, ns=(GENERATION_NS + 1, GENERATION_NS + 1))
    client, _ = make_client(root)
    stale = client.get(
        f"{PREFIX}/products?limit=3&sort=price_asc&cursor={cursor}", headers=bearer()
    )
    assert stale.status_code == 409
    out["error-stale-cursor"] = stale.json()
    return out


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_goldens_match_and_validate(name: str, golden_responses: dict[str, Any]) -> None:
    doc = golden_responses[name]
    _, model, _ = GOLDENS[name]
    if model is not BaseModel:
        model.model_validate(doc)  # the golden is a valid instance of the documented model
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    target = GOLDEN / f"{name}.json"
    if REGENERATE:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return
    assert target.read_text(encoding="utf-8") == text, "regenerate: make openapi"


def test_hosting_routes_api_before_the_spa_catch_all() -> None:
    """Hosting requirement 5: any /api rewrite precedes ``**`` and pins the region.

    The rewrite itself lands with the deploy (S4); until then this guards its shape.
    """
    hosting = json.loads((REPO / "infra" / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    rewrites = hosting["rewrites"]
    sources = [r["source"] for r in rewrites]
    assert sources[-1] == "**", "the SPA catch-all must be the last rewrite"
    for rule in rewrites:
        if rule["source"].startswith("/api"):
            assert rule["run"] == {"serviceId": "pi-api", "region": "me-central1"}
            assert "pinTag" not in rule["run"]
