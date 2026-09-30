"""Loader contract on trimmed real ulta.ae pages, against a throwaway migrated database.

Needs PI_DATABASE_URL (``make up``); skips when unset or unreachable, except in CI.
"""

import gzip
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
from ulta_snapshot.load import Loader

from pi_db import DATABASE_URL_ENV, alembic_config

FIXTURES = Path(__file__).parents[3] / "packages/pi_connector_ulta/tests/fixtures"
AT = "2026-09-30T20:40:00+00:00"


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


def _snapshot(root: Path, records: list[dict[str, Any]]) -> Path:
    snap = root / "snap"
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
                "counts": {"discovered": 3, "pdp_ok": 3, "pdp_parsed": 3},
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
        run = q("SELECT status, ladder_rung_used FROM crawl_run LIMIT 1").fetchone()
        assert run == ("succeeded", 5)
        method = q("SELECT DISTINCT fetch_method FROM evidence").fetchall()
        assert method == [("residential_proxy",)]
