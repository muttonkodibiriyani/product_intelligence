"""Per-source dataset files served as one view per scope (ADR-0010)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from api_fixture import bearer, make_client, write
from pi_api.config import Settings, dataset_entries
from pi_api.source import LocalStore, SnapshotSource
from pi_dataset import DatasetV3
from sources_fixture import SEPHORA, ULTA, days, snapshot, snapshot_doc

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


def test_a_composed_source_cutoff_is_its_own_latest_capture(tmp_path: Path) -> None:
    """Reviewer, #120: a slice keeps its file's meta, so the cutoff comes from the source's
    offers, not from another retailer's later capture in the same file."""
    combined = snapshot_doc({"p1": BOTH, "p2": (ULTA,)}, dates=OLD)
    for product in combined["products"]:
        product["offers"][ULTA]["evidence"]["capturedAt"] = "2026-09-21T12:00:00Z"
    write(tmp_path, DatasetV3.model_validate(combined), COMBINED)
    write(tmp_path, snapshot({"p1": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source = SnapshotSource(LocalStore(tmp_path), (COMBINED,), assigned=ASSIGNED)
    source.load_all()
    for loaded in source.datasets():
        cutoffs = {s.source: s.cutoff.isoformat() for s in loaded.sources}
        assert cutoffs[ULTA] == "2026-09-21T12:00:00+00:00", loaded.path


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


def test_the_imported_retailer_is_corrected_in_composed_and_whole_views(tmp_path: Path) -> None:
    """The ``pi_api.dq`` view applies after composition, and to a whole file beside it."""
    combined = snapshot_doc({"p1": BOTH, "p2": (ULTA,)}, dates=OLD)
    for product in combined["products"]:
        for offer in product["offers"].values():
            offer["series"]["regular"] = [
                m and {**m, "minor": 20_000, "amount": "200.00"} for m in offer["series"]["price"]
            ]
    write(tmp_path, DatasetV3.model_validate(combined), COMBINED)
    write(tmp_path, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source = SnapshotSource(LocalStore(tmp_path), (COMBINED,), assigned=ASSIGNED)
    source.load_all()
    views = {d.path: d for d in source.datasets()}
    assert sorted(views) == [COMBINED, f"{SEPHORA}={SEPHORA_FILE},{ULTA}={COMBINED}"]
    for loaded in views.values():
        assert loaded.unverified == {ULTA}
        assert [(shop.retailer, shop.was_prices) for shop in loaded.imported] == [(ULTA, 2)]
        regular = {
            cid: o.series.regular for p in loaded.dataset.products for cid, o in p.offers.items()
        }
        assert regular[ULTA] is None
    whole = views[COMBINED].dataset
    assert all(p.offers[SEPHORA].series.regular for p in whole.products if SEPHORA in p.offers)


def test_the_floor_applies_before_dq_in_composed_and_whole_views(tmp_path: Path) -> None:
    """``pi_api.floor`` first, then ``pi_api.dq``, as main serves a whole file (merge of #120).

    Ulta's p2 regular is all 0.01: the floor withholds it, so dq counts one was-price (p1),
    not two; in the other order dq would clear it first and the floor would count nothing.
    """
    combined = snapshot_doc({"p1": BOTH, "p2": (ULTA,)}, dates=OLD)
    low = {"amount": "0.01", "minor": 1, "currency": "AED"}
    for product in combined["products"]:
        offer = product["offers"][ULTA]
        price = offer["series"]["price"]
        regular = {**price[0], "minor": 20_000, "amount": "200.00"}
        offer["series"]["regular"] = [low if product["id"] == "p2" else regular for _ in price]
    write(tmp_path, DatasetV3.model_validate(combined), COMBINED)
    write(tmp_path, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source = SnapshotSource(LocalStore(tmp_path), (COMBINED,), assigned=ASSIGNED)
    source.load_all()
    views = {d.path: d for d in source.datasets()}
    assert len(views) == 2
    for loaded in views.values():
        assert [(f.retailer, f.offers) for f in loaded.floor.floored] == [(ULTA, 1)]
        assert [(shop.retailer, shop.was_prices) for shop in loaded.imported] == [(ULTA, 1)]


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
