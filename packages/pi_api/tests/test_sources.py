"""Per-source dataset files served as one view per scope (ADR-0010)."""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from api_fixture import bearer, make_client, write
from pi_api import dq
from pi_api.config import Settings, dataset_entries
from pi_api.source import AsOfViewError, LocalStore, SnapshotSource
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
        assert loaded.unverified == frozenset()  # stated was-prices are served (API 1.13.0)
        assert loaded.imported_contexts == {ULTA}
        assert [(shop.retailer, shop.was_prices) for shop in loaded.imported] == [(ULTA, 2)]
        regular = {
            cid: o.series.regular for p in loaded.dataset.products for cid, o in p.offers.items()
        }
        assert regular[ULTA] is not None
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


def test_composed_and_whole_views_build_their_product_ids_at_load(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Each served view's ids (``pi_api.ids``, #158) are built and logged at load, never on a
    request (merge of #120)."""
    caplog.set_level(logging.INFO, logger="pi_api.source")
    write(tmp_path, snapshot({"p1": BOTH, "p2": (ULTA,)}, dates=OLD), COMBINED)
    write(tmp_path, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source = SnapshotSource(LocalStore(tmp_path), (COMBINED,), assigned=ASSIGNED)
    source.load_all()
    views = source.datasets()
    assert len(views) == 2
    assert all("ids" in vars(loaded) for loaded in views)
    logged = sorted(
        r.getMessage().split(" loaded at ")[0].removeprefix("dataset ")
        for r in caplog.records
        if "old product ids" in r.getMessage()
    )
    assert logged == [COMBINED, "scope:beauty"]


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


def test_a_stale_collected_source_summary_is_as_of_its_own_cutoff(tmp_path: Path) -> None:
    """Reviewer, #126: a stale source that isn't imported (so no snapshot freshness) reads its
    own last date and cutoff, never the view's later ones."""
    shop = "shop_x"  # a second collected retailer, its file ending before Sephora's
    write(tmp_path, snapshot({"p1": (shop,), "p2": (shop,)}, dates=OLD), COMBINED)
    write(tmp_path, snapshot({"p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    client, _ = make_client(tmp_path, paths=(), assigned={SEPHORA: SEPHORA_FILE, shop: COMBINED})
    body = get(client, f"summary?retailer={shop}")
    data = body["data"]
    assert data["asOf"] == "2026-09-22"
    assert data["freshness"]["cutoff"] == "2026-09-22T00:00:00Z"
    assert data["freshness"]["status"] not in {"fresh", "snapshot"}
    assert body["caveats"][0] == {**body["caveats"][0], "code": "stale_source"}
    assert body["caveats"][0]["params"] == {"retailer": shop, "asOf": "2026-09-22"}


def test_the_latest_date_view_keeps_the_imported_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale Ulta read at its own last date never brings back its cleared was-prices, when
    they are withheld (``WAS_PRICE_WITHHELD``; empty since API 1.13.0)."""
    monkeypatch.setattr(dq, "WAS_PRICE_WITHHELD", frozenset({ULTA}))
    combined = snapshot_doc({"p1": BOTH, "p2": (ULTA,)}, dates=OLD)
    for product in combined["products"]:
        series = product["offers"][ULTA]["series"]
        series["regular"] = [{"amount": "99.00", "minor": 9900, "currency": "AED"}] * len(
            series["price"]
        )
    write(tmp_path, DatasetV3.model_validate(combined), COMBINED)
    write(tmp_path, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    (loaded,) = source.datasets()
    assert loaded.latest is not None
    assert loaded.unverified
    for ds in (loaded.dataset, loaded.latest):
        for product in ds.products:
            for cid, offer in product.offers.items():
                if cid in loaded.unverified:
                    assert offer.series.regular is None


def test_the_latest_date_view_is_floored_too(tmp_path: Path) -> None:
    """A stale Ulta read at its own last date never brings back a price the floor withholds
    (``pi_api.floor``, merge of #120 into #126)."""
    combined = snapshot_doc({"p1": BOTH, "p2": (ULTA,)}, dates=OLD)
    low = {"amount": "0.01", "minor": 1, "currency": "AED"}
    for product in combined["products"]:
        if product["id"] == "p2":
            series = product["offers"][ULTA]["series"]
            series["price"] = [low for _ in series["price"]]
    write(tmp_path, DatasetV3.model_validate(combined), COMBINED)
    write(tmp_path, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    (loaded,) = source.datasets()
    assert loaded.latest is not None
    assert [(f.retailer, f.offers) for f in loaded.floor.floored] == [(ULTA, 1)]
    for ds in (loaded.dataset, loaded.latest):
        (p2,) = (p for p in ds.products if p.id == "p2")
        assert all(v is None for v in p2.offers[ULTA].series.price)


#: A pair whose Ulta half is an old id (``pi_api.ids``, #158).
PAIR = "m-u-lip-1-ml-s-lip-1-ml"


@pytest.mark.parametrize("route", ["products", "admin/products"])
def test_an_old_product_id_reads_a_stale_source_at_its_own_last_date(
    tmp_path: Path, route: str
) -> None:
    """Merge of #120 into #126: the id resolves through ``pi_api.ids``, the product is read
    from the latest-date view, the stale caveat comes first, and ``resolvedFrom`` says so."""
    write(tmp_path, snapshot({PAIR: BOTH, "p2": (ULTA,)}, dates=OLD), COMBINED)
    write(tmp_path, snapshot({PAIR: (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    headers = bearer(role="admin") if route.startswith("admin") else bearer()
    response = client.get(f"/api/v1/{route}/u-lip-1-ml", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolvedFrom"] == {"requestedId": "u-lip-1-ml", "currentIds": [PAIR]}
    assert body["data"]["card"]["id"] == PAIR
    assert body["caveats"][0]["code"] == "stale_source"
    assert stale(body) == [STALE]
    (ulta,) = (o for o in body["data"]["offers"] if o["retailer"] == ULTA)
    assert ulta["price"]["minor"] == 10_000  # the view's own last date has no Ulta price
    assert ulta["evidence"]["capturedAt"] == "2026-09-22T00:00:00Z"


def test_the_products_export_reads_a_stale_source_as_of_and_flags_withheld_prices(
    tmp_path: Path,
) -> None:
    """Merge of #120 into #126: the products export carries the stale caveat first, and
    ``priceFlags`` where the floor withheld a stale source's price at its own last date (the
    view's last date has no Ulta price, so the view's own floor flags nothing there)."""
    combined = snapshot_doc({"p1": BOTH, "p2": (ULTA,)}, dates=OLD)
    for product in combined["products"]:
        if product["id"] == "p2":
            price = product["offers"][ULTA]["series"]["price"]
            price[-1] = {"amount": "0.01", "minor": 1, "currency": "AED"}
    write(tmp_path, DatasetV3.model_validate(combined), COMBINED)
    write(tmp_path, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)
    client, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    response = client.get("/api/v1/export/products?format=jsonl", headers=bearer())
    assert response.status_code == 200, response.text
    first, *rest = (json.loads(line) for line in response.text.splitlines())
    manifest = first["manifest"]
    rows = {r["id"]: r for r in rest}
    assert manifest["caveats"][0]["code"] == "stale_source"
    assert rows["p2"]["priceFlags"] == {ULTA: "invalid_low"}
    assert rows["p1"]["prices"][ULTA]["minor"] == 10_000  # as of Ulta's own last date
    cards = {c["id"]: c for c in get(client, "products")["data"]["items"]}
    assert cards["p2"]["priceFlags"] == {ULTA: "invalid_low"}


def stale_floored(root: Path) -> None:
    """Two files; Ulta (stale) has p2 at 0.01 on its own last date."""
    combined = snapshot_doc({"p1": BOTH, "p2": (ULTA,)}, dates=OLD)
    for product in combined["products"]:
        if product["id"] == "p2":
            price = product["offers"][ULTA]["series"]["price"]
            price[-1] = {"amount": "0.01", "minor": 1, "currency": "AED"}
    write(root, DatasetV3.model_validate(combined), COMBINED)
    write(root, snapshot({"p1": (SEPHORA,), "p3": (SEPHORA,)}, dates=NEW), SEPHORA_FILE)


def test_the_latest_date_index_is_built_at_load_and_a_missing_product_is_an_error(
    tmp_path: Path,
) -> None:
    """Reviewer N1 (#126): ``Loaded.as_of`` reads an index built at load, and a product missing
    from the latest-date view raises ``AsOfViewError``, never a guess or a not-found."""
    stale_floored(tmp_path)
    source = SnapshotSource(LocalStore(tmp_path), (), assigned=ASSIGNED)
    source.load_all()
    (loaded,) = source.datasets()
    assert loaded.latest is not None
    assert "latest_products" in vars(loaded)
    p1 = next(p for p in loaded.dataset.products if p.id == "p1")
    assert loaded.as_of(p1) is loaded.latest_products["p1"]
    assert loaded.as_of(p1) != p1  # Ulta read at its own last date
    broken = replace(loaded, latest=loaded.latest.model_copy(update={"products": ()}))
    with pytest.raises(AsOfViewError, match="'p1'"):
        broken.as_of(p1)


def test_the_withheld_price_count_matches_the_flags_of_latest_date_reads(tmp_path: Path) -> None:
    """Reviewer N2 (#126): the ``invalid_price_excluded`` count comes from the same floor as the
    flags (``current_floor``). The floor counts offers, and ``latest`` only restamps a stale
    source's last value, so both floors count the same offers; this pins that they agree."""
    stale_floored(tmp_path)
    client, source = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    (loaded,) = source.datasets()
    assert loaded.latest_floor is not None
    assert loaded.current_floor.floored == loaded.floor.floored
    body = get(client, f"products?retailer={ULTA}")
    (excluded,) = (c for c in body["caveats"] if c["code"] == "invalid_price_excluded")
    assert excluded["params"] == {"retailer": ULTA, "count": "1"}
    cards = {c["id"]: c for c in body["data"]["items"]}
    assert cards["p2"]["priceFlags"] == {ULTA: "invalid_low"}


def test_a_whole_file_has_no_stale_source(tmp_path: Path) -> None:
    write(tmp_path, snapshot({"p1": BOTH, "p2": (ULTA,)}, dates=OLD), COMBINED)
    client, source = make_client(tmp_path, paths=(COMBINED,))
    (loaded,) = source.datasets()
    assert (loaded.latest, loaded.stale) == (None, ())
    assert stale(get(client, f"compare?retailers={ULTA},{SEPHORA}")) == []


@pytest.mark.parametrize(
    ("shop", "as_of", "cutoff", "status"),
    [
        # Ulta is imported: its freshness is the import snapshot (``pi_api.dq``, API 1.5.0).
        (ULTA, "2026-09-22", "2026-09-22T00:00:00Z", "snapshot"),
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
