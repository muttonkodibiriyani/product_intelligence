"""Ulta import preserves source evidence without manufacturing values or variants."""

import json
import os
import sys
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import psycopg
import pytest
from alembic import command
from scripts.demo_export.export import ListingRow, UltaContext
from scripts.demo_export.test_export import row
from sqlalchemy.engine import make_url

from offline_import import ulta_feed
from offline_import.ulta_catalogue import enrich
from offline_import.ulta_catalogue import export as export_catalogue
from offline_import.ulta_feed import export, load, prepare
from pi_dataset.catalogue import CatalogueDataset
from pi_db import DATABASE_URL_ENV, alembic_config


@pytest.fixture
def db() -> Iterator[str]:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip("database not configured")
    base = make_url(url).set(drivername="postgresql")
    admin_url = base.render_as_string(hide_password=False)
    try:
        psycopg.connect(admin_url, connect_timeout=3).close()
    except psycopg.OperationalError:
        if os.environ.get("CI"):
            raise
        pytest.skip("database unreachable")
    name = "pi_test_ulta_" + uuid.uuid4().hex[:12]
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    target = base.set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(target), "head")
        yield target
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def source_record(sku: str, **values: Any) -> dict[str, Any]:
    record = {
        "sku": sku,
        "name": "Colour Lipstick",
        "brand": "Example Beauty",
        "brand_names": ["Example Beauty"],
        "product_type": "simple",
        "url": f"https://www.ulta.ae/en/{sku}",
        "size": "3",
        "size_unit": "g",
        "price": {"current": 51, "regular": 60, "source": "catalogue"},
        "stock": {
            "in_stock": True,
            "reported_quantity": 0,
            "checked_at": "2026-10-01T00:24:00Z",
        },
        "provenance": {"retrieved_at": "2026-10-01T00:00:00Z"},
        "images": [{"status": "downloaded", "download_url": "https://images.ulta.ae/a.jpg"}],
    }
    record.update(values)
    return record


def feed(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "source.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_preparation_preserves_money_gaps_and_original_times(tmp_path: Path) -> None:
    source = feed(
        tmp_path,
        [
            source_record("parent", product_type="configurable", variants=[{"sku": "child"}]),
            source_record(
                "child",
                parent_products=[{"sku": "parent"}],
                price={"current": 0, "regular": "0.001"},
            ),
        ],
    )
    folder = tmp_path / "prepared"
    report = prepare(source, folder)
    parent, child = json.loads((folder / "ulta-import.json").read_text())
    assert report["records"] == 2
    assert parent["aggregate_parent"] is True
    assert child["master_id"] == "parent"
    assert child["price_current"] is None
    assert child["price_regular"] == "0.001"
    assert child["source_record"]["price"]["current"] == 0
    assert child["availability"] == "in_stock"
    assert child["observed_at"] == "2026-10-01T00:00:00+00:00"
    assert child["stock_observed_at"] == "2026-10-01T00:24:00+00:00"


@pytest.mark.parametrize(
    ("stock", "availability"),
    [
        ({"in_stock": True}, "in_stock"),
        ({"in_stock": True, "stock_data": {"few_in_stock": True}}, "low_stock"),
        ({"in_stock": False}, "out_of_stock"),
        ({"in_stock": False, "stock_data": {"few_in_stock": True}}, "out_of_stock"),
        ({}, "unknown"),
        ({"in_stock": None}, "unknown"),
        ({"in_stock": "false"}, "unknown"),
        ({"in_stock": 0}, "unknown"),
    ],
)
def test_availability_is_the_source_reported_stock_state(
    tmp_path: Path, stock: dict[str, Any], availability: str
) -> None:
    """Only an explicit ``in_stock: false`` is out of stock; anything not a bool is unknown."""
    record = source_record("sku", stock={**stock, "checked_at": "2026-10-01T00:24:00Z"})
    folder = tmp_path / "prepared"
    prepare(feed(tmp_path, [record]), folder)
    (item,) = json.loads((folder / "ulta-import.json").read_text())
    assert item["availability"] == availability


def test_missing_capture_requires_evidence_and_duplicates_fail(tmp_path: Path) -> None:
    item = source_record("search-only", provenance={}, stock={})
    source = feed(tmp_path, [item])
    with pytest.raises(ValueError, match="no source capture time"):
        prepare(source, tmp_path / "prepared")
    index = tmp_path / "capture.json"
    provenance = {"retrieved_at": "2026-09-30T23:57:00Z", "basis": "original cache persistence"}
    index.write_text(json.dumps({"search-only": provenance}))
    prepare(source, tmp_path / "prepared", index)
    row = json.loads((tmp_path / "prepared/ulta-import.json").read_text())[0]
    assert row["source_record"]["supplemental_capture_provenance"] == provenance
    assert row["observed_at"] == "2026-09-30T23:57:00+00:00"
    duplicate = feed(tmp_path, [item, item])
    with pytest.raises(ValueError, match="duplicate SKU"):
        prepare(duplicate, tmp_path / "duplicate", index)


def stub_export(
    monkeypatch: pytest.MonkeyPatch, listing: ListingRow, labels: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        ulta_feed,
        "load_rows",
        lambda _, sources: ([listing] if listing.source_name in sources else [], []),
    )
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = [
        (listing.source_name, listing.source_listing_key, labels)
    ]
    monkeypatch.setattr(psycopg, "connect", lambda _: conn)


@pytest.mark.parametrize(
    ("source", "url", "expected"),
    [
        ("ulta_ae", "https://images.ulta.ae/a.jpg", None),
        ("ulta_ae", "https://img-product.sephora.me/a.jpg", None),
        ("sephora_me", "https://media.alshaya.com/a.jpg", None),
        ("sephora_me", "https://untrusted.example/a.jpg", None),
        (
            "ulta_ae",
            "https://media.alshaya.com/Lip Gloss.jpg?w=800",
            "https://media.alshaya.com/Lip%20Gloss.jpg?w=800",
        ),
        (
            "sephora_me",
            "https://img-product.sephora.me/a.jpg",
            "https://img-product.sephora.me/a.jpg",
        ),
    ],
)
def test_export_preserves_retailer_scoped_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: str, url: str, expected: str | None
) -> None:
    listing = replace(row(source=source), source_listing_key="sku-100", image=url)
    stub_export(monkeypatch, listing, {"image_url": url})
    target = tmp_path / "dataset.json"
    report = export(
        "unused",
        target,
        sources=(source,),
        ulta=UltaContext(
            blocked_since=ulta_feed.instant(ulta_feed.ULTA_BLOCKED_SINCE), blocked=False
        ),
    )
    product = json.loads(target.read_text())["products"][0]
    assert product["image"] == expected
    assert product["offers"][source]["image"] == expected
    assert report["offers_with_images"] == int(expected is not None)


def test_export_keeps_aggregate_parent_retained_by_shared_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    listing = replace(row(source="ulta_ae"), source_listing_key="sku-100")
    stub_export(monkeypatch, listing, {"aggregate_parent": True, "resolved_children": []})
    target = tmp_path / "dataset.json"
    report = export(
        "unused",
        target,
        sources=("ulta_ae",),
        ulta=UltaContext(
            blocked_since=ulta_feed.instant(ulta_feed.ULTA_BLOCKED_SINCE), blocked=False
        ),
    )
    assert report["offers_by_retailer"]["ulta_ae"] == 1


@pytest.mark.parametrize("unblocked", [False, True])
def test_export_does_not_select_ulta_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unblocked: bool
) -> None:
    stub_export(monkeypatch, row(source="ulta_ae"), {})
    context = (
        UltaContext(blocked_since=ulta_feed.instant(ulta_feed.ULTA_BLOCKED_SINCE), blocked=False)
        if unblocked
        else None
    )
    target = tmp_path / "dataset.json"
    with pytest.raises(ValueError, match="refusing to create an empty demo dataset"):
        export("unused", target, ulta=context)
    assert not target.exists()


def test_export_default_context_keeps_ulta_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stub_export(monkeypatch, row(source="sephora_me"), {})
    target = tmp_path / "dataset.json"
    export("unused", target)
    document = json.loads(target.read_text())
    retailer = next(r for r in document["meta"]["retailers"] if r["id"] == "ulta_ae")
    assert retailer["status"] == "blocked"
    assert all("ulta_ae" not in product["offers"] for product in document["products"])


@pytest.mark.parametrize("sources", [(), ("ulta_ae",), ("sephora_me", "ulta_ae")])
def test_export_rejects_empty_or_blocked_source_selection_before_database_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sources: tuple[str, ...]
) -> None:
    query = MagicMock(side_effect=AssertionError("must validate sources before querying"))
    monkeypatch.setattr(ulta_feed, "load_rows", query)
    connect = MagicMock(side_effect=AssertionError("must validate sources before connecting"))
    monkeypatch.setattr(psycopg, "connect", connect)
    target = tmp_path / "dataset.json"
    with pytest.raises(ValueError, match="--sources"):
        export("unused", target, sources=sources)
    query.assert_not_called()
    connect.assert_not_called()
    assert not target.exists()


@pytest.mark.parametrize("unblocked", [False, True])
def test_export_cli_takes_block_status_from_explicit_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unblocked: bool
) -> None:
    source = "ulta_ae" if unblocked else "sephora_me"
    stub_export(monkeypatch, row(source=source), {})
    target = tmp_path / "dataset.json"
    args = ["ulta-feed", "export", str(target), "--ulta-blocked-since", "2026-09-29T00:00:00Z"]
    if unblocked:
        args.extend(["--sources", "ulta_ae", "--ulta-unblocked"])
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setenv("PI_DATABASE_URL", "unused")
    ulta_feed.main()
    retailer = next(
        r for r in json.loads(target.read_text())["meta"]["retailers"] if r["id"] == "ulta_ae"
    )
    assert (retailer["status"] == "blocked") is not unblocked
    assert retailer["since"] == (None if unblocked else "2026-09-29")


def test_export_cli_refuses_ulta_source_without_unblock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "dataset.json"
    monkeypatch.setattr(sys, "argv", ["ulta-feed", "export", str(target), "--sources", "ulta_ae"])
    monkeypatch.setenv("PI_DATABASE_URL", "unused")
    with pytest.raises(SystemExit) as error:
        ulta_feed.main()
    assert error.value.code == 2
    assert "--sources ulta_ae needs --ulta-unblocked" in capsys.readouterr().err
    assert not target.exists()


def test_database_replay_evidence_and_combined_export(
    db: str,
    tmp_path: Path,
) -> None:
    source = feed(
        tmp_path,
        [
            source_record("parent", product_type="configurable", variants=[{"sku": "child"}]),
            source_record("child", parent_products=[{"sku": "parent"}]),
            source_record("fractional", price={"current": "0.001", "regular": "0.001"}),
            source_record("childless", product_type="configurable", variants=[{"sku": "missing"}]),
            source_record(
                "allowed-image",
                images=[
                    {
                        "status": "downloaded",
                        "roles": ["image"],
                        "download_url": "https://media.alshaya.com/a.jpg",
                    }
                ],
            ),
            source_record(
                "unknown",
                price={"current": 0},
                url=None,
                images=[{"status": "failed", "download_url": "https://images.ulta.ae/b.jpg"}],
            ),
        ],
    )
    folder = tmp_path / "prepared"
    prepare(source, folder)
    first = load(folder, db)
    assert first["observations_inserted"] == 12
    second = load(folder, db)
    assert second["observations_inserted"] == 0
    assert second["replay"] is True
    with psycopg.connect(db) as conn:
        facts = conn.execute(
            "SELECT o.observed_at=e.retrieved_at, o.price_current, o.availability_state::text "
            "FROM offer_observation o JOIN evidence e ON e.id=o.evidence_id "
            "JOIN source_listing l ON l.id=o.source_listing_id WHERE l.source_listing_key='child' "
            "ORDER BY o.observed_at"
        ).fetchall()
        assert all(row[0] for row in facts)
        assert facts[0][1:] == (51, "not_observed")
        assert facts[1][1:] == (None, "in_stock")
        assert conn.execute("SELECT count(*) FROM listing_content").fetchone() == (6,)
    target = tmp_path / "latest.json"
    with pytest.raises(ValueError, match="refusing to create an empty demo dataset"):
        export(db, target)
    assert not target.exists()
    report = export(
        db,
        target,
        sources=("ulta_ae",),
        ulta=UltaContext(
            blocked_since=ulta_feed.instant(ulta_feed.ULTA_BLOCKED_SINCE), blocked=False
        ),
    )
    assert report["offers_by_retailer"]["ulta_ae"] == 5
    assert report["unpublishable_fractional_aed_skus"] == ["fractional"]
    products = json.loads(target.read_text())["products"]
    offers = {p["offers"]["ulta_ae"]["sku"]: p["offers"]["ulta_ae"] for p in products}
    assert "childless" in offers
    assert "parent" not in offers
    assert offers["child"]["image"] is None
    assert offers["allowed-image"]["image"] == "https://media.alshaya.com/a.jpg"
    assert offers["unknown"]["image"] is None
    assert offers["unknown"]["url"] is None
    assert offers["fractional"]["series"]["price"] == [None]


def test_catalogue_append_replay_and_price_history_preserved(db: str, tmp_path: Path) -> None:
    image = {
        "asset_id": "image1",
        "download_url": "https://media.alshaya.com/a.jpg",
        "source_url": "https://media.alshaya.com/a.jpg",
        "sha256": "a" * 64,
        "width": 533,
        "height": 800,
        "bytes": 4000,
        "content_type": "image/jpeg",
        "status": "downloaded",
        "product_skus": ["parent", "child"],
    }
    parent = source_record(
        "parent",
        product_type="configurable",
        images=[image],
        variants=[{"sku": "child"}, {"sku": "missing"}],
    )
    child = source_record(
        "child", parent_products=[{"sku": "parent"}], images=[image], is_variant=True
    )
    folder = tmp_path / "prepared"
    prepare(feed(tmp_path, [parent, child]), folder)
    load(folder, db)
    audited = []
    for r in [parent, child]:
        audited.append(
            {
                "sku": r["sku"],
                "name": r["name"],
                "product_type": r["product_type"],
                "is_variant": bool(r.get("is_variant")),
                "source_ids": {"stock_id": 100},
                "parents": r.get("parent_products", []),
                "children": r.get("variants", []),
                "grouping_master_sku": "parent",
                "excluded_parent_summary": r["sku"] == "parent",
            }
        )
    audit = tmp_path / "audit.jsonl"
    audit.write_text("".join(json.dumps(r) + "\n" for r in audited))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([image]))
    with psycopg.connect(db) as conn:
        before = conn.execute(
            "SELECT row_to_json(o) FROM offer_observation o ORDER BY idempotency_key"
        ).fetchall()
        original = conn.execute(
            "SELECT listing_id,observed_at,labels FROM listing_content ORDER BY listing_id"
        ).fetchall()
    assert enrich(db, audit, manifest, "b" * 64)["content_rows_to_append"] == 2
    assert enrich(db, audit, manifest, "b" * 64, apply=True)["content_rows_to_append"] == 2
    assert enrich(db, audit, manifest, "b" * 64, apply=True)["content_rows_to_append"] == 0
    output = tmp_path / "catalogue.json"
    export_catalogue(db, output)
    catalogue = CatalogueDataset.model_validate_json(output.read_bytes())
    assert set(catalogue.records) == {"parent", "child"}
    assert len(catalogue.records["parent"].children) == 2
    assert catalogue.records["child"].captured_at.isoformat() == "2026-10-01T00:00:00+00:00"
    assert catalogue.imported_at > catalogue.records["child"].captured_at
    with psycopg.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT row_to_json(o) FROM offer_observation o ORDER BY idempotency_key"
            ).fetchall()
            == before
        )
        for lid, observed_at, labels in original:
            assert conn.execute(
                "SELECT labels FROM listing_content WHERE listing_id=%s AND observed_at=%s",
                (lid, observed_at),
            ).fetchone() == (labels,)
        assert conn.execute("SELECT count(*) FROM listing_content").fetchone() == (4,)
