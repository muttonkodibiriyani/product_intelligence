"""Loader contract on trimmed real ulta.ae pages, against a throwaway migrated database.

Needs PI_DATABASE_URL (``make up``); skips when unset or unreachable, except in CI.
"""

import gzip
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url
from ulta_snapshot import load
from ulta_snapshot.load import Loader, Refused, guard

from pi_db import DATABASE_URL_ENV, alembic_config

FIXTURES = Path(__file__).parents[3] / "packages/pi_connector_ulta/tests/fixtures"
AT = "2026-09-30T20:40:00+00:00"


def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@contextmanager
def _database() -> Iterator[str]:
    """A throwaway migrated database beside PI_DATABASE_URL's (never that database itself)."""
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


@pytest.fixture(scope="module")
def db() -> Iterator[str]:
    with _database() as url:
        yield url


@pytest.fixture
def fresh_db() -> Iterator[str]:
    with _database() as url:
        yield url


def _rec(fixture: str | None, lang: str, html: str = "") -> dict[str, Any]:
    body = (FIXTURES / fixture).read_text() if fixture else html
    return {
        "at": AT,
        "url": f"https://www.ulta.ae/{lang}/buy-x",
        "lang": lang,
        "status": 200,
        "engine": "webkit",
        "egress": "iproyal_ae",
        "proxy_bytes": 1,
        "html": body,
        "captures": [],
    }


def _snapshot(
    root: Path, records: list[dict[str, Any]], name: str = "snap", snapshot_id: str | None = None
) -> Path:
    snap = root / name
    (snap / "pdp").mkdir(parents=True)
    with gzip.open(snap / "pdp/part-0000.jsonl.gz", "wt", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    (snap / "progress.json").write_text(
        json.dumps(
            {
                "started": AT,
                "updated": AT,
                "stopped": "complete",
                "snapshot_id": snapshot_id,
                "counts": {
                    "en": {"discovered": 3, "pdp_ok": 2, "pdp_parsed": 2, "block_cloudflare": 1},
                    "ar": {"discovered": 1, "pdp_ok": 1, "pdp_parsed": 1},
                },
            }
        )
    )
    return snap


def test_load_is_idempotent_and_never_invents_stock_or_prices(db: str, tmp_path: Path) -> None:
    block = "<html><head><title>Attention Required! | Cloudflare</title></head></html>"
    snap = _snapshot(
        tmp_path,
        [
            _rec("ulta_ae_pdp_en_morphe_trio.html", "en"),
            _rec("ulta_ae_pdp_ar_morphe_trio.html", "ar"),
            _rec("ulta_ae_pdp_en_kylie_tint.html", "en"),
            _rec(None, "en", block),
        ],
    )
    with psycopg.connect(db) as conn:
        loader = Loader(conn, snap, "gs://test/ulta")
        assert loader.load() == {"pdp": 26}
        loader.finish()
        # Replay: a new loader over the same snapshot adds nothing.
        (tmp_path / f".loaded-{snap.name}.json").unlink()
        Loader(conn, snap, "gs://test/ulta").load()
        q = conn.execute
        assert q("SELECT count(*) FROM offer_observation").fetchone() == (26,)
        assert q("SELECT count(*) FROM source_listing").fetchone() == (19,)
        # Only the selected variant of each page has a price; the rest are NULL + unknown.
        priced = q("SELECT count(*) FROM offer_observation WHERE price_current IS NOT NULL")
        assert priced.fetchone() == (3,)
        unknown = q(
            "SELECT count(*) FROM offer_observation"
            " WHERE price_current IS NULL AND field_state->>'price_current'='unknown'"
        )
        assert unknown.fetchone() == (23,)
        # Stock comes from the swatches (observed); the block page wrote nothing.
        oos = q(
            "SELECT count(*) FROM offer_observation WHERE availability_state='out_of_stock'"
            " AND field_state->>'availability_state'='observed'"
        )
        assert oos.fetchone() == (10,)
        assert q("SELECT count(*) FROM evidence").fetchone() == (3,)
        # Brand from the EN page, Arabic name from the AR page, keyed by the locale-free slug.
        assert q(
            "SELECT name, name_ar FROM brand WHERE 'ulta_ae:morphe' = ANY(aliases)"
        ).fetchone() == ("Morphe", "مورفي")
        listing = q(
            "SELECT name_original, name_ar, lang FROM source_listing"
            " WHERE source_listing_key='345530690'"
        ).fetchone()
        assert listing is not None
        assert listing[0] == "Cheek Thrills Multi-Finish Face Trio"
        assert listing[1]
        assert listing[2] == "en"
        ctx = q("SELECT ladder_rung_current FROM source_context WHERE locale='en-AE'").fetchone()
        assert ctx == (5,)
        runs = q(
            "SELECT r.status, r.ladder_rung_used, r.discovered, r.fetched, r.blocked_count"
            " FROM crawl_run r JOIN source_context c ON c.id = r.source_context_id"
            " ORDER BY c.locale DESC"
        ).fetchall()
        assert runs == [("succeeded", 5, 3, 2, 1), ("succeeded", 5, 1, 1, 0)]  # en-AE, ar-AE
        # Evidence hashes the rendered DOM, never sha256 of nothing.
        empty = hashlib.sha256(b"").hexdigest()
        assert q("SELECT count(*) FROM evidence WHERE content_hash=%s", (empty,)).fetchone() == (0,)
        method = q("SELECT DISTINCT fetch_method FROM evidence").fetchall()
        assert method == [("residential_proxy",)]


def test_cumulative_uploads_of_one_snapshot_load_each_part_once(db: str, tmp_path: Path) -> None:
    recs = [_rec("ulta_ae_pdp_en_morphe_trio.html", "en")]
    first = _snapshot(tmp_path, recs, "up1", snapshot_id="ulta-ae-1")
    second = _snapshot(tmp_path, recs, "up2", snapshot_id="ulta-ae-1")  # a later upload
    with psycopg.connect(db) as conn:
        loaded = Loader(conn, first, "gs://test/ulta/up1").load()
        assert loaded["pdp"] > 0
        assert Loader(conn, second, "gs://test/ulta/up2").load() == {}
    assert (tmp_path / ".loaded-ulta-ae-1.json").exists()


# ---------------------------------------------------------------- guard: owner's ulta_ae rows
FEED_AT = "2026-09-30T12:00:00+00:00"
TABLES = (
    "source",
    "source_context",
    "crawl_run",
    "evidence",
    "brand",
    "source_listing",
    "listing_content",
    "offer_observation",
)


def _seed_feed(conn: psycopg.Connection[Any]) -> None:
    """ulta_ae rows shaped like the owner's offline ulta_feed import (offline_import.ulta_feed),
    on a SKU the morphe fixture also carries."""
    q = conn.execute
    sid = q(
        "INSERT INTO source (name, kind, base_url, notes) VALUES ('ulta_ae','web',"
        "'https://www.ulta.ae','User-supplied existing Ulta UAE website scrape') RETURNING id"
    ).fetchone()
    ctx = q(
        "INSERT INTO source_context (source_id, country, channel, locale, time_zone,"
        " ladder_rung_current, coverage_status, refresh_policy) VALUES (%s,'AE','online','en-AE',"
        "'Asia/Dubai',0,'partial',%s) RETURNING id",
        (sid[0] if sid else None, Jsonb({"mode": "offline_import", "currency": "AED"})),
    ).fetchone()
    run = q(
        "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
        " started_at, manifest_uri) VALUES (%s,'ulta_feed_import/1',0,%s,'file:///feed')"
        " RETURNING id",
        (ctx[0] if ctx else None, FEED_AT),
    ).fetchone()
    ev = q(
        "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
        " ladder_rung_used, fetch_method, retention_until) VALUES (%s,'file:///feed',%s,"
        "'file:///feed',%s,0,'offline_import',%s) RETURNING id",
        (run[0] if run else None, "f" * 64, FEED_AT, "2027-01-01T00:00:00+00:00"),
    ).fetchone()
    q("INSERT INTO brand (name, aliases) VALUES ('Morphe', ARRAY['ulta_ae:Morphe'])")
    lid = q(
        "INSERT INTO source_listing (source_id, source_listing_key, source_sku, url,"
        " name_original, lang, category_path_source, first_seen_at, last_seen_at)"
        " VALUES (%s,'345530690','345530690','https://www.ulta.ae/en/feed-url','Feed name','en',"
        "'Feed > Path',%s,%s) RETURNING id",
        (sid[0] if sid else None, FEED_AT, FEED_AT),
    ).fetchone()
    q(
        "INSERT INTO listing_content (listing_id, observed_at, labels, content_hash)"
        " VALUES (%s,%s,%s,%s)",
        (
            lid[0] if lid else None,
            FEED_AT,
            Jsonb({"brand": "Morphe", "sku": "345530690"}),
            "c" * 64,
        ),
    )
    q(
        "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
        " source_listing_id, observed_at, ingested_at, price_current, price_type, currency,"
        " availability_state, field_state, evidence_id) VALUES ('feed-1',%s,%s,%s,%s,now(),"
        "99.00,'full','AED','in_stock','{}',%s)",
        (
            run[0] if run else None,
            ctx[0] if ctx else None,
            lid[0] if lid else None,
            FEED_AT,
            ev[0] if ev else None,
        ),
    )
    conn.commit()


def _rows(conn: psycopg.Connection[Any]) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table the loader writes, with its xmin (any UPDATE changes it)."""
    return {
        t: conn.execute(f"SELECT xmin::text, x::text FROM {t} x ORDER BY 2").fetchall()  # noqa: S608
        for t in TABLES
    }


def test_owner_feed_rows_stay_byte_unchanged(fresh_db: str, tmp_path: Path) -> None:
    snap = _snapshot(
        tmp_path,
        [
            _rec("ulta_ae_pdp_en_morphe_trio.html", "en"),
            _rec("ulta_ae_pdp_ar_morphe_trio.html", "ar"),
        ],
    )
    with psycopg.connect(fresh_db) as conn:
        _seed_feed(conn)
        before = _rows(conn)
        with pytest.raises(Refused) as exc:
            Loader(conn, snap, "gs://test/ulta").load()
        conn.rollback()
        assert _rows(conn) == before  # same rows, same bytes, same xmin; nothing added
    assert set(exc.value.foreign) == set(load.FOREIGN_KINDS)
    assert not (tmp_path / f".loaded-{snap.name}.json").exists()


def test_main_exits_nonzero_and_writes_nothing(
    fresh_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _snapshot(tmp_path, [_rec("ulta_ae_pdp_en_morphe_trio.html", "en")])
    with psycopg.connect(fresh_db) as conn:
        _seed_feed(conn)
        before = _rows(conn)
    monkeypatch.setenv("PI_DATABASE_URL", fresh_db)
    monkeypatch.setattr(sys, "argv", ["load", str(snap), "gs://test/ulta", "--finish"])
    assert load.main() == 2
    with psycopg.connect(fresh_db) as conn:
        assert _rows(conn) == before


def _own_load(conn: psycopg.Connection[Any], tmp_path: Path) -> int:
    """Load the morphe page as this loader would; returns one of its en-AE listing ids."""
    Loader(
        conn,
        _snapshot(tmp_path, [_rec("ulta_ae_pdp_en_morphe_trio.html", "en")], "own"),
        "gs://test/own",
    ).load()
    row = conn.execute("SELECT min(id) FROM source_listing").fetchone()
    assert row is not None
    return int(row[0])


FOREIGN_ROW = {
    "source_context": "INSERT INTO source_context (source_id, country, channel, locale, time_zone,"
    " ladder_rung_current, coverage_status, refresh_policy) SELECT id,'AE','online','en-AE',"
    "'Asia/Dubai',0,'partial','{\"mode\": \"offline_import\"}' FROM source WHERE name='ulta_ae'",
    "crawl_run": "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
    " started_at, manifest_uri) SELECT min(id),'ulta_feed_import/1',0,now(),'file:///feed'"
    " FROM source_context",
    "source_listing": "INSERT INTO source_listing (source_id, source_listing_key, url,"
    " name_original, lang, first_seen_at, last_seen_at) SELECT id,'feed-only',"
    "'https://www.ulta.ae/en/x','Feed','en',now(),now() FROM source WHERE name='ulta_ae'",
    "listing_content": "INSERT INTO listing_content (listing_id, observed_at, labels, content_hash)"
    " VALUES (%(lid)s, now(), '{\"brand\": \"Morphe\"}', 'feedhash')",
    "brand_alias": "INSERT INTO brand (name, aliases) VALUES ('Feed Brand', ARRAY['ulta_ae:Feed'])",
}


@pytest.mark.parametrize("kind", [*FOREIGN_ROW, "offer_observation"])
def test_each_foreign_row_kind_alone_refuses(fresh_db: str, tmp_path: Path, kind: str) -> None:
    with psycopg.connect(fresh_db) as conn:
        lid = _own_load(conn, tmp_path)
        guard(conn)  # this loader's own rows pass (replay is allowed)
        if kind == "offer_observation":  # an offer on our listing from another source's run
            src = conn.execute(
                "INSERT INTO source (name, kind, base_url) VALUES ('other','web','https://x')"
                " RETURNING id"
            ).fetchone()
            ctx = conn.execute(
                "INSERT INTO source_context (source_id, country, channel, locale, time_zone,"
                " ladder_rung_current, coverage_status, refresh_policy) VALUES (%s,'AE','online',"
                "'en-AE','Asia/Dubai',0,'partial','{}') RETURNING id",
                (src[0] if src else None,),
            ).fetchone()
            run = conn.execute(
                "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
                " started_at, manifest_uri) VALUES (%s,'x/1',0,now(),'file:///x') RETURNING id",
                (ctx[0] if ctx else None,),
            ).fetchone()
            conn.execute(
                "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
                " source_listing_id, observed_at, ingested_at, availability_state, field_state)"
                " VALUES ('foreign-offer',%s,%s,%s,%s,now(),'in_stock',"
                '\'{"price_current": "unknown"}\')',
                (run[0] if run else None, ctx[0] if ctx else None, lid, AT),
            )
        else:
            conn.execute(FOREIGN_ROW[kind], {"lid": lid})
        conn.commit()
        with pytest.raises(Refused) as exc:
            guard(conn)
    assert exc.value.foreign == {kind: 1}


def test_prod_database_is_refused_before_any_query() -> None:
    class Info:
        dbname = "pi"

    class Conn:
        info = Info()

        def execute(self, *args: object) -> None:
            raise AssertionError("guard queried the prod database")

    with pytest.raises(Refused, match="prod"):
        guard(Conn())  # type: ignore[arg-type]


#: offline_import.ulta_catalogue's statement, verbatim: renaming either side fails a test.
IMPORTER_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('ulta-catalogue-import'))"


def test_writer_lock_is_the_ulta_catalogue_importers_lock() -> None:
    importer = Path(__file__).parents[3] / "tools/offline_import/offline_import/ulta_catalogue.py"
    assert f'"{IMPORTER_LOCK_SQL}"' in importer.read_text()
    assert f"hashtext('{load.WRITER_LOCK}')" in IMPORTER_LOCK_SQL


def _lock_free(url: str) -> bool:
    """True if another session can take the ulta_catalogue writer lock right now."""
    with psycopg.connect(url) as other:
        row = other.execute(
            "SELECT pg_try_advisory_xact_lock(hashtext(%s))", (load.WRITER_LOCK,)
        ).fetchone()
        return bool(row and row[0])


def test_concurrent_ulta_writer_refuses_and_writes_nothing(fresh_db: str, tmp_path: Path) -> None:
    snap = _snapshot(tmp_path, [_rec("ulta_ae_pdp_en_morphe_trio.html", "en")])
    with psycopg.connect(fresh_db) as importer, psycopg.connect(fresh_db) as conn:
        # offline_import.ulta_catalogue's lock, held in an open transaction.
        importer.execute(IMPORTER_LOCK_SQL)
        before = _rows(conn)
        with pytest.raises(Refused, match="lock"):
            Loader(conn, snap, "gs://test/ulta")
        conn.rollback()
        assert _rows(conn) == before
    assert not (tmp_path / f".loaded-{snap.name}.json").exists()


def test_writer_lock_is_held_across_part_commits(fresh_db: str, tmp_path: Path) -> None:
    snap = _snapshot(tmp_path, [_rec("ulta_ae_pdp_en_morphe_trio.html", "en")])
    with psycopg.connect(fresh_db) as conn:
        loader = Loader(conn, snap, "gs://test/ulta")
        conn.commit()
        assert not _lock_free(fresh_db)  # the gap between guard and the writes is closed
        loader.load()  # commits per part
        assert not _lock_free(fresh_db)
        loader.finish()
        assert not _lock_free(fresh_db)
    assert _lock_free(fresh_db)  # released with the connection
