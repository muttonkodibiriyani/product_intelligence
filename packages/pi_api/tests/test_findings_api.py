"""``/v1/findings`` (API 1.24.0): the Insights findings, their example images, the price floor
and the per-generation cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, write
from pi_api import findings as route
from pi_dataset import DatasetV3
from pi_metrics.findings import findings
from v3_fixture import doc, offer

API = "/api/v1"
IMG = "img.shop-a.example"
HOSTS = {"shop_a": frozenset({IMG})}
LOW = {"amount": "0.01", "minor": 1, "currency": "AED"}


def served(tmp_path: Path, hosts: Any = None) -> Client:
    """p01's latest shop_a price is 0.01: the floor withholds it, so it is a pricing anomaly."""
    d = doc()
    d["meta"]["test"] = False
    o = offer(d, "p01", "shop_a")
    o["image"] = f"https://{IMG}/p01.jpg"
    o["series"]["price"][-1] = LOW
    write(tmp_path, DatasetV3.model_validate(d))
    return make_client(tmp_path, image_hosts=hosts)[0]


def get(client: Client, query: str) -> Any:
    response = client.get(f"{API}/findings?{query}", headers=bearer())
    assert response.status_code == 200, response.text
    return response.json()


def anomalies(body: Any) -> Any:
    return next(f for f in body["data"]["findings"] if f["key"] == "pricing_anomalies")


def test_findings_rank_twelve_and_show_withheld_prices_as_anomalies(tmp_path: Path) -> None:
    body = get(served(tmp_path, HOSTS), "focus=shop_a&rival=shop_b")
    assert body["meta"]["endpoint"] == "findings"
    data = body["data"]
    assert (data["focus"], data["rival"], data["thirds"]) == (
        "shop_a",
        "shop_b",
        ["shop_c", "shop_d"],
    )
    assert [f["rank"] for f in data["findings"]] == list(range(1, 13))
    f = anomalies(body)
    assert (f["status"], f["n"], f["params"]["focusCount"]["value"]) == ("ok", 1, "1")
    (e,) = f["examples"]
    assert (e["id"], e["price"], e["priceWithheld"]) == ("p01", None, True)
    assert e["image"] == f"https://{IMG}/p01.jpg"
    assert "invalid_price_excluded" in {c["code"] for c in body["caveats"]}


def test_example_images_need_an_allowed_host(tmp_path: Path) -> None:
    (e,) = anomalies(get(served(tmp_path), "focus=shop_a&rival=shop_b"))["examples"]
    assert e["image"] is None


def test_too_few_counted_pairs_withhold_the_matched_findings(tmp_path: Path) -> None:
    data = get(served(tmp_path), "focus=shop_a&rival=shop_c")["data"]
    assert data["countedPairs"] == 1
    matched = {"brand_depth_gaps", "brand_price_policy", "size_level_gaps", "real_discounts"}
    rows = [f for f in data["findings"] if f["key"] in matched]
    assert len(rows) == len(matched)
    assert all(f["status"] == "not_enough_data" and f["reason"] for f in rows)
    assert all((f["figure"], f["examples"]) == (None, []) for f in rows)


@pytest.mark.parametrize(
    "query", ["focus=shop_a&rival=shop_a", "focus=shop_a&rival=nowhere", "focus=shop_a"]
)
def test_bad_pairs_are_refused(tmp_path: Path, query: str) -> None:
    response = served(tmp_path).get(f"{API}/findings?{query}", headers=bearer())
    assert response.status_code == 422


def counting(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    real = findings

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append((args[1], args[2]))
        return real(*args, **kwargs)

    monkeypatch.setattr(route, "findings", counted)
    return calls


def test_findings_are_computed_once_per_generation_and_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = counting(monkeypatch)
    client = served(tmp_path)
    first = get(client, "focus=shop_a&rival=shop_b")
    assert get(client, "focus=shop_a&rival=shop_b")["data"] == first["data"]
    get(client, "focus=shop_b&rival=shop_a")
    assert calls == [("shop_a", "shop_b"), ("shop_b", "shop_a")]


def test_the_cache_drops_the_least_recently_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(route, "CACHE_SIZE", 1)
    calls = counting(monkeypatch)
    client = served(tmp_path)
    for query in ("focus=shop_a&rival=shop_b", "focus=shop_b&rival=shop_a") * 2:
        get(client, query)
    assert len(calls) == 4
