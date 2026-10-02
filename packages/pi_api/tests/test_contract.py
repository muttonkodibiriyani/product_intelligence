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
from pi_api.summary import SummaryView
from pi_api.wire import Envelope, ProductEnvelope
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
    "product": ("/products/p01", ProductEnvelope[ProductDetail], {}),
    "admin-product": (
        "/admin/products/p01",
        ProductEnvelope[AdminProductDetail],
        {"role": "admin"},
    ),
    "history": ("/products/p05/history", ProductEnvelope[History], {}),
    "coverage": ("/coverage", Envelope[Coverage], {}),
    "products-gap": (
        "/products?retailer=shop_a&retailer=shop_b&sort=gap&limit=3",
        Envelope[ProductPage],
        {},
    ),
    "compare": ("/compare?retailers=shop_a,shop_b&groupBy=brand", Envelope[Comparison], {}),
    "compare-limited": (
        "/compare?retailers=shop_a,shop_b&limit=3",
        Envelope[Comparison],
        {},
    ),
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
    "summary": ("/summary", Envelope[SummaryView], {}),
    "summary-blocked": ("/summary?retailer=shop_d", Envelope[SummaryView], {}),
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
    """Hosting requirement 5: the /api rewrite is first, ``**`` last, and the region is pinned."""
    hosting = json.loads((REPO / "infra" / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    rewrites = hosting["rewrites"]
    sources = [r["source"] for r in rewrites]
    assert sources[0] == "/api/**", "the API rewrite must precede every other rewrite"
    assert sources[-1] == "**", "the SPA catch-all must be the last rewrite"
    for rule in rewrites:
        if rule["source"].startswith("/api"):
            assert rule["run"] == {"serviceId": "pi-api", "region": "me-central1"}
            assert "pinTag" not in rule["run"]


def test_the_csp_names_only_the_expected_external_hosts() -> None:
    """Thumbnails (API 1.3.0) are hotlinked from exactly one image host; nothing else is added.

    Images are hotlinked, never copied or rehosted. img-product.sephora.me is the only host for
    PI-collected (sephora_me) images; media.alshaya.com is allowed solely to keep serving the
    ulta_ae view live since 2026-10-01 (decision log, 2026-10-01).
    ``connect-src`` keeps the Firebase Auth and Storage hosts it already had. The assistant
    (switch-on build, App Check with reCAPTCHA Enterprise) adds exactly the reCAPTCHA script and
    frame paths, the App Check token exchange and the me-central1 callable host.
    Every unquoted source counts, not only dotted hosts, so a scheme-only ``https:`` or a ``*``
    wildcard fails too; ``data:`` is allowed for inline images only.
    """
    hosting = json.loads((REPO / "infra" / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    (csp,) = [
        h["value"]
        for block in hosting["headers"]
        for h in block["headers"]
        if h["key"] == "Content-Security-Policy"
    ]
    external = {
        name: {s for s in sources if not s.startswith("'")}
        for name, *sources in (d.split() for d in csp.split(";") if d.strip())
    }
    assert external.pop("img-src") == {
        "data:",
        "https://img-product.sephora.me",
        "https://media.alshaya.com",
    }
    assert external.pop("connect-src") == {
        "https://identitytoolkit.googleapis.com",
        "https://securetoken.googleapis.com",
        "https://firebasestorage.googleapis.com",
        "https://content-firebaseappcheck.googleapis.com",
        "https://me-central1-productintelligence-beeb3.cloudfunctions.net",
    }
    assert external.pop("script-src") == {
        "https://www.google.com/recaptcha/",
        "https://www.gstatic.com/recaptcha/",
    }
    assert external.pop("frame-src") == {
        "https://www.google.com/recaptcha/",
        "https://recaptcha.google.com/recaptcha/",
    }
    assert all(not hosts for hosts in external.values()), external


@pytest.mark.parametrize(
    ("schema", "fields"),
    [
        ("TopDiscount", {"brand", "name", "category", "image"}),
        ("BrandPrice", {"brand"}),
        ("CategoryShare", {"category"}),
        ("LadderRow", {"category"}),
        ("PromoDepth", {"category"}),
    ],
)
def test_summary_page_text_is_tagged(schema: str, fields: set[str]) -> None:
    """AIE's #104 flag: every retailer-written field in ``SummaryView`` is ``x-pi-source-text``."""
    properties = openapi()["components"]["schemas"][schema]["properties"]
    tagged = {k for k, v in properties.items() if '"x-pi-source-text": true' in json.dumps(v)}
    assert tagged == fields
