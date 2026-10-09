"""Run selection in LATEST_LISTINGS_SQL against a real migrated database (pytest -m db)."""
# ruff: noqa: S101

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from offline_import.load import Loader
from offline_import.mapping import ImportMapping
from offline_import.validate import validate_file
from pi_capture.bloomingdales import readings_from_bloomingdales
from pi_capture.feed import SHOPS, Shop, build_feed, dump_feed, mapping_for
from pi_capture.model import ProductCapture
from pi_dataset import dump_dataset
from pi_db import DATABASE_URL_ENV, alembic_config
from scripts.demo_export.export import (
    LATEST_LISTINGS_SQL,
    RETENTION_BASELINE_SQL,
    ListingRow,
    UltaContext,
    baseline_report,
    latest_params,
)
from scripts.demo_export.history import RunSpan, read_history
from scripts.demo_export.v2 import build_dataset_v2

pytestmark = pytest.mark.db

Conn = psycopg.Connection[dict[str, object]]
T0 = datetime(2026, 10, 1, tzinfo=UTC)
SEPHORA = {"sources": ["sephora_me"]}


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
    def __init__(self, conn: Conn, source: str = "sephora_me") -> None:
        self.conn, self.name = conn, source
        self.source = _id(
            conn, "INSERT INTO source (name, kind) VALUES (%s, 'web') RETURNING id", (source,)
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
        price_type: str | None = "full",
        regular: str | None = None,
        evidence: object = None,
        at: datetime | None = None,
    ) -> None:
        """One observation at ``hour`` on 1 Oct (UTC), or exactly ``at`` (then one run may read
        the same listing more than once)."""
        moment = T0.replace(hour=hour) if at is None else at
        if key not in self.listings:
            self.listings[key] = _id(
                self.conn,
                "INSERT INTO source_listing (source_id, source_listing_key, url, name_original,"
                " first_seen_at, last_seen_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (self.source, key, f"https://example.test/{key}", key, T0, T0),
            )
        self.conn.execute(
            "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
            " source_listing_id, observed_at, ingested_at, price_current, price_regular_stated,"
            " price_type, currency, availability_state, field_state, quality_status, evidence_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'AED', %s, %s::jsonb, 'accepted', %s)",
            (
                f"{run}-{key}" if at is None else f"{run}-{key}-{at.isoformat()}",
                run,
                context or self.context,
                self.listings[key],
                moment,
                moment,
                Decimal(price) if price is not None else None,
                Decimal(regular) if regular is not None else None,
                price_type if price is not None else None,
                availability,
                field_state,
                evidence,
            ),
        )

    def content(self, key: str, labels: dict[str, object], hour: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO listing_content (listing_id, observed_at, labels, content_hash)"
            " VALUES (%s, %s, %s::jsonb, %s)",
            (self.listings[key], T0.replace(hour=hour), json.dumps(labels), f"{key}-{hour}"),
        )

    def rederived(self, key: str, labels: dict[str, object], recorded_day: int) -> None:
        """Content at page time 01:00, recorded on 1 Oct + ``recorded_day`` (a re-derivation)."""
        self.conn.execute(
            "INSERT INTO listing_content (listing_id, observed_at, recorded_at, labels,"
            " content_hash) VALUES (%s, %s, %s, %s::jsonb, %s)",
            (
                self.listings[key],
                T0.replace(hour=1),
                T0.replace(day=recorded_day),
                json.dumps(labels),
                f"{key}-r{recorded_day}",
            ),
        )

    def latest(self) -> dict[str, tuple[object, object]]:
        rows = self.conn.execute(LATEST_LISTINGS_SQL, latest_params([self.name])).fetchall()
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
    rows = world.conn.execute(LATEST_LISTINGS_SQL, latest_params([world.name])).fetchall()
    return next(dict(r) for r in rows if r["source_listing_key"] == key)


def test_a_full_price_row_is_its_own_regular_price(conn: Conn) -> None:
    world = World(conn)
    run = world.run("succeeded", 1)
    world.observe(run, "FULL", 1, "80")  # Sephora/Faces: no regular stated on a full row
    world.observe(run, "STATED", 1, "70", regular="75")  # Ulta: stated on a full row
    world.observe(run, "PROMO", 1, "60", price_type="promotional", regular="90")
    world.observe(run, "BARE", 1, "50", price_type="promotional")  # a cut with no was-price

    regular = {k: _row(world, k)["regular"] for k in ("FULL", "STATED", "PROMO", "BARE")}
    assert regular == {
        "FULL": Decimal("80"),
        "STATED": Decimal("75"),
        "PROMO": Decimal("90"),
        "BARE": None,
    }


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


def test_stock_provenance_is_the_stock_row_not_a_newer_page_read(conn: Conn) -> None:
    """An old stock state must not look current: it carries its own time and run (#53)."""
    world = World(conn)
    stock = world.run("partial", 1)
    world.observe(stock, "A", 1, None, availability="in_stock", field_state=STOCK_ONLY)
    page = world.run("partial", 4)
    world.observe(page, "A", 4, "75", availability="not_observed")
    world.observe(page, "B", 4, "90", availability="not_observed")

    a, b = _row(world, "A"), _row(world, "B")
    assert (a["availability"], a["observed_at"], a["run_id"]) == (
        "in_stock",
        T0.replace(hour=4),
        page,
    )
    assert (a["stock_observed_at"], a["stock_run_id"]) == (T0.replace(hour=1), stock)
    assert (b["stock_observed_at"], b["stock_run_id"]) == (None, None)  # no stock read at all


def test_the_main_image_comes_from_the_latest_content(conn: Conn) -> None:
    world = World(conn)
    run = world.run("succeeded", 1)
    world.observe(run, "A", 1, "80")
    world.observe(run, "B", 1, "90")
    old = [{"role": "main", "position": 0, "url": "https://img-product.sephora.me/old.jpg"}]
    new = [
        {"role": "swatch", "position": 0, "url": "?sw=1248"},
        {"role": "alt", "position": 1, "url": "https://img-product.sephora.me/alt.jpg"},
        {"role": "main", "position": 0, "url": "https://img-product.sephora.me/new.jpg"},
    ]
    for hour, images in ((1, old), (2, new)):
        conn.execute(
            "INSERT INTO listing_content (listing_id, observed_at, labels, content_hash)"
            " VALUES (%s, %s, %s::jsonb, %s)",
            (world.listings["A"], T0.replace(hour=hour), json.dumps({"images": images}), str(hour)),
        )
    assert _row(world, "A")["image"] == "https://img-product.sephora.me/new.jpg"
    assert _row(world, "B")["image"] is None  # no content row at all


def test_the_concentration_comes_from_the_latest_content_label(conn: Conn) -> None:
    world = World(conn)
    run = world.run("succeeded", 1)
    for key in "ABC":
        world.observe(run, key, 1, "80")
    world.content("A", {"concentration": "edt"}, hour=1)
    world.content("A", {"concentration": "edp"}, hour=2)
    world.content("B", {"concentration": ""})
    assert _row(world, "A")["concentration"] == "edp"
    assert _row(world, "B")["concentration"] is None  # blank is absent
    assert _row(world, "C")["concentration"] is None  # no content row at all


def test_at_one_page_time_the_latest_recorded_content_wins(conn: Conn) -> None:
    world = World(conn)
    world.observe(world.run("succeeded", 1), "A", 1, "80")
    world.rederived("A", {"concentration": "edt"}, recorded_day=2)  # first in table order
    world.rederived("A", {"concentration": "edp"}, recorded_day=8)
    assert _row(world, "A")["concentration"] == "edp"


def test_ulta_rows_in_the_db_stay_out_unless_named_in_sources(conn: Conn) -> None:
    world = World(conn)
    world.observe(world.run("succeeded", 1), "s1", 1, "10")
    ulta = World(conn, "ulta_ae")
    ulta.observe(ulta.run("partial", 2), "u1", 2, "20")

    def keys(sources: list[str]) -> set[str]:
        rows = conn.execute(LATEST_LISTINGS_SQL, latest_params(sources)).fetchall()
        return {str(r["source_listing_key"]) for r in rows}

    assert keys(["sephora_me"]) == {"s1"}
    assert keys(["sephora_me", "ulta_ae"]) == {"s1", "u1"}


def _parent(*children: object, flag: object = True) -> dict[str, object]:
    return {"aggregate_parent": flag, "resolved_children": list(children)}


def test_an_ulta_parent_is_dropped_iff_a_child_is_exported_as_a_non_parent(conn: Conn) -> None:
    """The AIE's fixture: 2 children, childless, a shared child, absent and parent-only refs."""
    world = World(conn, "ulta_ae")
    run = world.run("succeeded", 1)
    for key in ("P", "C1", "C2", "Q", "R", "S", "P2", "C3", "U", "T", "V", "W"):
        world.observe(run, key, 1, "50")
    world.content("P", _parent("C1", "C2"))  # both children exported: dropped
    world.content("C1", {"listing_key": "C1"})
    world.content("Q", _parent())  # childless: kept
    world.content("R", {"aggregate_parent": True})  # no resolved_children key: kept
    world.content("S", _parent("GONE1", "GONE2"))  # children absent from the source: kept
    world.content("P2", _parent("C3", flag="true"))  # text 'true'; C3 shared with W
    world.content("W", _parent("C3", "GONE3"))  # one present child is enough: dropped
    world.content("U", _parent("Q"))  # its only ref is another parent: kept
    world.content("T", _parent("V", flag=False))  # not a parent at all: kept
    world.content("V", {"aggregate_parent": "false"})
    keys = sorted(world.latest())
    assert keys == ["C1", "C2", "C3", "Q", "R", "S", "T", "U", "V"]


def test_a_child_outside_the_exported_runs_does_not_drop_its_parent(conn: Conn) -> None:
    world = World(conn, "ulta_ae")
    run = world.run("succeeded", 2)
    failed = world.run("failed", 3)
    world.observe(run, "P", 2, "50")
    world.observe(failed, "C", 3, "40")  # only in a failed run: not in this snapshot
    world.content("P", _parent("C"))
    assert sorted(world.latest()) == ["P"]


def test_only_the_latest_content_decides_who_is_a_parent(conn: Conn) -> None:
    world = World(conn, "ulta_ae")
    run = world.run("succeeded", 1)
    for key in ("P", "C"):
        world.observe(run, key, 1, "50")
    world.content("P", _parent("C"), hour=1)
    world.content("P", {"aggregate_parent": False}, hour=2)  # no longer a parent
    world.content("C", {"aggregate_parent": True}, hour=1)
    world.content("C", {"aggregate_parent": False}, hour=2)
    assert sorted(world.latest()) == ["C", "P"]


def test_at_one_page_time_the_latest_recorded_child_content_decides(conn: Conn) -> None:
    world = World(conn, "ulta_ae")
    run = world.run("succeeded", 1)
    for key in ("P", "C"):
        world.observe(run, key, 1, "50")
    world.content("P", _parent("C"))
    world.rederived("C", {"aggregate_parent": True}, recorded_day=2)  # first in table order
    world.rederived("C", {"aggregate_parent": False}, recorded_day=8)  # a child now: P dropped
    assert sorted(world.latest()) == ["C"]


def test_sephora_listings_are_never_deduplicated(conn: Conn) -> None:
    world = World(conn)
    run = world.run("succeeded", 1)
    for key in ("P", "C"):
        world.observe(run, key, 1, "50")
    world.content("P", _parent("C"))
    assert sorted(world.latest()) == ["C", "P"]


def test_the_main_image_is_the_lowest_numeric_position_then_the_url(conn: Conn) -> None:
    world = World(conn)
    run = world.run("succeeded", 1)
    world.observe(run, "A", 1, "80")
    world.observe(run, "B", 1, "90")
    images = {
        "A": [  # as text "10" < "2"; numerically 2 comes first
            {"role": "main", "position": 10, "url": "https://img-product.sephora.me/a10.jpg"},
            {"role": "main", "position": 2, "url": "https://img-product.sephora.me/a2.jpg"},
        ],
        "B": [  # a tie on position: the url decides, so the pick is stable
            {"role": "main", "position": 0, "url": "https://img-product.sephora.me/b2.jpg"},
            {"role": "main", "position": 0, "url": "https://img-product.sephora.me/b1.jpg"},
        ],
    }
    for key, imgs in images.items():
        conn.execute(
            "INSERT INTO listing_content (listing_id, observed_at, labels, content_hash)"
            " VALUES (%s, %s, %s::jsonb, %s)",
            (world.listings[key], T0.replace(hour=1), json.dumps({"images": imgs}), key),
        )
    assert _row(world, "A")["image"] == "https://img-product.sephora.me/a2.jpg"
    assert _row(world, "B")["image"] == "https://img-product.sephora.me/b1.jpg"


ALSHAYA = "https://media.alshaya.com/adobe/assets/urn:aaid:aem:0000/as/p{n}.png"


def _ulta_image(n: int, position: object, roles: list[str]) -> dict[str, object]:
    """One element in the shape of the owner's ulta_ae load (synthetic values)."""
    return {
        "roles": roles,
        "download_url": ALSHAYA.format(n=n) + "?width=533&height=800&preferwebp=true",
        "source_url": ALSHAYA.format(n=n),
        "position": position,
        "status": "downloaded",
        "asset_id": f"a{n}",
        "sha256": "0" * 64,
        "local_path": f"/data/images/p{n}.png",
    }


def test_an_ulta_image_element_gives_its_lowest_positioned_download_url(conn: Conn) -> None:
    world = World(conn, "ulta_ae")
    run = world.run("partial", 1)
    for key in ("A", "B", "C", "D"):
        world.observe(run, key, 1, "50")
    world.content(
        "A",
        {
            "images": [
                _ulta_image(3, 3, ["image"]),
                _ulta_image(1, 1, ["swatch_image"]),  # not an 'image' role: skipped
                _ulta_image(2, 2, ["image", "swatch_image"]),
            ]
        },
    )
    world.content("B", {"images": []})  # empty: null, never invented
    world.content("C", {"images": [_ulta_image(4, 1, ["swatch_image"])]})  # no 'image' role
    # D has no content row at all
    expected = ALSHAYA.format(n=2) + "?width=533&height=800&preferwebp=true"
    assert _row(world, "A")["image"] == expected
    assert _row(world, "B")["image"] is None
    assert _row(world, "C")["image"] is None
    assert _row(world, "D")["image"] is None


def test_an_ulta_alshaya_image_survives_the_v2_export(conn: Conn) -> None:
    """The URL the SQL reads from the owner's shape reaches the v2 file (strict load included)."""
    from scripts.demo_export.test_export import row  # noqa: PLC0415
    from scripts.demo_export.test_v2 import doc, only_offer  # noqa: PLC0415

    world = World(conn, "ulta_ae")
    world.observe(world.run("partial", 1), "A", 1, "50")
    world.content("A", {"images": [_ulta_image(1, 1, ["image", "swatch_image"])]})
    image = _row(world, "A")["image"]
    expected = ALSHAYA.format(n=1) + "?width=533&height=800&preferwebp=true"
    assert image == expected
    ulta = row(source="ulta_ae", family=20, variant=200)
    d = doc([ListingRow(**(ulta.__dict__ | {"image": image}))])
    assert only_offer(d)["image"] == expected
    assert d["products"][0]["image"] == expected
    assert d["meta"]["capabilities"]["images"] is True


def _history(conn: Conn, world: World) -> tuple[list[RunSpan], dict[date, list[ListingRow]]]:
    with conn.cursor() as cursor:
        spans, days, _ = read_history(cursor, [world.name])
    return spans, days


def test_history_files_each_observation_under_its_dubai_market_day(conn: Conn) -> None:
    # T0 is 00:00Z on 1 Oct: 02:00Z is 06:00 Dubai on 1 Oct, 21:00Z is 01:00 Dubai on 2 Oct.
    world = World(conn)
    conn.execute(
        "UPDATE source_context SET coverage_status = 'supported' WHERE id = %s", (world.context,)
    )
    first = world.run("succeeded", 2)
    world.observe(first, "a", 2, "10")
    world.observe(first, "b", 3, "20")
    second = world.run("succeeded", 21)
    world.observe(second, "a", 21, "11")
    world.observe(second, "c", 22, "30")
    spans, days = _history(conn, world)
    assert [(s.run_id, s.days, s.complete_day) for s in spans] == [
        (first, [date(2026, 10, 1)], date(2026, 10, 1)),
        (second, [date(2026, 10, 2)], date(2026, 10, 2)),
    ]
    prices = {d: {r.source_listing_key: r.price for r in rows} for d, rows in days.items()}
    # each day holds only that day's observations: nothing from 2 Oct leaks back, nothing carries
    assert prices == {
        date(2026, 10, 1): {"a": Decimal(10), "b": Decimal(20)},
        date(2026, 10, 2): {"a": Decimal(11), "c": Decimal(30)},
    }


def test_history_on_a_context_not_marked_supported_has_no_complete_day(conn: Conn) -> None:
    world = World(conn)  # the column default, 'pending'; the Sephora loader writes 'partial'
    world.observe(world.run("succeeded", 2), "a", 2, "10")
    spans, days = _history(conn, world)
    assert [s.complete_day for s in spans] == [None]
    assert list(days) == [date(2026, 10, 1)]


def test_history_ignores_failed_and_unfinished_runs(conn: Conn) -> None:
    world = World(conn)
    for status, hour in [("failed", 2), ("running", 3), ("aborted", 4)]:
        world.observe(world.run(status, hour), f"k{hour}", hour, "10")
    assert _history(conn, world) == ([], {})


def test_gift_with_purchase_titles_come_from_the_latest_content_in_order(conn: Conn) -> None:
    world = World(conn)
    run = world.run("succeeded", 1)
    for key in ("A", "B", "C"):
        world.observe(run, key, 1, "80")
    world.content("A", {"gift_with_purchase": ["Old gift"]}, hour=1)
    titles = ["Free pouch", " ", None, "A mini", "Zip bag"]  # page order, neither sort order
    world.content("A", {"gift_with_purchase": titles}, hour=2)
    world.content("B", {"gift_with_purchase": "not a list"})
    assert _row(world, "A")["gift_with_purchase"] == ["Free pouch", "A mini", "Zip bag"]
    assert _row(world, "B")["gift_with_purchase"] == []
    assert _row(world, "C")["gift_with_purchase"] == []  # no content row at all


def _blm_capture() -> ProductCapture:
    product = {
        "id": "900000101",
        "master": {"masterId": "BEA900000100"},
        "name": "Hydra Gel Cleanser",
        "c_brand": "Synthetic Lab",
        "c_rms_div": "Beauty",
        "c_rms_dept": "Skincare",
        "c_price": {"sales": {"value": 140, "currency": "AED"}},
        "c_ingredients": "Aqua, Glycerin, Propanediol, Xanthan Gum, Phenoxyethanol, Citric Acid",
        "c_product_promotions": [
            {"promotionId": "GWP-Synthetic", "calloutMsgText": "<b>Beauty Treats</b>, free"}
        ],
    }
    query = json.dumps({"queries": [{"state": {"data": {"productData": product}}}]})
    page = f"<html><body><script>window.__Q__={query}</script></body></html>"
    return ProductCapture(
        source="test",
        retailer="bloomingdales",
        url="https://bloomingdales.ae/p/900000101",
        locale="en-AE",
        retrieved_at=datetime(2026, 10, 2, 9, 0, tzinfo=UTC),
        egress="direct",
        page_sha256="0" * 64,
        readings=tuple(readings_from_bloomingdales(page, locale="en-AE")),
    )


def _feed_load_export(conn: Conn, migrated_db: str, tmp_path: Path, shop: Shop) -> dict[str, Any]:
    """Page -> pi_capture feed -> offline_import load -> the export row."""
    feed = tmp_path / "feed.json"
    feed.write_text(dump_feed(build_feed([_blm_capture()], shop), shop), "utf-8")
    mapping = ImportMapping.model_validate(mapping_for(shop))
    with psycopg.connect(_libpq(migrated_db)) as load_conn:
        Loader(load_conn, mapping, validate_file(feed, mapping), "gs://pi-test/blm.json").load()
    rows = conn.execute(LATEST_LISTINGS_SQL, latest_params([shop.source])).fetchall()
    (got,) = [dict(r) for r in rows]
    content = conn.execute(
        "SELECT c.labels FROM listing_content c JOIN source_listing l ON l.id = c.listing_id"
        " JOIN source s ON s.id = l.source_id WHERE s.name = %s",
        (shop.source,),
    ).fetchone()
    assert content is not None
    return got | {"labels": content["labels"]}


def test_a_captured_gift_with_purchase_and_style_reach_the_export_row(
    conn: Conn, migrated_db: str, tmp_path: Path
) -> None:
    """The gift-with-purchase label and the style id (the family the export groups by) survive
    every hop for a shop with page attributes (Bloomingdale's)."""
    shop = replace(SHOPS["bloomingdales_ae"], source="blm_export_e2e")
    got = _feed_load_export(conn, migrated_db, tmp_path, shop)
    assert got["gift_with_purchase"] == ["Beauty Treats, free"]
    assert got["family_id"] == "BEA900000100"
    assert got["labels"]["master_id"] == "BEA900000100"


def test_without_page_attributes_the_same_page_keeps_its_sku_family(
    conn: Conn, migrated_db: str, tmp_path: Path
) -> None:
    """The same page through a shop without page attributes (Faces' setting): the style id
    never reaches labels.master_id, so the family and product id stay keyed by the sku."""
    shop = replace(SHOPS["bloomingdales_ae"], source="sku_family_e2e", page_attributes=False)
    got = _feed_load_export(conn, migrated_db, tmp_path, shop)
    assert "master_id" not in got["labels"]
    assert got["family_id"] == got["source_listing_key"] == "900000101"
    assert got["gift_with_purchase"] == []  # a promotion here, as on main


def test_an_ounass_page_keeps_its_sku_family_and_product_id(
    conn: Conn, migrated_db: str, tmp_path: Path
) -> None:
    """Ounass stays at sku grain: the same page, with a style id on it, through Ounass's shop
    settings never reaches labels.master_id, so the family (and the product id derived from it)
    is the listing key, as in the Ounass body already served; the other page attributes still
    arrive."""
    shop = replace(SHOPS["ounass_ae"], source="ounass_sku_e2e")
    got = _feed_load_export(conn, migrated_db, tmp_path, shop)
    assert "master_id" not in got["labels"]
    assert got["family_id"] == got["source_listing_key"] == "900000101"
    assert got["gift_with_purchase"] == ["Beauty Treats, free"]


# ------------------------------------------- capture time and the regular-price declaration
CAPTURED = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)  # _blm_capture's retrieved_at


def _v2(rows: list[dict[str, Any]], slots: tuple[str, ...]) -> dict[str, Any]:
    """The v2 body of these export rows (World's rows carry no brand: a test one is given)."""
    listing = [ListingRow(**(r | {"brand": r["brand"] or "Test Brand"})) for r in rows]
    dataset = build_dataset_v2(
        listing,
        [],
        generated_at=datetime(2026, 12, 1, tzinfo=UTC),
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
        ulta_note={},
        slots=slots,
    )
    loaded: dict[str, Any] = json.loads(dump_dataset(dataset))
    return loaded


def _offers(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for p in d["products"] for o in p["offers"].values()]


def test_an_imported_page_is_dated_by_its_capture_not_the_import(
    conn: Conn, migrated_db: str, tmp_path: Path
) -> None:
    """Page (2 Oct) -> feed -> offline_import load (now) -> v2: capturedAt is the page's time.
    The file's evidence row holds the import time; it never reaches the export as a capture."""
    shop = replace(SHOPS["bloomingdales_ae"], source="bloomingdales_capture_e2e")
    got = _feed_load_export(conn, migrated_db, tmp_path, shop)
    assert got["evidence_retrieved_at"] is None
    assert got["price_evidence_retrieved_at"] is None
    assert got["observed_at"] == got["price_observed_at"] == CAPTURED
    assert got["file_received_at"] is not None
    assert got["file_received_at"] > CAPTURED  # the import, days later
    got.pop("labels")
    d = _v2([got], ("b",))
    (offer,) = _offers(d)
    assert offer["evidence"]["capturedAt"] == "2026-10-02T09:00:00Z"
    assert d["meta"]["dates"] == ["2026-10-02"]
    # ...and Bloomingdale's (regular_stated not_collected) publishes no regular price
    assert got["price_type"] is None
    assert offer["series"]["regular"] is None
    assert d["meta"]["fields"]["regular"] == "not_collected"
    assert d["meta"]["capabilities"]["promotions"] is False


def test_rows_loaded_full_before_the_declaration_export_regular_not_collected(
    conn: Conn,
) -> None:
    """Run 8's 7,694 rows are stored price_type 'full' with no regular (append-only, and a replay
    of the same feed is a no-op). The query still gives them regular = price; the export reads
    the declaration per source and publishes none: not_collected, promotions off."""
    world = World(conn, "bloomingdales_ae")
    run = world.run("partial", 1)
    for key in ("B1", "B2"):
        world.observe(run, key, 1, "90")  # price_type 'full', price_regular_stated NULL
    rows = conn.execute(LATEST_LISTINGS_SQL, latest_params([world.name])).fetchall()
    assert {r["regular"] for r in rows} == {Decimal("90")}  # what made the 0% discount
    d = _v2([dict(r) for r in rows], ("b",))
    assert [o["series"]["regular"] for o in _offers(d)] == [None, None]
    assert d["meta"]["fields"]["regular"] == "not_collected"
    assert d["meta"]["capabilities"]["promotions"] is False


def test_sephora_with_no_promotion_keeps_regular_ok(conn: Conn) -> None:
    """Sephora states a regular only on promotional rows: a day with none is a 0% share, not
    'not collected'. The declaration, not the day's row counts, decides."""
    world = World(conn)
    run = world.run("succeeded", 1)
    for key in ("S1", "S2"):
        world.observe(run, key, 1, "80")
    rows = conn.execute(LATEST_LISTINGS_SQL, latest_params([world.name])).fetchall()
    d = _v2([dict(r) for r in rows], ("s",))
    assert all(o["series"]["regular"] == o["series"]["price"] for o in _offers(d))
    assert d["meta"]["fields"]["regular"] == "ok"
    assert d["meta"]["capabilities"]["promotions"] is True


@pytest.mark.parametrize(
    ("method", "rung", "dated_by_evidence"),
    [("plain_http", 1, True), ("offline_import", 0, False)],
)
def test_only_offline_import_evidence_gives_way_to_the_rows_own_time(
    conn: Conn, method: str, rung: int, dated_by_evidence: bool
) -> None:
    """Crawled evidence still dates a row by its retrieved_at (the fetch); a feed file's does
    not (keyed on the stored evidence.fetch_method, never on a URI)."""
    world = World(conn)
    run = world.run("succeeded", 1)
    retrieved = T0.replace(hour=5)
    evidence = _id(
        conn,
        "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
        " ladder_rung_used, fetch_method, retention_until)"
        " VALUES (%s, 'https://example.test/E', 'h', 'gs://pi-test/e', %s, %s, %s, %s)"
        " RETURNING id",
        (run, retrieved, rung, method, T0.replace(month=12)),
    )
    world.observe(run, "E", 1, "80", evidence=evidence)
    got = _row(world, "E")
    fields: dict[str, Any] = got
    assert got["observed_at"] == T0.replace(hour=1)
    if dated_by_evidence:
        assert (got["evidence_retrieved_at"], got["file_received_at"]) == (retrieved, None)
    else:
        assert (got["evidence_retrieved_at"], got["file_received_at"]) == (None, retrieved)
    captured, _ = ListingRow(**fields).price_capture
    assert captured == (retrieved if dated_by_evidence else T0.replace(hour=1))


# ------------------------------------------- crawl windows (--run, ADR-0013; option A stock)


def _window(world: World, runs: list[object]) -> dict[str, dict[str, object]]:
    params = latest_params([world.name], runs=[int(str(r)) for r in runs])
    rows = world.conn.execute(LATEST_LISTINGS_SQL, params).fetchall()
    return {str(r["source_listing_key"]): dict(r) for r in rows}


def _at(hour: int, minute: int = 0) -> datetime:
    return T0.replace(hour=hour, minute=minute)  # 1 Oct UTC: Dubai 1 Oct until 20:00Z


def test_in_a_window_the_latest_real_same_day_stock_read_wins(conn: Conn) -> None:
    """Several stock reads on the price's Dubai day: the latest real one; a later blocked read
    is skipped, never published as out of stock."""
    world = World(conn)
    run = world.run("partial", 1)
    world.observe(run, "A", 1, "80", availability="not_observed")
    for hour, state in ((2, "in_stock"), (3, "out_of_stock"), (4, "blocked")):
        world.observe(run, "A", 0, None, availability=state, field_state=STOCK_ONLY, at=_at(hour))

    a = _window(world, [run])["A"]
    assert (a["price"], a["availability"]) == (Decimal("80"), "out_of_stock")
    assert (a["stock_observed_at"], a["stock_run_id"]) == (_at(3), run)
    assert a["retained"] is False


def test_in_a_window_another_runs_same_day_stock_read_is_never_used(conn: Conn) -> None:
    """The Sephora run-2 shape: run 1 reads the page, run 2 the stock, the same Dubai day."""
    world = World(conn)
    run_1 = world.run("partial", 1)
    world.observe(run_1, "A", 1, "80", availability="not_observed")
    run_2 = world.run("partial", 2)
    world.observe(run_2, "A", 2, None, availability="out_of_stock", field_state=STOCK_ONLY)

    a = _window(world, [run_1])["A"]
    assert (a["price"], a["availability"], a["stock_run_id"]) == (
        Decimal("80"),
        "not_observed",
        None,
    )
    assert _row(world, "A")["availability"] == "out_of_stock"  # without a window, as before


def test_in_a_window_stock_after_dubai_midnight_is_not_the_prices(conn: Conn) -> None:
    """Price at Dubai 23:59 and stock at 00:01 the next Dubai day, one run: no stock."""
    world = World(conn)
    run = world.run("partial", 1)
    world.observe(run, "A", 0, "80", availability="not_observed", at=_at(19, 59))
    world.observe(run, "A", 0, None, availability="in_stock", field_state=STOCK_ONLY, at=_at(20, 1))

    a = _window(world, [run])["A"]
    assert (a["price"], a["availability"], a["stock_run_id"]) == (
        Decimal("80"),
        "not_observed",
        None,
    )


def test_a_listing_the_window_did_not_see_is_retained_from_an_earlier_run(conn: Conn) -> None:
    """B was seen only by an earlier succeeded run: it is kept with no value (never a removal)
    and its earlier run as evidence. C, seen only by a run after the window's, is not read."""
    world = World(conn)
    earlier = world.run("succeeded", 1)
    world.observe(earlier, "A", 1, "70")
    world.observe(earlier, "B", 1, "90", availability="in_stock")
    window = world.run("partial", 5)
    world.observe(window, "A", 5, "75")
    later = world.run("succeeded", 9)
    world.observe(later, "C", 9, "50")

    got = _window(world, [window])
    assert set(got) == {"A", "B"}
    a, b = got["A"], got["B"]
    assert (a["price"], a["run_id"], a["retained"]) == (Decimal("75"), window, False)
    assert (b["price"], b["regular"], b["availability"]) == (None, None, "not_observed")
    assert (b["run_id"], b["observed_at"], b["retained"]) == (earlier, _at(1), True)
    assert b["rating"] is None


def _baseline(world: World, runs: list[object]) -> str:
    params = latest_params([world.name], runs=[int(str(r)) for r in runs])
    return baseline_report(world.conn.execute(RETENTION_BASELINE_SQL, params).fetchall())


def test_only_the_latest_succeeded_run_before_the_window_is_retained(conn: Conn) -> None:
    """Reviewer 5461503616 item 3, Coordinator 01a11ce2-fd3e: B, seen only by run N-2, is not
    retained; A, seen by N-1 (the latest succeeded run before the window) and missed by the
    window, is."""
    world = World(conn)
    n2 = world.run("succeeded", 1)
    world.observe(n2, "B", 1, "90")
    n1 = world.run("succeeded", 2)
    world.observe(n1, "A", 2, "70")
    window = world.run("partial", 5)
    world.observe(window, "C", 5, "75")

    got = _window(world, [window])
    assert set(got) == {"A", "C"}
    assert (got["A"]["run_id"], got["A"]["retained"]) == (n1, True)
    assert _baseline(world, [window]) == f"retention {world.name}: baseline succeeded run {n1}"


def test_a_partial_run_after_the_baseline_retains_what_it_saw(conn: Conn) -> None:
    """Coordinator 01a11e38-6cba (A1): B, seen only by a partial N-1 after the succeeded N-2, is
    retained from N-1 with no value; A is still retained from N-2. The partial run is never the
    baseline, and the log line says so."""
    world = World(conn)
    n2 = world.run("succeeded", 1)
    world.observe(n2, "A", 1, "70")
    n1 = world.run("partial", 2)
    world.observe(n1, "B", 2, "90", availability="in_stock")
    window = world.run("partial", 5)
    world.observe(window, "C", 5, "75")

    got = _window(world, [window])
    assert set(got) == {"A", "B", "C"}
    assert (got["A"]["run_id"], got["A"]["retained"]) == (n2, True)
    b = got["B"]
    assert (b["run_id"], b["observed_at"], b["retained"]) == (n1, _at(2), True)
    assert (b["price"], b["regular"], b["availability"], b["rating"]) == (
        None,
        None,
        "not_observed",
        None,
    )
    assert _baseline(world, [window]) == (
        f"retention {world.name}: baseline succeeded run {n2}; partial runs [{n1}] retain only"
        " the listings they saw, never the baseline"
    )


def test_a_listing_the_baseline_and_a_later_partial_run_both_saw_keeps_the_newer_evidence(
    conn: Conn,
) -> None:
    """Reviewer 5465016080 (c): A, seen by the succeeded N-2 and again by the partial N-1, is
    retained once, from N-1 (the newer capture); B, seen only by N-2, keeps N-2's."""
    world = World(conn)
    n2 = world.run("succeeded", 1)
    world.observe(n2, "A", 1, "70")
    world.observe(n2, "B", 1, "80")
    n1 = world.run("partial", 2)
    world.observe(n1, "A", 2, "72")
    window = world.run("partial", 5)
    world.observe(window, "C", 5, "75")

    got = _window(world, [window])
    assert set(got) == {"A", "B", "C"}
    a, b = got["A"], got["B"]
    assert (a["run_id"], a["observed_at"], a["retained"]) == (n1, _at(2), True)
    assert (b["run_id"], b["observed_at"], b["retained"]) == (n2, _at(1), True)
    assert (a["price"], a["availability"]) == (None, "not_observed")


def test_a_listing_a_later_succeeded_run_did_not_see_is_not_retained(conn: Conn) -> None:
    """Crawl 01a11e38-d0f3, Coordinator 01a11e38-fd27: P saw L, then the succeeded S (a complete
    catalogue) did not; S ends L's retention, so L is not retained from P."""
    world = World(conn)
    p = world.run("partial", 1)
    world.observe(p, "L", 1, "90")
    s = world.run("succeeded", 2)
    world.observe(s, "A", 2, "70")
    window = world.run("partial", 5)
    world.observe(window, "C", 5, "75")

    got = _window(world, [window])
    assert set(got) == {"A", "C"}
    assert (got["A"]["run_id"], got["A"]["retained"]) == (s, True)
    assert _baseline(world, [window]) == f"retention {world.name}: baseline succeeded run {s}"


def test_with_no_succeeded_run_a_partial_run_retains_what_it_saw(conn: Conn) -> None:
    """The Faces case (Coordinator 01a11e36-b087, 01a11e38-6cba): window run 9, an earlier
    partial run 6 and no succeeded run. Exactly the listings run 6 saw and run 9 did not are
    retained, with run 6's capture as evidence and no value from run 6; the window's own listings
    keep the window's values."""
    world = World(conn)
    six = world.run("partial", 1)
    world.observe(six, "A", 1, "70", availability="in_stock")
    world.observe(six, "B", 1, "90", availability="in_stock")
    nine = world.run("succeeded", 5)
    world.observe(nine, "A", 5, "75")
    world.observe(nine, "C", 5, "80")

    got = _window(world, [nine])
    assert set(got) == {"A", "B", "C"}
    assert [k for k, v in sorted(got.items()) if v["retained"]] == ["B"]
    a, b = got["A"], got["B"]
    assert (a["price"], a["run_id"]) == (Decimal("75"), nine)
    assert (b["run_id"], b["observed_at"]) == (six, _at(1))
    assert (b["price"], b["regular"], b["availability"], b["rating"]) == (
        None,
        None,
        "not_observed",
        None,
    )
    assert (b["stock_run_id"], b["price_run_id"]) == (None, None)
    assert _baseline(world, [nine]) == (
        f"retention {world.name}: baseline none; partial runs [{six}] retain only the listings"
        " they saw, never the baseline"
    )


def test_with_no_run_before_the_window_nothing_is_retained(conn: Conn) -> None:
    world = World(conn)
    window = world.run("partial", 5)
    world.observe(window, "C", 5, "75")
    later = world.run("partial", 9)
    world.observe(later, "D", 9, "60")

    assert set(_window(world, [window])) == {"C"}
    assert _baseline(world, [window]) == f"retention {world.name}: baseline none (nothing retained)"


def test_without_a_window_nothing_is_retained(conn: Conn) -> None:
    world = World(conn)
    earlier = world.run("succeeded", 1)
    world.observe(earlier, "A", 1, "70")
    rows = conn.execute(LATEST_LISTINGS_SQL, latest_params([world.name])).fetchall()
    assert [r["retained"] for r in rows] == [False]


def test_a_history_day_and_window_runs_do_not_mix() -> None:
    with pytest.raises(ValueError, match="do not mix"):
        latest_params(["sephora_me"], day=(T0, T0), runs=[1])
