"""Run selection in LATEST_LISTINGS_SQL against a real migrated database (pytest -m db)."""
# ruff: noqa: S101

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest
from alembic import command
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from pi_db import DATABASE_URL_ENV, alembic_config
from scripts.demo_export.export import LATEST_LISTINGS_SQL

pytestmark = pytest.mark.db

Conn = psycopg.Connection[dict[str, object]]
T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def migrated_db() -> Iterator[str]:
    """Same contract as packages/pi_db/tests/conftest.py: skip locally, fail in CI."""
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{DATABASE_URL_ENV} not set; run `make up` and export it")
    try:
        psycopg.connect(_libpq(url), connect_timeout=3).close()
    except psycopg.OperationalError:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"database at {DATABASE_URL_ENV} unreachable (run `make up`)")
    name = f"pi_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq(url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    db_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(db_url), "head")
        yield db_url
    finally:
        with psycopg.connect(_libpq(url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def conn(migrated_db: str) -> Iterator[Conn]:
    with psycopg.connect(_libpq(migrated_db), row_factory=dict_row) as connection:
        yield connection
        connection.rollback()


def _id(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> object:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row["id"]


class World:
    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self.source = _id(
            conn, "INSERT INTO source (name, kind) VALUES ('sephora_me', 'web') RETURNING id"
        )
        self.context = _id(
            conn,
            "INSERT INTO source_context (source_id, country, channel, locale, time_zone)"
            " VALUES (%s, 'AE', 'online', 'en-AE', 'Asia/Dubai') RETURNING id",
            (self.source,),
        )
        self.listings: dict[str, object] = {}

    def run(self, status: str, hour: int) -> object:
        return _id(
            self.conn,
            "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
            " started_at, status) VALUES (%s, '0.1.0', 0, %s, %s) RETURNING id",
            (self.context, T0.replace(hour=hour), status),
        )

    def observe(self, run: object, key: str, hour: int, price: str) -> None:
        if key not in self.listings:
            self.listings[key] = _id(
                self.conn,
                "INSERT INTO source_listing (source_id, source_listing_key, url, name_original,"
                " first_seen_at, last_seen_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (self.source, key, f"https://example.test/{key}", key, T0, T0),
            )
        self.conn.execute(
            "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
            " source_listing_id, observed_at, ingested_at, price_current, price_type, currency,"
            " availability_state, field_state, quality_status)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, 'full', 'AED', 'in_stock', '{}'::jsonb,"
            " 'accepted')",
            (
                f"{run}-{key}",
                run,
                self.context,
                self.listings[key],
                T0.replace(hour=hour),
                T0.replace(hour=hour),
                Decimal(price),
            ),
        )

    def latest(self) -> dict[str, tuple[object, object]]:
        rows = self.conn.execute(LATEST_LISTINGS_SQL).fetchall()
        return {str(r["source_listing_key"]): (r["run_id"], r["price"]) for r in rows}


@pytest.mark.parametrize("refresh_status", ["running", "failed", "partial", "aborted"])
def test_unfinished_refresh_never_hides_the_succeeded_baseline(
    conn: Conn, refresh_status: str
) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10")
    world.observe(baseline, "B", 1, "20")
    refresh = world.run(refresh_status, 5)
    world.observe(refresh, "A", 5, "11")  # B not (yet) seen: must not read as removed

    assert world.latest() == {"A": (baseline, Decimal("10")), "B": (baseline, Decimal("20"))}


def test_newest_succeeded_run_wins(conn: Conn) -> None:
    world = World(conn)
    old = world.run("succeeded", 1)
    world.observe(old, "A", 1, "10")
    world.observe(old, "B", 1, "20")
    new = world.run("succeeded", 3)
    world.observe(new, "A", 3, "12")

    assert world.latest() == {"A": (new, Decimal("12"))}


def test_without_a_succeeded_run_latest_observation_per_listing_across_runs(conn: Conn) -> None:
    world = World(conn)
    first = world.run("partial", 1)
    world.observe(first, "A", 1, "10")
    world.observe(first, "B", 1, "20")
    second = world.run("failed", 4)
    world.observe(second, "A", 4, "11")

    assert world.latest() == {"A": (second, Decimal("11")), "B": (first, Decimal("20"))}
