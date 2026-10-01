"""The HTTP layer: hosting requirements (no-store, fail-closed Bearer auth), errors, routes."""

from __future__ import annotations

import gzip
import os
from pathlib import Path
from typing import Any

import anyio
import pytest
from starlette.types import Message, Receive, Scope, Send

from api_fixture import (
    DATASET_PATH,
    KID,
    Client,
    FakeCerts,
    bearer,
    make_client,
    served_dataset,
    write,
)
from metrics_fixture import A, B, C, rebuild, with_capabilities
from pi_api.app import ServerErrors, TokenBuckets
from pi_api.auth import CertificatesUnavailableError
from pi_api.source import SnapshotSource

API = "/api/v1"
NO_STORE = "private, no-store"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    write(tmp_path, served_dataset())
    return tmp_path


@pytest.fixture
def client(root: Path) -> Client:
    return make_client(root)[0]


def body(client: Client, path: str, status: int = 200, **overrides: Any) -> Any:
    response = client.get(path, headers=bearer(**overrides))
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == NO_STORE
    return response.json()


def floats(value: Any) -> list[Any]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [f for v in value.values() for f in floats(v)]
    if isinstance(value, list):
        return [f for v in value for f in floats(v)]
    return []


# ---------------------------------------------------------------- hosting requirements

ROUTES = [
    f"{API}/meta",
    f"{API}/products",
    f"{API}/products/p01",
    f"{API}/products/p01/history",
    f"{API}/admin/products/p01",
    f"{API}/coverage",
    f"{API}/not-a-route",
    "/",
    "/docs",
    "/openapi.json",
    "/healthz",
]


@pytest.mark.parametrize("path", ROUTES)
def test_every_path_is_401_without_a_token(client: Client, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["cache-control"] == NO_STORE
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("path", ROUTES)
def test_every_response_is_private_no_store(client: Client, path: str) -> None:
    for headers in ({}, bearer(), bearer(role="admin"), bearer(role="none")):
        response = client.get(path, headers=headers)
        assert response.headers["cache-control"] == NO_STORE, (path, response.status_code)
        assert response.headers["x-content-type-options"] == "nosniff"


def test_a_cookie_is_never_a_credential(client: Client) -> None:
    session = f"__session={bearer()['Authorization'].removeprefix('Bearer ')}"
    response = client.get(f"{API}/meta", headers={"Cookie": session})
    assert response.status_code == 401


def test_two_authorization_headers_are_refused(client: Client) -> None:
    good = bearer()["Authorization"]
    response = client.get(f"{API}/meta", headers=[("Authorization", good)] * 2)
    assert response.status_code == 401


def test_a_token_without_a_role_is_403_everywhere(client: Client) -> None:
    for path in ROUTES:
        assert body(client, path, 403, role=None)["error"]["code"] == "forbidden"


def test_docs_and_health_routes_do_not_exist(client: Client) -> None:
    for path in ("/docs", "/redoc", "/openapi.json", "/healthz", "/readyz"):
        assert body(client, path, 404)["error"]["code"] == "not_found"


def test_only_get_is_served(client: Client) -> None:
    response = client.request("POST", f"{API}/products", headers=bearer())
    assert response.status_code == 405
    assert response.headers["cache-control"] == NO_STORE


def test_rate_limit_is_per_uid_with_retry_after(root: Path) -> None:
    client, _ = make_client(root, rate=1, burst=2)
    for _ in range(2):
        body(client, f"{API}/meta", sub="busy")
    limited = client.get(f"{API}/meta", headers=bearer(sub="busy"))
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "1"
    assert limited.headers["cache-control"] == NO_STORE
    body(client, f"{API}/meta", sub="other")  # a different uid has its own bucket


def test_token_buckets_refill_and_evict() -> None:
    now = [0.0]
    buckets = TokenBuckets(rate=2, burst=1, clock=lambda: now[0], capacity=2)
    assert buckets.take("u") == 0
    assert buckets.take("u") == pytest.approx(0.5)
    now[0] = 0.5
    assert buckets.take("u") == 0
    buckets.take("v")
    buckets.take("w")  # evicts u, the least recently used
    assert buckets.take("u") == 0


# ---------------------------------------------------------------- data availability


class DownCerts(FakeCerts):
    def certificates(self) -> dict[str, str]:
        raise CertificatesUnavailableError


@pytest.mark.parametrize("certs", [DownCerts(), FakeCerts({KID: "not a pem"})])
def test_unverifiable_tokens_are_a_retryable_503_not_a_sign_out(
    root: Path, certs: FakeCerts
) -> None:
    client = make_client(root, certs=certs)[0]
    response = client.get(f"{API}/meta", headers=bearer())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"
    assert response.headers["retry-after"] == "5"
    assert response.headers["cache-control"] == NO_STORE
    assert "www-authenticate" not in response.headers


def test_an_error_escaping_the_guards_is_a_json_500_with_no_store(root: Path) -> None:
    class Exploding(FakeCerts):
        def certificates(self) -> dict[str, str]:
            raise RuntimeError("boom")

    client = make_client(root, certs=Exploding())[0]
    response = client.get(f"{API}/meta", headers=bearer())
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "internal error"}}
    assert response.headers["cache-control"] == NO_STORE
    assert response.headers["x-content-type-options"] == "nosniff"


def test_an_error_inside_a_route_is_a_json_500_with_no_store(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, source = make_client(root)

    def broken(*_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(source, "select", broken)
    response = client.get(f"{API}/meta", headers=bearer())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "boom" not in response.text
    assert response.headers["cache-control"] == NO_STORE


def test_no_dataset_is_503_with_retry_after(tmp_path: Path) -> None:
    client, source = make_client(tmp_path)
    response = client.get(f"{API}/meta", headers=bearer())
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert response.headers["cache-control"] == NO_STORE
    write(tmp_path, served_dataset())
    source.load_all()
    body(client, f"{API}/meta")


def test_test_datasets_are_refused_by_default(tmp_path: Path) -> None:
    write(tmp_path, rebuild(served_dataset(), test=True))
    client, _ = make_client(tmp_path)
    assert body(client, f"{API}/meta", 503)["error"]["code"] == "data_unavailable"


def test_a_bad_new_generation_keeps_the_last_good_one(root: Path) -> None:
    client, source = make_client(root)
    before = body(client, f"{API}/meta")["meta"]["generation"]
    target = root / DATASET_PATH
    target.write_text('{"schema": "pi.dataset/v2"}')
    os.utime(target, ns=(1, 1))
    source.load_all()
    assert body(client, f"{API}/meta")["meta"]["generation"] == before


def test_gzip_datasets_are_read(root: Path) -> None:
    target = root / DATASET_PATH
    target.write_bytes(gzip.compress(target.read_bytes()))
    client, _ = make_client(root)
    assert body(client, f"{API}/meta")["meta"]["scope"] == "fixture"


def test_unknown_market_or_scope_is_404(client: Client) -> None:
    assert body(client, f"{API}/meta?market=SA", 404)["error"]["code"] == "not_found"
    assert body(client, f"{API}/meta?scope=other", 404)["error"]["code"] == "not_found"
    body(client, f"{API}/meta?market=ae&scope=fixture")


def test_two_matching_datasets_must_be_disambiguated(root: Path) -> None:
    write(root, rebuild(served_dataset(), scope="second"), "datasets/uae/second.json")
    paths = (DATASET_PATH, "datasets/uae/second.json")
    client, _ = make_client(root, paths=paths)
    assert body(client, f"{API}/meta", 422)["error"]["code"] == "ambiguous_dataset"
    meta = body(client, f"{API}/meta?scope=second")
    assert meta["meta"]["scope"] == "second"
    assert [d["scope"] for d in meta["data"]["datasets"]] == ["fixture", "second"]


# ---------------------------------------------------------------- meta and the envelope


def test_meta_envelope(client: Client) -> None:
    doc = body(client, f"{API}/meta")
    assert doc["status"] == "ok"
    meta = doc["meta"]
    assert meta["apiVersion"] == "1.0.0"
    assert (meta["endpoint"], meta["market"], meta["currency"]) == ("meta", "AE", "AED")
    assert [r["id"] for r in doc["data"]["retailers"]] == [A, B, C, "shop_d"]
    tree = {n["key"]: n for n in doc["data"]["categories"]}
    assert tree["makeup"]["count"] == 2
    assert tree["skincare"]["children"][0]["key"] == "serum"
    assert floats(doc) == []


# ---------------------------------------------------------------- products


def ids(doc: Any) -> list[str]:
    return [item["id"] for item in doc["data"]["items"]]


def test_products_default_page(client: Client) -> None:
    doc = body(client, f"{API}/products")
    assert doc["data"]["total"] == 16
    assert doc["data"]["nextCursor"] is None
    assert ids(doc) == sorted(ids(doc))
    assert floats(doc) == []


def test_paging_walks_every_product_once(client: Client) -> None:
    seen, cursor = [], None
    while True:
        query = "limit=5&brand=Fixture%20Beauty&brand=Sample%20Labs" + (
            f"&cursor={cursor}" if cursor else ""
        )
        doc = body(client, f"{API}/products?{query}")
        seen += ids(doc)
        cursor = doc["data"]["nextCursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == doc["data"]["total"]
    assert doc["meta"]["filters"]["brand"] == ["Fixture Beauty", "Sample Labs"]


def test_a_cursor_is_bound_to_its_generation_and_filters(root: Path) -> None:
    client, source = make_client(root)
    cursor = body(client, f"{API}/products?limit=2")["data"]["nextCursor"]
    wrong = body(client, f"{API}/products?limit=2&q=p0&cursor={cursor}", 422)
    assert wrong["error"]["code"] == "invalid_query"
    assert body(client, f"{API}/products?cursor=%%%", 422)["error"]["code"] == "invalid_query"
    write(root, rebuild(served_dataset(), match_stage="reviewed-again"))
    os.utime(root / DATASET_PATH, ns=(2, 2))
    source.load_all()
    stale = body(client, f"{API}/products?limit=2&cursor={cursor}", 409)
    assert stale["error"]["code"] == "stale_cursor"


def test_search_folds_case_and_arabic_letter_forms(client: Client) -> None:
    assert ids(body(client, f"{API}/products?q=PRODUCT%20p1")) == [
        "p10",
        "p11",
        "p12",
        "p13",
        "p14",
        "p15",
        "p16",
    ]
    assert ids(body(client, f"{API}/products?q=sample%20p02")) == ["p02"]


def test_facets_ignore_their_own_filter(client: Client) -> None:
    doc = body(client, f"{API}/products?brand=Sample%20Labs&retailer={C}")
    assert doc["data"]["total"] == 0  # no Sample Labs product at shop_c
    facets = doc["data"]["facets"]
    # brand drops the brand filter: what shop_c carries, by brand.
    assert facets["brand"] == [{"key": "Fixture Beauty", "count": 2}]
    # retailer drops the retailer filter: where Sample Labs is sold.
    assert facets["retailer"] == [{"key": A, "count": 3}, {"key": B, "count": 3}]
    # category keeps both filters.
    assert facets["category"] == []


def test_matched_filter_means_an_exact_counted_edge(client: Client) -> None:
    matched = ids(body(client, f"{API}/products?matched=true"))
    assert matched == ["p01", "p02", "p03", "p04", "p05", "p06", "p10", "p11", "p13", "p16"]
    unmatched = ids(body(client, f"{API}/products?matched=false"))
    assert unmatched == ["p07", "p08", "p09", "p12", "p14", "p15"]


def test_price_filter_uses_the_visible_retailers_and_skips_early_offers(client: Client) -> None:
    doc = body(client, f"{API}/products?priceMax=60&sort=price_asc&retailer={B}")
    # p13's shop_b offer is early, so it neither matches the retailer nor carries a price.
    assert ids(doc) == ["p07", "p08", "p09", "p10", "p16", "p14"]
    assert ids(body(client, f"{API}/products?priceMin=100.5&priceMax=200")) == []
    assert ids(body(client, f"{API}/products?priceMin=95")) == ["p02", "p03", "p04", "p06"]


def test_price_sorts_break_ties_on_id_both_ways(client: Client) -> None:
    desc = ids(body(client, f"{API}/products?sort=price_desc"))
    assert desc[:6] == ["p02", "p03", "p06", "p04", "p01", "p05"]
    asc = ids(body(client, f"{API}/products?sort=price_asc"))
    assert asc[:3] == ["p07", "p08", "p09"]
    assert asc[-6:] == ["p05", "p01", "p04", "p02", "p03", "p06"]


@pytest.mark.parametrize(
    "query",
    [
        "bogus=1",
        "limit=0",
        "limit=101",
        "sort=random",
        "priceMin=1e3",
        "priceMin=-1",
        "market=UAE",
        "retailer=shop_x",
        "q=" + "x" * 121,
        "&".join(["brand=b"] * 26),
    ],
)
def test_bad_product_queries_are_422(client: Client, query: str) -> None:
    doc = body(client, f"{API}/products?{query}", 422)
    assert doc["error"]["code"] in {"invalid_request", "invalid_query"}
    assert "x" * 50 not in doc["error"]["message"]  # input is never echoed


# ---------------------------------------------------------------- detail, history, coverage


def test_product_detail_hides_admin_evidence(client: Client) -> None:
    doc = body(client, f"{API}/products/p01")
    offer = doc["data"]["offers"][0]
    assert offer["promoPct"] == "10.0"
    assert set(offer["evidence"]) == {"capturedAt", "url"}
    assert body(client, f"{API}/products/zz", 404)["error"]["code"] == "not_found"
    assert body(client, f"{API}/products/a%20b", 422)["error"]["code"] == "invalid_request"


def test_admin_detail_is_admin_only(client: Client) -> None:
    assert body(client, f"{API}/admin/products/p01", 403)["error"]["code"] == "forbidden"
    doc = body(client, f"{API}/admin/products/p01", role="admin")
    assert {"source", "runId"} <= set(doc["data"]["offers"][0]["evidence"])


def test_history_series_and_window(client: Client) -> None:
    doc = body(client, f"{API}/products/p05/history?from=2026-09-29")
    points = doc["data"]["series"][A]
    assert [p["date"] for p in points] == ["2026-09-29", "2026-09-30"]
    assert points[-1]["price"]["amount"] == "80.00"
    assert body(client, f"{API}/products/p05/history?from=2026-09-30&to=2026-09-01", 422)
    assert floats(doc) == []


def test_history_without_the_capability_is_one_point(tmp_path: Path) -> None:
    write(tmp_path, with_capabilities(served_dataset(), history=False))
    client, _ = make_client(tmp_path)
    doc = body(client, f"{API}/products/p01/history")
    assert doc["status"] == "not_enough_data"
    assert doc["reason"] == "capability_off"
    assert doc["detail"]["en"]
    assert len(doc["data"]["series"][A]) == 1


def test_coverage(client: Client) -> None:
    doc = body(client, f"{API}/coverage?retailer={C}")
    (row,) = doc["data"]["retailers"]
    assert (row["id"], row["status"], row["productCount"]) == (C, "partial", 2)
    assert body(client, f"{API}/coverage?retailer=shop_x", 422)


def test_a_snapshot_source_is_what_the_app_reads(root: Path) -> None:
    _, source = make_client(root)
    assert isinstance(source, SnapshotSource)
    assert [d.scope for d in source.datasets()] == ["fixture"]


def test_server_errors_keeps_a_started_response_and_passes_other_scopes() -> None:
    sent: list[Message] = []

    async def half_sent(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("boom")

    async def lifespan(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "lifespan.startup.complete"})

    async def record(message: Message) -> None:
        sent.append(message)

    async def nothing() -> Message:
        return {"type": "http.disconnect"}

    async def run() -> None:
        await ServerErrors(half_sent)(
            {"type": "http", "method": "GET", "path": "/"}, nothing, record
        )
        await ServerErrors(lifespan)({"type": "lifespan"}, nothing, record)

    anyio.run(run)
    assert [m["type"] for m in sent] == ["http.response.start", "lifespan.startup.complete"]
    assert sent[0]["status"] == 200
