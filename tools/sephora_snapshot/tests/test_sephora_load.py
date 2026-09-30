"""Loader contract on synthetic snapshot folders, against a throwaway migrated database.

Needs PI_DATABASE_URL (``make up``); skips when unset or unreachable, except in CI.
"""

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from sephora_snapshot.load import Loader
from sephora_synth import pdp_rec, trpc_rec, write_part
from sqlalchemy.engine import make_url

from pi_db import DATABASE_URL_ENV, alembic_config


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


def _folder(root: Path, progress: dict[str, Any]) -> Path:
    root.mkdir(parents=True)
    started = {"started": "2026-09-30T21:00:00+00:00", "updated": "2026-09-30T23:00:00+00:00"}
    (root / "progress.json").write_text(json.dumps({**started, **progress}))
    return root


def _load(conn: psycopg.Connection[Any], root: Path, *, finish: bool = True) -> dict[str, int]:
    ld = Loader(conn, root, f"gs://test-bucket/{root.name}")
    stats = ld.load()
    if finish:
        ld.finish()
    return stats


def _runs(conn: psycopg.Connection[Any], name: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT manifest_uri, status FROM crawl_run WHERE manifest_uri LIKE %s",
        (f"gs://test-bucket/{name}/%",),
    ).fetchall()
    return {uri.rsplit("=", 1)[1]: status for uri, status in rows}


def test_full_run_loads_prices_then_stock_and_replays_idempotently(db: str, tmp_path: Path) -> None:
    done = {"stopped": "complete", "updated": "2026-09-30T23:00:00+00:00"}
    root = _folder(tmp_path / "full", {**done, "counts": {"seed_en": 2, "pdp_en_ok": 2}})
    write_part(root, "pdp_en", [pdp_rec("P100", "en"), pdp_rec("P101", "en")])
    write_part(root, "trpc", [trpc_rec("P100"), trpc_rec("P101", in_stock=False)])
    with psycopg.connect(db) as conn:
        assert _load(conn, root) == {"pdp_en": 2, "trpc": 2}
        states: dict[str, str] = dict(
            conn.execute(
                "SELECT l.source_listing_key, o.availability_state FROM offer_observation o"
                " JOIN source_listing l ON l.id=o.source_listing_id WHERE o.price_current IS NULL"
            ).fetchall()
        )
        assert states == {"1001": "in_stock", "1011": "out_of_stock"}
        price = conn.execute(
            "SELECT price_current, price_regular_stated, availability_state FROM offer_observation"
            " WHERE price_current IS NOT NULL LIMIT 1"
        ).fetchone()
        assert price is not None
        assert (float(price[0]), float(price[1]), price[2]) == (80.0, 100.0, "not_observed")
        assert _runs(conn, "full") == {"en": "succeeded"}  # no AR rows: no AR crawl_run
        # replay after the ledger is lost: nothing is duplicated
        (root.parent / ".loaded-full.json").unlink()
        _load(conn, root)
        n = conn.execute("SELECT count(*) FROM offer_observation").fetchone()
        assert n == (4,)


def test_plan_run_is_partial_even_when_complete(db: str, tmp_path: Path) -> None:
    progress = {"stopped": "complete", "counts": {"plan_pids": 1, "pdp_ar_ok": 1}}
    root = _folder(tmp_path / "plan", progress)
    write_part(root, "pdp_ar", [pdp_rec("P200", "ar")])
    with psycopg.connect(db) as conn:
        _load(conn, root)
        assert _runs(conn, "plan") == {"ar": "partial"}


def test_blocked_run_is_partial(db: str, tmp_path: Path) -> None:
    progress = {"stopped": "challenge: marker at x", "counts": {"block_challenge": 1}}
    root = _folder(tmp_path / "blocked", progress)
    write_part(root, "pdp_en", [pdp_rec("P300", "en")])
    with psycopg.connect(db) as conn:
        _load(conn, root)
        assert _runs(conn, "blocked") == {"en": "partial"}
        blocked = conn.execute(
            "SELECT blocked_count FROM crawl_run WHERE manifest_uri LIKE 'gs://test-bucket/blocked/%'"
        ).fetchone()
        assert blocked == (1,)
