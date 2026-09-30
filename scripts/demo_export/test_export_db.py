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

    def run(self, status: str, hour: int, context: object = None) -> object:
        return _id(
            self.conn,
            "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
            " started_at, status) VALUES (%s, '0.1.0', 0, %s, %s) RETURNING id",
            (context or self.context, T0.replace(hour=hour), status),
        )

    def ar_context(self) -> object:
        return _id(
            self.conn,
            "INSERT INTO source_context (source_id, country, channel, locale, time_zone)"
            " VALUES (%s, 'AE', 'online', 'ar-AE', 'Asia/Dubai') RETURNING id",
            (self.source,),
        )

    def observe(  # noqa: PLR0913 - one column per argument
        self,
        run: object,
        key: str,
        hour: int,
        price: str | None,
        *,
        availability: str = "in_stock",
        field_state: str = "{}",
        context: object = None,
    ) -> None:
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
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'AED', %s, %s::jsonb, 'accepted')",
            (
                f"{run}-{key}",
                run,
                context or self.context,
                self.listings[key],
                T0.replace(hour=hour),
                T0.replace(hour=hour),
                Decimal(price) if price is not None else None,
                "full" if price is not None else None,
                availability,
                field_state,
            ),
        )

    def latest(self) -> dict[str, tuple[object, object]]:
        rows = self.conn.execute(LATEST_LISTINGS_SQL).fetchall()
        return {str(r["source_listing_key"]): (r["run_id"], r["price"]) for r in rows}


@pytest.mark.parametrize("refresh_status", ["running", "failed", "aborted"])
def test_unfinished_or_failed_refresh_is_ignored(conn: Conn, refresh_status: str) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10")
    world.observe(baseline, "B", 1, "20")
    refresh = world.run(refresh_status, 5)
    world.observe(refresh, "A", 5, "11")
    world.observe(refresh, "C", 5, "30")

    assert world.latest() == {"A": (baseline, Decimal("10")), "B": (baseline, Decimal("20"))}


def test_later_partial_refresh_updates_but_never_hides_the_baseline(conn: Conn) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10")
    world.observe(baseline, "B", 1, "20")
    refresh = world.run("partial", 5)
    world.observe(refresh, "A", 5, "11")
    world.observe(refresh, "C", 5, "30")  # new since the baseline: shown
    # B not seen by the refresh: keeps its baseline row, never reads as removed

    assert world.latest() == {
        "A": (refresh, Decimal("11")),
        "B": (baseline, Decimal("20")),
        "C": (refresh, Decimal("30")),
    }


def test_partial_runs_before_the_baseline_are_ignored(conn: Conn) -> None:
    world = World(conn)
    old = world.run("partial", 1)
    world.observe(old, "A", 1, "9")
    world.observe(old, "B", 1, "19")
    baseline = world.run("succeeded", 3)
    world.observe(baseline, "A", 3, "10")

    assert world.latest() == {"A": (baseline, Decimal("10"))}


def test_later_partial_stock_read_updates_stock_and_keeps_the_baseline_price(conn: Conn) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10", availability="in_stock")
    refresh = world.run("partial", 5)
    world.observe(refresh, "A", 5, None, availability="out_of_stock", field_state=STOCK_ONLY)

    a = _row(world, "A")
    assert (a["price"], a["availability"]) == (Decimal("10"), "out_of_stock")
    assert (a["price_run_id"], a["run_id"]) == (baseline, refresh)


def test_explicit_removed_observation_from_a_later_page_check_flows_through(conn: Conn) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10", availability="in_stock")
    check = world.run("partial", 5)
    world.observe(check, "A", 5, None, availability="removed", field_state=STOCK_ONLY)

    a = _row(world, "A")
    assert (a["price"], a["availability"]) == (Decimal("10"), "removed")


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


STOCK_ONLY = '{"price_current": "unknown", "availability_state": "observed"}'


def _row(world: World, key: str) -> dict[str, object]:
    rows = world.conn.execute(LATEST_LISTINGS_SQL).fetchall()
    return next(dict(r) for r in rows if r["source_listing_key"] == key)


def test_newer_stock_read_keeps_the_page_price(conn: Conn) -> None:
    world = World(conn)
    run = world.run("partial", 1)
    world.observe(run, "A", 1, "80", availability="not_observed")  # page: price, no stock
    world.observe(run, "B", 1, "90", availability="not_observed")
    stock = world.run("partial", 3)
    world.observe(stock, "A", 3, None, availability="out_of_stock", field_state=STOCK_ONLY)

    a, b = _row(world, "A"), _row(world, "B")
    assert (a["price"], a["availability"]) == (Decimal("80"), "out_of_stock")
    assert (b["price"], b["availability"]) == (Decimal("90"), "not_observed")


def test_price_provenance_is_the_price_row_not_a_newer_stock_read(conn: Conn) -> None:
    world = World(conn)
    page = world.run("partial", 1)
    world.observe(page, "A", 1, "80", availability="not_observed")
    stock = world.run("partial", 3)
    world.observe(stock, "A", 3, None, availability="in_stock", field_state=STOCK_ONLY)

    a = _row(world, "A")
    assert (a["observed_at"], a["run_id"]) == (T0.replace(hour=3), stock)
    assert (a["price_observed_at"], a["price_run_id"]) == (T0.replace(hour=1), page)


def test_newer_page_read_keeps_the_stock_state(conn: Conn) -> None:
    world = World(conn)
    stock = world.run("partial", 1)
    world.observe(stock, "A", 1, "80", availability="not_observed")
    later = world.run("partial", 2)
    world.observe(later, "A", 2, None, availability="out_of_stock", field_state=STOCK_ONLY)
    page = world.run("partial", 4)
    world.observe(page, "A", 4, "75", availability="not_observed")

    a = _row(world, "A")
    assert (a["price"], a["availability"], a["run_id"]) == (Decimal("75"), "out_of_stock", page)


def test_arabic_context_rows_never_override_the_english_baseline(conn: Conn) -> None:
    world = World(conn)
    en = world.run("partial", 1)
    world.observe(en, "A", 1, "80", availability="in_stock")
    ar_ctx = world.ar_context()
    ar = world.run("partial", 6, context=ar_ctx)
    world.observe(ar, "A", 6, "70", availability="not_observed", context=ar_ctx)

    a = _row(world, "A")
    assert (a["price"], a["availability"], a["run_id"]) == (Decimal("80"), "in_stock", en)


@pytest.mark.parametrize("state", ["not_observed", "unknown", "blocked"])
def test_non_stock_states_never_override_a_known_stock_state(conn: Conn, state: str) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10", availability="in_stock")
    refresh = world.run("partial", 5)
    world.observe(refresh, "A", 5, None, availability=state, field_state=STOCK_ONLY)

    assert _row(world, "A")["availability"] == "in_stock"


@pytest.mark.parametrize("reason", ["unknown", "blocked", "parse_failure"])
def test_price_non_observation_keeps_the_baseline_price(conn: Conn, reason: str) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10", availability="in_stock")
    refresh = world.run("partial", 5)
    world.observe(
        refresh, "A", 5, None, availability="not_observed",
        field_state=f'{{"price_current": "{reason}"}}',
    )  # fmt: skip

    a = _row(world, "A")
    assert (a["price"], a["price_run_id"]) == (Decimal("10"), baseline)


def test_not_published_price_is_an_observation(conn: Conn) -> None:
    world = World(conn)
    baseline = world.run("succeeded", 1)
    world.observe(baseline, "A", 1, "10", availability="in_stock")
    refresh = world.run("partial", 5)
    world.observe(
        refresh, "A", 5, None, availability="not_observed",
        field_state='{"price_current": "not_published"}',
    )  # fmt: skip

    a = _row(world, "A")
    assert (a["price"], a["price_run_id"]) == (None, refresh)
