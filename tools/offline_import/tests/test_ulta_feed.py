"""Ulta import preserves source evidence without manufacturing values or variants."""

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy.engine import make_url

from offline_import.ulta_feed import export, image_url, load, prepare
from pi_db import DATABASE_URL_ENV, alembic_config


@pytest.fixture(scope="module")
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


def test_image_paths_encode_spaces_and_skip_failed_downloads() -> None:
    assert image_url({"image_url": "https://media.alshaya.com/Lip Gloss.jpg?w=800"}) == (
        "https://media.alshaya.com/Lip%20Gloss.jpg?w=800"
    )
    assert image_url({"images": [{"status": "failed", "url": "https://x.example/a.jpg"}]}) is None


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
    assert first["observations_inserted"] == 8
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
        assert conn.execute("SELECT count(*) FROM listing_content").fetchone() == (4,)
    target = tmp_path / "latest.json"
    report = export(db, target)
    assert report["offers_by_retailer"]["ulta_ae"] == 3
    assert report["unpublishable_fractional_aed_skus"] == ["fractional"]
    products = json.loads(target.read_text())["products"]
    offers = {p["offers"]["ulta_ae"]["sku"]: p["offers"]["ulta_ae"] for p in products}
    assert offers["child"]["image"] == "https://images.ulta.ae/a.jpg"
    assert offers["unknown"]["image"] is None
    assert offers["unknown"]["url"] is None
    assert offers["fractional"]["series"]["price"] == [None]
