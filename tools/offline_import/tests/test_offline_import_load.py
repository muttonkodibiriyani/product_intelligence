"""Loader contract on the synthetic Acme feed, against a throwaway migrated database.

Needs PI_DATABASE_URL (``make up``); skips when unset or unreachable, except in CI.
"""

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy.engine import make_url

from offline_import.__main__ import main
from offline_import.load import Loader, idempotency_key
from offline_import.mapping import ImportMapping, load_mapping
from offline_import.validate import validate_file
from pi_db import DATABASE_URL_ENV, alembic_config

FIXTURES = Path(__file__).parent / "fixtures"
CSV = FIXTURES / "acme_feed.csv"
MAPPING = FIXTURES / "acme_mapping.json"
URI = "gs://pi-imports-test/acme/acme_feed.csv"


def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def db() -> Iterator[str]:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{DATABASE_URL_ENV} not set; run `make up` and export it")
    try:
        psycopg.connect(_libpq(url), connect_timeout=3).close()
    except psycopg.OperationalError:
        if os.environ.get("CI"):
            raise
        pytest.skip("database unreachable (run `make up`)")
    name = f"pi_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq(url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    test_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(test_url), "head")
        yield _libpq(test_url)
    finally:
        with psycopg.connect(_libpq(url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def _load(db: str, mapping: ImportMapping, path: Path = CSV, uri: str = URI) -> dict[str, Any]:
    report = validate_file(path, mapping)
    with psycopg.connect(db) as conn:
        return Loader(conn, mapping, report, uri).load()


def _rows(db: str, sql: str, args: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(db) as conn:
        return conn.execute(sql, args).fetchall()


def _count(db: str, table: str) -> int:
    return int(_rows(db, f"SELECT count(*) FROM {table}")[0][0])  # noqa: S608 - test constant


def test_load_and_idempotent_replay(db: str, tmp_path: Path) -> None:
    mapping = load_mapping(MAPPING)
    sha = hashlib.sha256(CSV.read_bytes()).hexdigest()
    first = _load(db, mapping)
    assert first["replay"] is False
    assert first["observations_inserted"] == 5
    assert (first["accepted"], first["rejected"]) == (5, 6)

    [(kind, base_url)] = _rows(
        db, "SELECT kind::text, base_url FROM source WHERE name='acme_beauty_partner_feed'"
    )
    assert (kind, base_url) == ("offline", "https://acme-beauty.example")
    [ctx] = _rows(
        db,
        "SELECT c.country, c.locale, c.time_zone, c.ladder_rung_current FROM source_context c"
        " JOIN source s ON s.id = c.source_id WHERE s.name='acme_beauty_partner_feed'",
    )
    assert ctx == ("AE", "en-AE", "Asia/Dubai", 0)
    [run] = _rows(
        db,
        "SELECT status, ladder_rung_used, discovered, accepted, quarantined, manifest_uri,"
        " finished_at IS NOT NULL FROM crawl_run WHERE id=%s",
        (first["crawl_run_id"],),
    )
    # An import is never a complete catalogue unless the mapping says so.
    assert run == ("partial", 0, 11, 5, 6, URI, True)
    [evidence] = _rows(
        db, "SELECT fetch_method::text, ladder_rung_used, content_hash, storage_uri FROM evidence"
    )
    assert evidence == ("offline_import", 0, sha, URI)

    offers = {
        r[0]: r[1:]
        for r in _rows(
            db,
            "SELECT l.source_listing_key, o.price_current, o.price_regular_stated, o.price_promo,"
            " o.price_type::text, o.currency, o.availability_state::text, o.low_stock_flag,"
            " o.field_state, o.idempotency_key, o.observed_at = '2026-09-15T04:00:00Z'"
            " FROM offer_observation o JOIN source_listing l ON l.id = o.source_listing_id",
        )
    }
    assert set(offers) == {"AB-1001", "AB-1002", "AB-1003", "AB-1008", "AB-1009"}
    assert offers["AB-1001"][:7] == (
        Decimal("89.0000"), Decimal("89.0000"), None, "full", "AED", "in_stock", None
    )  # fmt: skip
    assert offers["AB-1002"][:7] == (
        Decimal("99.0000"), Decimal("120.0000"), Decimal("99.0000"), "promotional", "AED",
        "out_of_stock", None,
    )  # fmt: skip
    assert offers["AB-1002"][7] == {"availability_state": "observed"}
    # Missing price: NULL with a reason, never 0; no currency without a price.
    assert offers["AB-1003"][:6] == (None, None, None, None, None, "in_stock")
    assert offers["AB-1003"][7]["price_current"] == "not_published"
    assert offers["AB-1008"][5:7] == ("low_stock", True)
    # Nothing published about stock: not observed, never out of stock.
    assert offers["AB-1009"][5] == "not_observed"
    assert offers["AB-1009"][7] == {"availability_state": "not_published"}
    assert offers["AB-1001"][8] == idempotency_key("acme_beauty_partner_feed", sha, "AB-1001")
    assert all(o[9] for o in offers.values())  # observed_at from the mapping, not load time

    [(url, sku, name_ar, lang, cat)] = _rows(
        db,
        "SELECT url, source_sku, name_ar, lang, category_path_source FROM source_listing"
        " WHERE source_listing_key='AB-1001'",
    )
    assert (url, sku, lang, cat) == (
        "https://acme-beauty.example/p/AB-1001",
        "ACME-LIP-01",
        "en",
        "Makeup > Lips",
    )
    assert name_ar == "أحمر شفاه أكمي"
    labels = {
        r[0]: r[1]
        for r in _rows(
            db,
            "SELECT l.source_listing_key, c.labels FROM listing_content c"
            " JOIN source_listing l ON l.id = c.listing_id",
        )
    }
    assert labels["AB-1001"]["brand"] == "Acme Beauty"
    assert labels["AB-1001"]["gtin"] == "2000000001012"
    assert labels["AB-1001"]["shade"] == "Coral Dawn"
    assert labels["AB-1001"]["size"] == "3.5 g"
    assert labels["AB-1001"]["stock_qty"] == 12
    assert labels["AB-1001"]["import_sha256"] == sha
    assert "gtin" not in labels["AB-1009"]  # invalid GTIN dropped, with a warning

    counts = {t: _count(db, t) for t in ("crawl_run", "evidence", "source_listing",
                                         "listing_content", "offer_observation")}  # fmt: skip

    # Same bytes again, even from another path: nothing new is written.
    copy = tmp_path / "renamed.csv"
    shutil.copyfile(CSV, copy)
    replay = _load(db, mapping, copy, copy.as_uri())
    assert replay["replay"] is True
    assert replay["observations_inserted"] == 0
    assert (replay["crawl_run_id"], replay["evidence_id"]) == (
        first["crawl_run_id"],
        first["evidence_id"],
    )
    assert {t: _count(db, t) for t in counts} == counts


def test_complete_catalogue_run_succeeds_and_cli_loads(
    db: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = json.loads(MAPPING.read_text()) | {"complete_catalogue": True}
    config["source"] = config["source"] | {"name": "acme_full_catalogue"}
    config["url_template"] = None
    mapping_path = tmp_path / "full.json"
    mapping_path.write_text(json.dumps(config))
    monkeypatch.setenv(DATABASE_URL_ENV, db)
    report_path = tmp_path / "report.json"
    assert main([str(CSV), "--mapping", str(mapping_path), "--report", str(report_path)]) == 0
    out = json.loads(report_path.read_text())
    assert out["dry_run"] is False
    assert out["load"]["observations_inserted"] == 5
    [(status, uri)] = _rows(
        db,
        "SELECT r.status, e.storage_uri FROM crawl_run r JOIN evidence e ON e.crawl_run_id = r.id"
        " WHERE r.id=%s",
        (out["load"]["crawl_run_id"],),
    )
    assert status == "succeeded"
    assert uri == CSV.resolve().as_uri()
    [(url,)] = _rows(
        db,
        "SELECT l.url FROM source_listing l JOIN source s ON s.id = l.source_id"
        " WHERE s.name='acme_full_catalogue' AND l.source_listing_key='AB-1003'",
    )
    assert url == f"{uri}#listing_key=AB-1003"  # no url column and no template
    assert json.loads(capsys.readouterr().out)["load"]["replay"] is False


def test_url_template_encodes_the_key() -> None:
    ld = object.__new__(Loader)  # _url reads only the mapping; no database needed
    ld.m = load_mapping(MAPPING)
    row = SimpleNamespace(listing_key="AB/10 01?x#y", text={})
    assert ld._url(row) == "https://acme-beauty.example/p/AB%2F10%2001%3Fx%23y"  # type: ignore[arg-type]
