"""Per-source dataset files served as one view per scope (ADR-0010)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from api_fixture import bearer, make_client, write
from pi_api.config import Settings, dataset_entries
from pi_api.source import LocalStore, SnapshotSource
from sources_fixture import SEPHORA, ULTA, days, snapshot

COMBINED = "datasets/ae/beauty/latest.json"
SEPHORA_FILE = "datasets/ae/sephora_me/latest.json"
ASSIGNED = {SEPHORA: SEPHORA_FILE, ULTA: COMBINED}
OLD, NEW = days("2026-09-22", 3), days("2026-09-30", 2)
BOTH = (ULTA, SEPHORA)


def ids(prefix: str, start: int, stop: int) -> list[str]:
    return [f"{prefix}{k:05d}" for k in range(start, stop)]


def test_the_combined_file_and_a_sephora_file_give_each_source_once(tmp_path: Path) -> None:
    """9529 Sephora products from the new file, 7275 Ulta from the combined one.

    The combined file has 7275 Ulta products, 3000 of them matched to an older Sephora offer, and
    500 older Sephora-only ones. The new Sephora file shares 5275 ids with Ulta products (3000 of
    them matched in the old file) and drops the 500.
    """
    old: dict[str, tuple[str, ...]] = dict.fromkeys(ids("p", 0, 3000), BOTH)
    old |= dict.fromkeys(ids("p", 3000, 7275), (ULTA,))
    old |= dict.fromkeys(ids("q", 0, 500), (SEPHORA,))
    write(tmp_path, snapshot(old, dates=OLD), COMBINED)
    new = dict.fromkeys(ids("p", 2000, 11529), (SEPHORA,))
    write(tmp_path, snapshot(new, dates=NEW, price=12_000), SEPHORA_FILE)

    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    loaded = source.select(None, None)  # one view; never ambiguous
    ds = loaded.dataset

    offers = Counter(r for p in ds.products for r in p.offers)
    assert offers == {SEPHORA: 9529, ULTA: 7275}
    assert len(ds.products) == len({p.id for p in ds.products}) == 11529
    assert not [p for p in ds.products if p.id.startswith("q")]
    sephora_prices = {
        m.minor
        for p in ds.products
        if SEPHORA in p.offers
        for m in p.offers[SEPHORA].series.price
        if m is not None
    }
    assert sephora_prices == {12_000}
    assert not [p for p in ds.products if p.matches]
    by_source = {s.source: s for s in loaded.sources}
    assert (by_source[SEPHORA].products, by_source[ULTA].products) == (9529, 7275)
    assert str(by_source[ULTA].cutoff.date()) == "2026-09-22"
    assert str(by_source[SEPHORA].cutoff.date()) == "2026-09-30"


def two_files(root: Path) -> None:
    write(root, snapshot({"p1": BOTH, "p2": (ULTA,)}, dates=OLD), COMBINED)
    write(root, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)


def test_meta_lists_each_source_with_its_own_cutoff(tmp_path: Path) -> None:
    two_files(tmp_path)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    response = client.get("/api/v1/meta", headers=bearer())
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    cutoffs = {s["source"]: s["cutoff"] for s in data["sources"]}
    assert cutoffs == {ULTA: "2026-09-22T00:00:00Z", SEPHORA: "2026-09-30T00:00:00Z"}
    assert sorted(r["id"] for r in data["retailers"]) == [SEPHORA, ULTA]


def test_the_view_waits_for_every_assigned_file(tmp_path: Path) -> None:
    write(tmp_path, snapshot({"p1": BOTH}, dates=OLD), COMBINED)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    assert source.datasets() == ()  # never Ulta alone, or the old Sephora as a fallback
    write(tmp_path, snapshot({"p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source.load_all()
    (view,) = source.datasets()
    assert {r.id for r in view.dataset.meta.retailers} == {SEPHORA, ULTA}


def test_a_bad_new_file_keeps_the_previous_view(tmp_path: Path) -> None:
    two_files(tmp_path)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    (before,) = source.datasets()
    (tmp_path / SEPHORA_FILE).write_text("{not json")
    source.load_all()
    assert source.datasets() == (before,)


def test_a_new_file_that_lacks_its_source_keeps_the_previous_view(tmp_path: Path) -> None:
    two_files(tmp_path)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    (before,) = source.datasets()
    write(tmp_path, snapshot({"p9": (ULTA,)}, dates=NEW), SEPHORA_FILE)
    source.load_all()
    assert source.datasets() == (before,)


def test_sources_of_two_scopes_are_two_views(tmp_path: Path) -> None:
    two_files(tmp_path)
    write(tmp_path, snapshot({"p3": (SEPHORA,)}, dates=NEW, scope="other"), SEPHORA_FILE)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    assert sorted(d.scope for d in source.datasets()) == ["beauty", "other"]
    assert {r.id for r in source.select("AE", "other").dataset.meta.retailers} == {SEPHORA}


def test_a_new_generation_rebuilds_the_view(tmp_path: Path) -> None:
    two_files(tmp_path)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    (before,) = source.datasets()
    source.load_all()  # unchanged: same view object
    assert source.datasets() == (before,)
    write(tmp_path, snapshot({"p4": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source.load_all()
    (after,) = source.datasets()
    assert after.generation != before.generation
    assert sorted(p.id for p in after.dataset.products) == ["p1", "p2", "p4"]


def test_whole_paths_still_work_beside_a_view(tmp_path: Path) -> None:
    two_files(tmp_path)
    other = "datasets/sa/beauty/latest.json"
    write(tmp_path, snapshot({"p1": (SEPHORA,)}, dates=NEW, scope="sa_beauty"), other)
    source = SnapshotSource(LocalStore(tmp_path), (other,), assigned=ASSIGNED)
    source.load_all()
    assert [d.scope for d in source.datasets()] == ["sa_beauty", "beauty"]
    assert source.select(None, "beauty").path == f"{SEPHORA}={SEPHORA_FILE},{ULTA}={COMBINED}"


def test_dataset_entries_reads_whole_and_per_source_paths() -> None:
    assert dataset_entries("datasets/uae/latest.json") == (("datasets/uae/latest.json",), {})
    raw = f" {SEPHORA}={SEPHORA_FILE}, {ULTA}={COMBINED},{COMBINED.replace('ae', 'sa')} ,"
    assert dataset_entries(raw) == (
        (COMBINED.replace("ae", "sa"),),
        {SEPHORA: SEPHORA_FILE, ULTA: COMBINED},
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (f"{SEPHORA}={SEPHORA_FILE},{SEPHORA}={COMBINED}", "twice"),
        (f"Bad Source={SEPHORA_FILE}", "source=path"),
        (f"{SEPHORA}=datasets/../x.json", "source=path"),
        (f"{SEPHORA}=", "source=path"),
    ],
)
def test_dataset_entries_refuses(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        dataset_entries(raw)


def env(datasets: str) -> dict[str, str]:
    return {
        "PI_API_FIREBASE_PROJECT": "p",
        "PI_API_DATASETS": datasets,
        "PI_API_LOCAL_DIR": "data",
    }


def test_settings_take_per_source_paths() -> None:
    settings = Settings.from_env(env(f"{SEPHORA}={SEPHORA_FILE},{ULTA}={COMBINED}"))
    assert settings.datasets == ()
    assert dict(settings.sources) == ASSIGNED


@pytest.mark.parametrize(
    ("datasets", "message"),
    [("", "names no dataset"), (f"{COMBINED},{ULTA}={COMBINED}", "both whole and per source")],
)
def test_settings_refuse(datasets: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.from_env(env(datasets))


STALE = {"code": "stale_source", "params": {"retailer": ULTA, "asOf": "2026-09-22"}}


def get(client: Any, url: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/{url}", headers=bearer())
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def stale(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"code": c["code"], "params": c["params"]}
        for c in body["caveats"]
        if c["code"] == "stale_source"
    ]


def test_the_latest_comparison_reads_a_stale_source_at_its_own_last_date(tmp_path: Path) -> None:
    two_files(tmp_path)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    body = get(client, f"compare?retailers={ULTA},{SEPHORA}")
    p1 = next(r for r in body["data"]["rows"] if r["id"] == "p1")
    assert (p1["basePrice"]["minor"], p1["otherPrice"]["minor"]) == (10_000, 10_000)
    assert body["caveats"][0]["code"] == "stale_source"
    assert stale(body) == [STALE]
    assert "2026-09-22" in body["caveats"][0]["en"]
    assert "2026-09-22" in body["caveats"][0]["ar"]
    # An explicit date reads that date: Ulta was not collected on 30 Sep.
    body = get(client, f"compare?retailers={ULTA},{SEPHORA}&date=2026-09-30")
    p1 = next(r for r in body["data"]["rows"] if r["id"] == "p1")
    assert p1["basePrice"] is None
    assert stale(body) == []


@pytest.mark.parametrize(
    "url",
    [
        f"index?retailers={ULTA},{SEPHORA}",
        f"promotions?retailer={ULTA}",
        f"availability?retailer={ULTA}",
        f"summary?retailer={ULTA}",
        f"products?retailer={ULTA}",
        "products",
        "products/p2",
        "admin/products/p1",
    ],
)
def test_latest_date_reads_of_a_stale_source_say_so(tmp_path: Path, url: str) -> None:
    two_files(tmp_path)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    headers = bearer(role="admin") if url.startswith("admin") else bearer()
    response = client.get(f"/api/v1/{url}", headers=headers)
    assert response.status_code == 200, response.text
    assert stale(response.json()) == [STALE]


@pytest.mark.parametrize(
    "url",
    [
        f"summary?retailer={SEPHORA}",
        f"availability?retailer={SEPHORA}",
        f"availability?retailer={ULTA}&date=2026-09-22",
        "products/p3",
        f"launches?retailer={ULTA}",
        f"coverage?retailer={ULTA}",
    ],
)
def test_other_reads_carry_no_stale_caveat(tmp_path: Path, url: str) -> None:
    two_files(tmp_path)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    assert stale(get(client, url)) == []


def test_a_latest_gap_is_never_claimed_from_a_stale_source(tmp_path: Path) -> None:
    """Gaps read the view itself: p3 isn't "missing at Ulta" on a date Ulta wasn't collected."""
    two_files(tmp_path)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    body = get(client, f"assortment-gaps?missingAt={ULTA}&presentAt={SEPHORA}")
    assert body["data"]["items"] == []
    assert stale(body) == [STALE]


def test_a_whole_file_has_no_stale_source(tmp_path: Path) -> None:
    write(tmp_path, snapshot({"p1": BOTH, "p2": (ULTA,)}, dates=OLD), COMBINED)
    client, source = make_client(tmp_path, paths=(COMBINED,))
    (loaded,) = source.datasets()
    assert (loaded.latest, loaded.stale) == (None, ())
    assert stale(get(client, f"compare?retailers={ULTA},{SEPHORA}")) == []


@pytest.mark.parametrize(
    ("shop", "as_of", "cutoff", "status"),
    [
        (ULTA, "2026-09-22", "2026-09-22T00:00:00Z", "stale"),
        (SEPHORA, "2026-09-30", "2026-09-30T00:00:00Z", "aging"),
    ],
)
def test_a_summary_is_as_fresh_as_its_own_source(
    tmp_path: Path, shop: str, as_of: str, cutoff: str, status: str
) -> None:
    """The Reviewer's #126 probe: a stale source's summary is labelled with its own date."""
    two_files(tmp_path)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    data = get(client, f"summary?retailer={shop}")["data"]
    assert data["asOf"] == as_of
    assert (data["freshness"]["cutoff"], data["freshness"]["status"]) == (cutoff, status)
