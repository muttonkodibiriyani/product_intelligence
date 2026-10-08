"""Loader contract on the synthetic Acme feed, against a throwaway migrated database.

Needs PI_DATABASE_URL (``make up``); skips when unset or unreachable, except in CI.
"""

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy.engine import make_url

from offline_import.__main__ import main
from offline_import.load import Loader, content_hash, idempotency_key
from offline_import.mapping import ImportMapping, load_mapping
from offline_import.validate import validate_file
from pi_db import DATABASE_URL_ENV, alembic_config

FIXTURES = Path(__file__).parent / "fixtures"
CSV = FIXTURES / "acme_feed.csv"
CLEAN = FIXTURES / "acme_clean.csv"  # every row valid
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


def _full_mapping(tmp_path: Path, name: str, **changes: Any) -> Path:
    config = json.loads(MAPPING.read_text()) | {"complete_catalogue": True} | changes
    config["source"] = config["source"] | {"name": name}
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(config))
    return path


def test_complete_catalogue_run_succeeds_and_cli_loads(
    db: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mapping_path = _full_mapping(tmp_path, "acme_full_catalogue")
    monkeypatch.setenv(DATABASE_URL_ENV, db)
    report_path = tmp_path / "report.json"
    assert main([str(CLEAN), "--mapping", str(mapping_path), "--report", str(report_path)]) == 0
    out = json.loads(report_path.read_text())
    assert out["dry_run"] is False
    assert (out["load"]["observations_inserted"], out["load"]["rejected"]) == (4, 0)
    [(status, uri)] = _rows(
        db,
        "SELECT r.status, e.storage_uri FROM crawl_run r JOIN evidence e ON e.crawl_run_id = r.id"
        " WHERE r.id=%s",
        (out["load"]["crawl_run_id"],),
    )
    assert status == "succeeded"
    assert uri == CLEAN.resolve().as_uri()  # evidence storage only; never a listing URL
    urls = {u for (u,) in _rows(db, "SELECT url FROM source_listing")}
    assert urls
    assert all(u.startswith("https://acme-beauty.example/p/") for u in urls)
    assert json.loads(capsys.readouterr().out)["load"]["replay"] is False


def test_complete_catalogue_with_a_rejected_row_is_partial(db: str, tmp_path: Path) -> None:
    mapping = load_mapping(_full_mapping(tmp_path, "acme_full_but_dirty"))
    out = _load(db, mapping)  # acme_feed.csv: 5 accepted, 6 rejected
    [(status,)] = _rows(db, "SELECT status FROM crawl_run WHERE id=%s", (out["crawl_run_id"],))
    assert status == "partial"


def test_complete_catalogue_with_no_rows_is_partial(db: str, tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text(CLEAN.read_text().splitlines()[0] + "\n")
    mapping = load_mapping(_full_mapping(tmp_path, "acme_full_but_empty"))
    out = _load(db, mapping, empty, "gs://pi-imports-test/acme/empty.csv")
    [(status,)] = _rows(db, "SELECT status FROM crawl_run WHERE id=%s", (out["crawl_run_id"],))
    assert status == "partial"


def test_feed_without_price_columns_records_price_unknown(db: str, tmp_path: Path) -> None:
    config = json.loads(MAPPING.read_text())
    config["source"] = config["source"] | {"name": "acme_stock_only"}
    for col in ("price_current", "price_regular", "price_promo"):
        config["columns"].pop(col, None)
    path = tmp_path / "stock_only.json"
    path.write_text(json.dumps(config))
    out = _load(db, load_mapping(path), CLEAN, "gs://pi-imports-test/acme/stock_only.csv")
    states = {
        fs["price_current"]
        for (fs,) in _rows(
            db,
            "SELECT field_state FROM offer_observation WHERE crawl_run_id=%s",
            (out["crawl_run_id"],),
        )
    }
    assert states == {"unknown"}


def _content_feed(tmp_path: Path, name: str, locale: str = "en-AE") -> tuple[ImportMapping, Path]:
    columns = (
        "listing_key", "url", "name", "price_current", "observed_at", "description", "gender",
        "concentration", "badges", "promotions", "image_urls",
    )  # fmt: skip
    mapping = ImportMapping.model_validate(
        {
            "source": {"name": name, "kind": "web"},
            "country": "AE",
            "locale": locale,
            "currency": "AED",
            "time_zone": "Asia/Dubai",
            "format": "json",
            "json_items_path": "items",
            "columns": {c: c for c in columns},
        }
    )
    item = {
        "listing_key": "C-1",
        "url": "https://acme-beauty.example/p/c-1",
        "name": "Amber Night",
        "price_current": "120.00",
        "observed_at": "2026-10-02T09:00:00+00:00",
        "description": "A warm amber eau de parfum.",
        "gender": "women",
        "concentration": "edp",
        "badges": ["new", "onlineexclusive"],
        "promotions": "Free Gifts",
        "image_urls": [
            "https://img.example/1.jpg",
            "file:///etc/x.jpg",
            "https://img.example/2.jpg",
        ],
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"items": [item]}))
    return mapping, path


def test_page_content_is_stored_where_the_sephora_load_puts_it(db: str, tmp_path: Path) -> None:
    mapping, path = _content_feed(tmp_path, "acme_content")
    report = validate_file(path, mapping)
    assert [w.message for w in report.warnings] == ["1 image URL(s) not http(s); dropped"]
    out = _load(db, mapping, path, "gs://pi-imports-test/acme/content.json")
    [(description, description_ar, badges, labels)] = _rows(
        db,
        "SELECT c.description, c.description_ar, c.badges, c.labels FROM listing_content c"
        " JOIN source_listing l ON l.id = c.listing_id WHERE l.source_listing_key = 'C-1'",
    )
    assert (description, description_ar) == ("A warm amber eau de parfum.", None)
    assert badges == ["new", "onlineexclusive"]
    assert (labels["gender"], labels["concentration"]) == ("women", "edp")
    assert labels["promotions"] == ["Free Gifts"]
    assert labels["images"] == [
        {"role": "main", "position": 0, "url": "https://img.example/1.jpg"},
        {"role": "alt", "position": 1, "url": "https://img.example/2.jpg"},
    ]
    [(at_time,)] = _rows(
        db,
        "SELECT badges_at_time FROM offer_observation WHERE crawl_run_id=%s",
        (out["crawl_run_id"],),
    )
    assert at_time == ["new", "onlineexclusive"]


def test_an_arabic_feed_stores_the_description_as_arabic(db: str, tmp_path: Path) -> None:
    mapping, path = _content_feed(tmp_path, "acme_content_ar", locale="ar-AE")
    _load(db, mapping, path, "gs://pi-imports-test/acme/content_ar.json")
    [(description, description_ar)] = _rows(
        db,
        "SELECT c.description, c.description_ar FROM listing_content c"
        " JOIN source_listing l ON l.id = c.listing_id JOIN source s ON s.id = l.source_id"
        " WHERE s.name = 'acme_content_ar'",
    )
    assert (description, description_ar) == (None, "A warm amber eau de parfum.")


def test_a_row_without_page_content_keeps_its_earlier_content_hash() -> None:
    labels = {"brand": "Acme", "import_row": 2}
    assert (
        content_hash(labels, None, None)
        == hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest()
    )
    assert content_hash(labels, "text", None) != content_hash(labels, None, None)


def test_url_template_encodes_the_key() -> None:
    ld = object.__new__(Loader)  # _url reads only the mapping; no database needed
    ld.m = load_mapping(MAPPING)
    row = SimpleNamespace(listing_key="AB/10 01?x#y", text={})
    assert ld._url(row) == "https://acme-beauty.example/p/AB%2F10%2001%3Fx%23y"  # type: ignore[arg-type]


def test_page_attributes_go_to_labels_the_style_id_to_master_id_and_inci_to_ingredients(
    db: str, tmp_path: Path
) -> None:
    attributes = {
        "style_id": "STYLE-9",
        "ingredients": "Aqua, Glycerin, Parfum, Limonene, Linalool, Citral",
        "gift_with_purchase": ["Beauty Treats, Complimentary"],
        "mpn": "VPN-1",
        "colour_code": "242",
        "colour_hex": "#C4A1A0",
        "finish": "matte",
        "lifecycle_class": "core",
        "exclusivity": "exclusive",
        "loyalty_points": "45",
        "installment_amount_minor": "3500",
        "bullets": ["Long wear", "Vegan"],
        "skin_type": ["All Skin Types"],
        "concern": ["Dryness"],
        "installment_provider": ["tabby", "tamara"],
    }
    mapping = ImportMapping.model_validate(
        {
            "source": {"name": "acme_attrs", "kind": "web"},
            "country": "AE",
            "locale": "en-AE",
            "currency": "AED",
            "time_zone": "Asia/Dubai",
            "format": "json",
            "json_items_path": "items",
            "columns": {c: c for c in ("listing_key", "url", "observed_at", *attributes)},
        }
    )
    item = {
        "listing_key": "A-1",
        "url": "https://acme-beauty.example/p/a-1",
        "observed_at": "2026-10-02T09:00:00+00:00",
        **attributes,
    }
    path = tmp_path / "attrs.json"
    path.write_text(json.dumps({"items": [item]}))
    _load(db, mapping, path, "gs://pi-imports-test/acme/attrs.json")
    [(ingredients, labels)] = _rows(
        db,
        "SELECT c.ingredients, c.labels FROM listing_content c"
        " JOIN source_listing l ON l.id = c.listing_id WHERE l.source_listing_key = 'A-1'",
    )
    assert ingredients == attributes["ingredients"]
    assert labels["master_id"] == "STYLE-9"
    assert "style_id" not in labels
    assert "ingredients" not in labels
    for key, value in attributes.items():
        if key not in {"style_id", "ingredients"}:
            assert labels[key] == value, key


def test_the_content_hash_of_a_row_without_ingredients_is_unchanged() -> None:
    labels = {"brand": "Acme"}
    before = _sha_json([labels, "desc", ["new"]])
    assert content_hash(labels, "desc", ["new"]) == before
    assert content_hash(labels, "desc", ["new"], None) == before
    assert content_hash(labels, "desc", ["new"], "Aqua") != before
    assert content_hash(labels, None, None, "Aqua") != content_hash(labels, None, None)


def _sha_json(parts: object) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _attrs_feed(tmp_path: Path, name: str, items: list[dict[str, Any]]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"items": items}))
    return path


def test_content_only_appends_a_re_derived_feed_and_touches_nothing_else(
    db: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    columns = ("listing_key", "url", "observed_at", "price_current", "style_id", "ingredients")
    config = {
        "source": {"name": "acme_rederive", "kind": "web"},
        "country": "AE",
        "locale": "en-AE",
        "currency": "AED",
        "time_zone": "Asia/Dubai",
        "format": "json",
        "json_items_path": "items",
        "columns": {c: c for c in (*columns, "finish")},
    }
    mapping = ImportMapping.model_validate(config)
    mapping_path = tmp_path / "rederive_mapping.json"
    mapping_path.write_text(json.dumps(config))
    monkeypatch.setenv(DATABASE_URL_ENV, db)
    page_at = "2026-10-03T10:00:00+00:00"
    base = [
        {"listing_key": k, "url": f"https://acme-beauty.example/p/{k}", "observed_at": page_at,
         "price_current": "120.00"}
        for k in ("R-1", "R-2")
    ]  # fmt: skip
    v1 = _attrs_feed(tmp_path, "v1.json", base)
    first = _load(db, mapping, v1, "gs://pi-imports-test/acme/v1.json")
    tables = ("crawl_run", "evidence", "source_listing", "offer_observation")
    counts = {t: _count(db, t) for t in tables}
    original = _rows(
        db,
        "SELECT c.listing_id, c.observed_at, c.recorded_at, c.labels, c.content_hash"
        " FROM listing_content c JOIN source_listing l ON l.id = c.listing_id"
        " WHERE l.source_listing_key LIKE 'R-%%' ORDER BY 1",
    )
    assert len(original) == 2

    # The same pages read by a newer reader: a new feed (new bytes) with the new fields, and a
    # row whose listing was never loaded.
    attrs = {"style_id": "STYLE-R", "finish": "matte",
             "ingredients": "Aqua, Glycerin, Parfum, Limonene, Linalool, Citral"}  # fmt: skip
    v2 = _attrs_feed(
        tmp_path,
        "v2.json",
        [r | attrs for r in base]
        + [base[0] | {"listing_key": "R-3", "url": "https://acme-beauty.example/p/R-3"}],
    )
    report_path = tmp_path / "v2.report.json"
    v2_uri = "gs://pi-imports-test/acme/v2.json"
    argv = [str(v2), "--mapping", str(mapping_path), "--content-only", "--uri", v2_uri]
    assert main([*argv, "--report", str(report_path)]) == 0
    got = json.loads(report_path.read_text())["load"]
    report = validate_file(v2, mapping)
    assert (got["content_inserted"], got["listings_not_loaded"], got["superseded"]) == (2, 1, 0)

    # No run, evidence, listing or offer row; the first import's content rows are untouched.
    assert {t: _count(db, t) for t in tables} == counts
    for lid, at, recorded, labels, digest in original:
        assert _rows(
            db,
            "SELECT labels, content_hash FROM listing_content WHERE listing_id=%s"
            " AND observed_at=%s AND recorded_at=%s",
            (lid, at, recorded),
        ) == [(labels, digest)]
    # The re-derived row keeps the page's time; only recorded_at is new, and the readers'
    # tiebreak (observed_at DESC, recorded_at DESC) makes it the latest.
    [(observed_at, recorded_at, ingredients, labels)] = _rows(
        db,
        "SELECT c.observed_at, c.recorded_at, c.ingredients, c.labels FROM listing_content c"
        " JOIN source_listing l ON l.id = c.listing_id WHERE l.source_listing_key = 'R-1'"
        " ORDER BY c.observed_at DESC, c.recorded_at DESC LIMIT 1",
    )
    assert observed_at == datetime.fromisoformat(page_at)
    assert recorded_at > original[0][2]
    assert "page_observed_at" not in labels
    assert labels["master_id"] == "STYLE-R"
    assert labels["finish"] == "matte"
    assert labels["import_sha256"] == report.sha256
    assert ingredients == attrs["ingredients"]

    # A replay of the re-derived feed adds nothing.
    content = _count(db, "listing_content")
    with psycopg.connect(db) as conn:
        again = Loader(conn, mapping, report, v2_uri).load_content()
    assert again["content_inserted"] == 0
    assert _count(db, "listing_content") == content
    # ... and so does a replay from another copy of the same bytes: the URI is not hashed.
    with psycopg.connect(db) as conn:
        moved = Loader(conn, mapping, report, "gs://pi-imports-test/elsewhere/v2.json")
        assert moved.load_content()["content_inserted"] == 0
    assert _count(db, "listing_content") == content

    # The bytes of a full import carry nothing new: refused, from the API and the CLI.
    with psycopg.connect(db) as conn, pytest.raises(ValueError, match="already imported"):
        Loader(conn, mapping, validate_file(v1, mapping), "x").load_content()
    capsys.readouterr()
    assert main([str(v1), "--mapping", str(mapping_path), "--content-only"]) == 2
    assert "already imported" in capsys.readouterr().err
    assert first["replay"] is False


def test_content_only_skips_and_counts_a_listing_whose_content_is_already_later(
    db: str, tmp_path: Path
) -> None:
    """A re-derivation never lands behind a later page: a listing whose content already has a
    later observed_at is skipped and counted, and the others are re-derived."""
    columns = ("listing_key", "url", "observed_at", "price_current", "finish")
    mapping = ImportMapping.model_validate(
        {
            "source": {"name": "acme_superseded", "kind": "web"},
            "country": "AE",
            "locale": "en-AE",
            "currency": "AED",
            "time_zone": "Asia/Dubai",
            "format": "json",
            "json_items_path": "items",
            "columns": {c: c for c in columns},
        }
    )
    page_at, later_at = "2026-10-03T10:00:00+00:00", "2026-10-05T10:00:00+00:00"
    base = [
        {"listing_key": k, "url": f"https://acme-beauty.example/p/{k}", "observed_at": page_at,
         "price_current": "120.00"}
        for k in ("S-1", "S-2")
    ]  # fmt: skip
    _load(db, mapping, _attrs_feed(tmp_path, "s1.json", base), "gs://pi-imports-test/s1.json")
    # A later crawl has already read S-2 again.
    later = [base[1] | {"observed_at": later_at, "price_current": "110.00"}]
    _load(db, mapping, _attrs_feed(tmp_path, "s2.json", later), "gs://pi-imports-test/s2.json")
    before = {key: _count_content(db, key) for key in ("S-1", "S-2")}

    v2 = _attrs_feed(tmp_path, "s3.json", [r | {"finish": "matte"} for r in base])
    with psycopg.connect(db) as conn:
        got = Loader(
            conn, mapping, validate_file(v2, mapping), "gs://pi-imports-test/s3.json"
        ).load_content()
    assert (got["content_inserted"], got["superseded"], got["listings_not_loaded"]) == (1, 1, 0)
    assert _count_content(db, "S-1") == before["S-1"] + 1
    assert _count_content(db, "S-2") == before["S-2"]
    [(observed_at, labels)] = _rows(
        db,
        "SELECT c.observed_at, c.labels FROM listing_content c"
        " JOIN source_listing l ON l.id = c.listing_id WHERE l.source_listing_key = 'S-2'"
        " ORDER BY c.observed_at DESC, c.recorded_at DESC LIMIT 1",
    )
    assert observed_at == datetime.fromisoformat(later_at)
    assert "finish" not in labels


def _count_content(db: str, key: str) -> int:
    [(n,)] = _rows(
        db,
        "SELECT count(*) FROM listing_content c JOIN source_listing l ON l.id = c.listing_id"
        " WHERE l.source_listing_key = %s",
        (key,),
    )
    return int(n)
