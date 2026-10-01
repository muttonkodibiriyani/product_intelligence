"""S3 metric endpoints (design §6): thin wrappers over ``pi_metrics`` plus the match list."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, served_dataset, write
from metrics_fixture import A, B, C, D
from pi_api.analytics import capped_launches
from pi_metrics import Metric, Status
from pi_metrics.launches import Launch, Launches

API = "/api/v1"
NO_STORE = "private, no-store"
PAIR = f"retailers={A},{B}"


@pytest.fixture
def client(tmp_path: Path) -> Client:
    write(tmp_path, served_dataset())
    return make_client(tmp_path)[0]


def body(client: Client, path: str, status: int = 200, **overrides: Any) -> Any:
    response = client.get(f"{API}{path}", headers=bearer(**overrides))
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == NO_STORE
    return response.json()


METRIC_PATHS = [
    f"/compare?{PAIR}",
    f"/index?{PAIR}",
    "/promotions",
    f"/assortment-gaps?missingAt={B}&presentAt={A}",
    "/availability",
    "/launches",
    "/reviews-summary",
    "/matches",
]


@pytest.mark.parametrize("path", METRIC_PATHS)
def test_metric_routes_are_bearer_only_and_no_store(client: Client, path: str) -> None:
    response = client.get(f"{API}{path}")
    assert response.status_code == 401
    assert response.headers["cache-control"] == NO_STORE
    assert body(client, path, 403, role=None)["error"]["code"] == "forbidden"
    doc = body(client, path)
    assert doc["meta"]["endpoint"] == path[1:].split("?", maxsplit=1)[0].replace("-", "_")
    assert doc["status"] in {"ok", "not_enough_data"}


@pytest.mark.parametrize(
    "path",
    [
        "/compare",
        f"/compare?retailers={A}",
        f"/compare?retailers={A},{A}",
        f"/compare?retailers={A},shop_x",
        f"/compare?retailers={A};{B}",
        f"/compare?{PAIR}&groupBy=size",
        f"/compare?{PAIR}&date=2020-01-01",
        f"/index?{PAIR}&from=2026-09-30&to=2026-09-01",
        f"/index?{PAIR}&from=2027-01-01",
        "/promotions?minPct=abc",
        "/promotions?retailer=shop_x",
        f"/assortment-gaps?missingAt={B}",
        f"/assortment-gaps?missingAt={B}&presentAt={B}",
        "/availability?retailer=Shop_A",
        "/launches?since=yesterday",
        "/matches?retailers=shop_x,shop_a",
        f"/matches?retailers={A},{A}",
        "/matches?class=twin",
        "/matches?limit=0",
        f"/compare?{PAIR}&limit=0",
        f"/compare?{PAIR}&limit=501",
        "/promotions?limit=ten",
        "/launches?limit=0",
        "/index?retailers=shop_a,shop_b&limit=3",
    ],
)
def test_bad_metric_queries_are_422(client: Client, path: str) -> None:
    doc = body(client, path, 422)
    assert doc["error"]["code"] in {"invalid_request", "invalid_query"}


def test_compare_counts_only_exact_counted_pairs(client: Client) -> None:
    doc = body(client, f"/compare?{PAIR}&groupBy=brand")
    assert doc["status"] == "ok"
    assert doc["cohort"]["n"] == 6
    data = doc["data"]
    rows = {r["id"]: r for r in data["rows"]}
    assert rows["p01"]["gap"]["pct"] == "11.1"
    assert rows["p01"]["gap"]["cheaper"] == "base"
    assert rows["p07"]["excludedReason"] == "match_unreviewed"
    assert rows["p16"]["excludedReason"] == "no_match"  # never inferred through shop_c
    assert data["summary"]["n"] == 6
    assert data["summary"]["basket"]["base"]["currency"] == "AED"
    assert {g["key"] for g in data["groups"]} >= {"Fixture Beauty"}
    assert doc["meta"]["filters"]["retailers"] == f"{A},{B}"


def test_compare_order_is_significant(client: Client) -> None:
    forward = body(client, f"/compare?{PAIR}&id=p01")["data"]["rows"][0]["gap"]
    backward = body(client, f"/compare?retailers={B},{A}&id=p01")["data"]["rows"][0]["gap"]
    assert forward["cheaper"] == "base"
    assert backward["cheaper"] == "other"


def test_compare_against_a_blocked_retailer_is_not_enough_data(client: Client) -> None:
    doc = body(client, f"/compare?retailers={A},{D}")
    assert (doc["status"], doc["reason"]) == ("not_enough_data", "retailer_blocked")
    assert doc["data"]["summary"] is None
    assert doc["detail"]["en"]


def test_index_is_a_fixed_basket_series(client: Client) -> None:
    doc = body(client, f"/index?{PAIR}")
    points = doc["data"]["points"]
    assert [p["n"] for p in points] == [7, 7, 6]
    assert points[-1]["index"] == "103.3"
    assert doc["data"]["trendAvailable"] is True
    single = body(client, f"/index?{PAIR}&from=2026-09-30")
    assert len(single["data"]["points"]) == 1


def _gap_first(row: dict[str, Any]) -> tuple[bool, Decimal, str]:
    gap = row["gap"]
    return (gap is None, -abs(Decimal(gap["pct"])) if gap else Decimal(0), row["id"])


@pytest.mark.parametrize("limit", [1, 3, 15, 500])
def test_compare_limit_cuts_rows_by_largest_gap_and_keeps_the_summary(
    client: Client, limit: int
) -> None:
    full = body(client, f"/compare?{PAIR}")["data"]
    capped = body(client, f"/compare?{PAIR}&limit={limit}")
    data = capped["data"]
    assert (full["total"], full["truncated"]) == (len(full["rows"]), False)
    assert data["total"] == full["total"] == 15
    assert data["truncated"] is (limit < data["total"])
    assert data["rows"] == sorted(full["rows"], key=_gap_first)[:limit]
    assert data["summary"] == full["summary"]  # the metric is over every row
    assert data["sides"] == full["sides"]
    assert capped["meta"]["filters"]["limit"] == limit


def test_promotions_limit_cuts_items_by_deepest_discount(client: Client) -> None:
    full = body(client, "/promotions")["data"]
    assert full["total"] == len(full["items"]) >= 2
    data = body(client, "/promotions?limit=1")["data"]
    deepest = sorted(full["items"], key=lambda i: (-Decimal(i["depthPct"]), i["id"], i["retailer"]))
    assert (data["items"], data["total"], data["truncated"]) == (deepest[:1], full["total"], True)
    assert data["retailers"] == full["retailers"]


def test_launches_limit_keeps_the_newest_first() -> None:
    items = (
        Launch(id="p2", name="b", retailer=B, first_seen=date(2026, 9, 2)),
        Launch(id="p1", name="a", retailer=B, first_seen=date(2026, 9, 1)),
        Launch(id="p3", name="c", retailer=A, first_seen=date(2026, 9, 2)),
        Launch(id="p2", name="b", retailer=A, first_seen=date(2026, 9, 2)),
    )
    metric = Metric[Launches](
        status=Status.OK, data=Launches(items=items, total=4), as_of=date(2026, 9, 30)
    )
    assert capped_launches(metric, None) is metric
    capped = capped_launches(metric, 3).data
    assert [(i.id, i.retailer) for i in capped.items] == [("p2", A), ("p2", B), ("p3", A)]
    assert (capped.total, capped.truncated) == (4, True)
    assert capped_launches(metric, 4).data.truncated is False


def test_launches_limit_on_the_route(client: Client) -> None:
    data = body(client, "/launches?limit=1")["data"]
    assert (len(data["items"]), data["total"], data["truncated"]) == (1, 1, False)


def test_promotions_availability_launches_reviews(client: Client) -> None:
    promos = body(client, f"/promotions?retailer={A}&minPct=10")["data"]
    assert all(i["retailer"] == A for i in promos["items"])
    stock = body(client, f"/availability?retailer={A}")["data"]["retailers"]
    assert [r["retailer"] for r in stock] == [A]
    launches = body(client, "/launches")
    assert [(i["id"], i["retailer"]) for i in launches["data"]["items"]] == [("p14", B)]
    assert launches["caveats"][0]["code"] == "launches_withheld"
    assert body(client, "/launches?since=2026-09-30")["data"]["items"] == []
    reviews = body(client, f"/reviews-summary?retailer={C}")["data"]["retailers"]
    assert [r["retailer"] for r in reviews] == [C]


def test_assortment_gaps(client: Client) -> None:
    doc = body(client, f"/assortment-gaps?missingAt={B}&presentAt={A}")
    assert [i["id"] for i in doc["data"]["items"]] == ["p12"]
    assert doc["data"]["total"] == 1


# ---------------------------------------------------------------- product pairs and sort=gap


def test_cards_carry_a_gap_only_for_a_two_retailer_filter(client: Client) -> None:
    plain = body(client, "/products?limit=2")["data"]["items"]
    assert all(card["gap"] is None for card in plain)
    paired = body(client, f"/products?retailer={A}&retailer={B}&limit=50")["data"]["items"]
    gap = next(card["gap"] for card in paired if card["id"] == "p01")
    assert (gap["base"], gap["other"], gap["gap"]["pct"]) == (A, B, "11.1")


def test_sort_by_gap_puts_counted_pairs_first(client: Client) -> None:
    doc = body(client, f"/products?retailer={A}&retailer={B}&sort=gap&limit=50")
    items = doc["data"]["items"]
    pcts = [float(c["gap"]["gap"]["pct"]) for c in items if c["gap"]["gap"] is not None]
    assert pcts == sorted(pcts, reverse=True)
    assert len(pcts) == 6
    tail = items[len(pcts) :]
    assert all(c["gap"]["gap"] is None for c in tail)
    assert [c["id"] for c in tail] == sorted(c["id"] for c in tail)
    assert body(client, "/products?sort=gap", 422)["error"]["code"] == "invalid_query"
    assert body(client, f"/products?retailer={A}&retailer={A}&sort=gap", 422)


def test_sort_by_gap_asc_flips_only_the_counted_order(client: Client) -> None:
    path = f"/products?retailer={A}&retailer={B}&limit=50&sort="
    down = body(client, f"{path}gap")["data"]["items"]
    up = body(client, f"{path}gap_asc")["data"]["items"]
    pcts = [Decimal(c["gap"]["gap"]["pct"]) for c in up if c["gap"]["gap"] is not None]
    assert pcts == sorted(pcts)
    counted = len(pcts)
    assert {c["id"] for c in up[:counted]} == {c["id"] for c in down[:counted]}
    assert [c["id"] for c in up[counted:]] == [c["id"] for c in down[counted:]]
    assert body(client, "/products?sort=gap_asc", 422)["error"]["code"] == "invalid_query"


def test_sort_by_gap_pages_without_repeats(client: Client) -> None:
    path = f"/products?retailer={A}&retailer={B}&sort=gap&limit=4"
    seen: list[str] = []
    doc = body(client, path)
    while True:
        seen += [c["id"] for c in doc["data"]["items"]]
        cursor = doc["data"]["nextCursor"]
        if cursor is None:
            break
        doc = body(client, f"{path}&cursor={cursor}")
    assert len(seen) == len(set(seen)) == doc["data"]["total"]


def test_product_detail_lists_every_retailer_pair(client: Client) -> None:
    pairs = body(client, "/products/p16")["data"]["pairs"]
    by_pair = {(p["base"], p["other"]): p for p in pairs}
    assert set(by_pair) == {(A, B), (A, C), (B, C)}
    assert by_pair[A, B]["excludedReason"] == "no_match"
    admin = body(client, "/admin/products/p16", role="admin")["data"]["pairs"]
    assert admin == pairs


# ---------------------------------------------------------------- matches


def test_viewers_see_counted_states_only(client: Client) -> None:
    viewer = body(client, "/matches?limit=100")["data"]
    admin = body(client, "/matches?limit=100", role="admin")["data"]
    assert {m["reviewState"] for m in viewer["items"]} <= {"approved", "locked"}
    assert {"proposed", "rejected"} <= {m["reviewState"] for m in admin["items"]}
    assert viewer["total"] < admin["total"]
    assert body(client, "/matches?reviewState=locked")["data"]["total"] > 0
    for state in ("proposed", "rejected"):
        assert body(client, f"/matches?reviewState={state}", 403)["error"]["code"] == "forbidden"
        assert body(client, f"/matches?reviewState={state}", role="admin")["data"]["total"] == 1


def test_matches_filter_by_unordered_pair_class_and_brand(client: Client) -> None:
    forward = body(client, f"/matches?retailers={A},{C}", role="admin")["data"]
    backward = body(client, f"/matches?retailers={C},{A}", role="admin")["data"]
    assert forward == backward
    assert {(m["a"], m["b"]) for m in forward["items"]} == {(A, C)}
    family = body(client, "/matches?class=family")["data"]["items"]
    assert [m["productId"] for m in family] == ["p09"]
    brand = body(client, "/matches?brand=sample%20labs&limit=100")["data"]["items"]
    assert brand
    assert {m["brand"] for m in brand} == {"Sample Labs"}


def test_match_cursor_walks_once_and_is_bound_to_the_role(client: Client) -> None:
    seen: list[tuple[str, str, str]] = []
    doc = body(client, "/matches?limit=5", role="admin")
    first_cursor = doc["data"]["nextCursor"]
    while True:
        seen += [(m["productId"], m["a"], m["b"]) for m in doc["data"]["items"]]
        cursor = doc["data"]["nextCursor"]
        if cursor is None:
            break
        doc = body(client, f"/matches?limit=5&cursor={cursor}", role="admin")
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen)) == doc["data"]["total"]
    # An admin's cursor is refused to a viewer: their pages hold different rows.
    foreign = body(client, f"/matches?limit=5&cursor={first_cursor}", 422)
    assert foreign["error"]["code"] == "invalid_query"
