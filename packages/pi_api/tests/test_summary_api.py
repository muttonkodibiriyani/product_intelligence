"""``/v1/summary`` (API 1.4.0): freshness, thumbnails, the per-generation cache."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api_fixture import CLOCK, Client, bearer, make_client, write
from pi_api.source import LocalStore, SnapshotSource
from pi_api.summary import FreshnessStatus, SummaryCache, freshness
from pi_dataset import DatasetV3
from v3_fixture import doc, offer

API = "/api/v1"
IMG = "img.shop-a.example"
HOSTS = {"shop_a": frozenset({IMG})}
CUTOFF = datetime(2026, 9, 30, 23, 0, tzinfo=UTC)


def served(tmp_path: Path, hosts: Any = None) -> Client:
    d = doc()
    d["meta"]["test"] = False
    offer(d, "p01", "shop_a")["image"] = f"https://{IMG}/p01.jpg"
    write(tmp_path, DatasetV3.model_validate(d))
    return make_client(tmp_path, image_hosts=hosts)[0]


def get(client: Client, query: str = "", **claims: Any) -> Any:
    response = client.get(f"{API}/summary{query}", headers=bearer(**claims))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("age", "days", "status"),
    [
        (timedelta(hours=-2), 0, FreshnessStatus.FRESH),  # a clock behind the cutoff
        (timedelta(hours=23), 0, FreshnessStatus.FRESH),
        (timedelta(days=1, hours=23), 1, FreshnessStatus.FRESH),
        (timedelta(days=2), 2, FreshnessStatus.AGING),
        (timedelta(days=3, hours=23), 3, FreshnessStatus.AGING),
        (timedelta(days=4), 4, FreshnessStatus.STALE),
    ],
)
def test_freshness_counts_whole_days_since_the_cutoff(
    age: timedelta, days: int, status: FreshnessStatus
) -> None:
    f = freshness(CUTOFF, CUTOFF + age)
    assert (f.cutoff, f.age_days, f.status) == (CUTOFF, days, status)


def test_a_viewer_gets_the_default_context_with_its_freshness(tmp_path: Path) -> None:
    body = get(served(tmp_path))
    data = body["data"]
    assert data["retailer"] == "shop_a"
    assert body["status"] == "ok"
    assert data["freshness"]["status"] in {"fresh", "aging", "stale"}
    assert data["freshness"]["ageDays"] >= 0
    assert data["products"] >= data["priced"] > 0
    assert {"ladder", "promoDepth", "brandPrice", "categoryMix", "priceHist"} <= set(data)


def test_the_retailer_param_picks_the_context(tmp_path: Path) -> None:
    client = served(tmp_path)
    assert get(client, "?retailer=shop_b")["data"]["retailer"] == "shop_b"
    blocked = get(client, "?retailer=shop_d")
    assert blocked["data"]["products"] is None
    assert blocked["reason"] == "retailer_blocked"


@pytest.mark.parametrize("query", ["?retailer=shop_z", "?retailer=", "?retailer=a,b"])
def test_an_unknown_retailer_is_422(tmp_path: Path, query: str) -> None:
    response = served(tmp_path).get(f"{API}/summary{query}", headers=bearer())
    assert response.status_code == 422, response.text


def test_no_token_is_401(tmp_path: Path) -> None:
    assert served(tmp_path).get(f"{API}/summary").status_code == 401


def test_top_discounts_carry_a_thumbnail_only_from_an_image_host(tmp_path: Path) -> None:
    def p01(client: Client) -> Any:
        top = get(client)["data"]["topDiscounts"]
        assert top, "the fixture's shop_a has discounts"
        return next(t for t in top if t["id"] == "p01")

    assert p01(served(tmp_path / "on", HOSTS))["image"] == f"https://{IMG}/p01.jpg"
    assert p01(served(tmp_path / "off"))["image"] is None


def test_summaries_are_computed_once_per_generation_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = sys.modules["pi_api.summary"]
    calls: list[str | None] = []
    real = module.summary

    def counting(ds: Any, ctx: str | None, unverified: frozenset[str]) -> Any:
        calls.append(ctx)
        return real(ds, ctx, unverified)

    monkeypatch.setattr(module, "summary", counting)
    client = served(tmp_path)
    first = get(client)
    assert get(client, "?retailer=shop_a")["data"] == first["data"]  # default shop_a: one entry
    get(client, "?retailer=shop_b")
    assert calls == ["shop_a", "shop_b"]

    source = SnapshotSource(LocalStore(tmp_path), ("datasets/uae/latest.json",), 3600)
    source.load_all()
    (loaded,) = source.datasets()
    cache = SummaryCache({}, size=1)
    a = cache.get(loaded, "shop_a")
    assert cache.get(loaded, None) is a
    cache.get(loaded, "shop_b")
    assert cache.get(loaded, "shop_a") is not a  # evicted, computed again
    assert calls[2:] == ["shop_a", "shop_b", "shop_a"]


def test_the_clock_is_injected(tmp_path: Path) -> None:
    data = get(served(tmp_path))["data"]
    cutoff = datetime.fromisoformat(data["freshness"]["cutoff"])
    assert data["freshness"]["ageDays"] == max((CLOCK - cutoff).days, 0)
