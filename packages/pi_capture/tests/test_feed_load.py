"""The feed through offline_import's real loader: a regular price at or below the current price
must load as FULL, never PROMOTIONAL. Needs a database (skipped without one, required in CI).
Synthetic captures only; no real retailer page is used."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from sqlalchemy.engine import make_url

from offline_import.load import Loader
from offline_import.mapping import ImportMapping
from offline_import.validate import validate_file
from pi_capture.feed import Shop, build_feed, dump_feed, mapping_for
from pi_capture.model import ProductCapture, Reading
from pi_capture.registry import get
from pi_db import DATABASE_URL_ENV, alembic_config

CaptureFactory = Callable[..., ProductCapture]

SHOP = Shop(
    source="example_load_ae",
    base_url="https://shop.example",
    country="AE",
    locale="en-AE",
    currency="AED",
    time_zone="Asia/Dubai",
    notes="synthetic",
)


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


def _price(key: str, minor: int) -> Reading:
    return Reading(key, get(key).level, "observed", str(minor), minor, f"test.{key}", None, "AED")


def _capture(make_capture: CaptureFactory, sku: str, now: int, was: int) -> ProductCapture:
    sku_reading = Reading(
        "retailer_sku", get("retailer_sku").level, "observed", sku, sku, "test.sku", None, None
    )
    return make_capture(
        url=f"https://shop.example/en/p/{sku}",
        readings=(sku_reading, _price("price_minor", now), _price("regular_price_minor", was)),
    )


def test_only_a_regular_price_above_the_current_one_loads_as_a_promotion(
    db: str, tmp_path: Path, make_capture: CaptureFactory
) -> None:
    captures = [
        _capture(make_capture, "ABOVE", 8000, 10000),
        _capture(make_capture, "EQUAL", 8000, 8000),
        _capture(make_capture, "BELOW", 8000, 7000),
    ]
    feed = tmp_path / "feed.json"
    feed.write_text(dump_feed(build_feed(captures, SHOP), SHOP), "utf-8")
    mapping = ImportMapping.model_validate(mapping_for(SHOP))
    report = validate_file(feed, mapping)
    with psycopg.connect(db) as conn:
        Loader(conn, mapping, report, "gs://pi-imports-test/example/feed.json").load()
    with psycopg.connect(db) as conn:
        rows = conn.execute(
            "SELECT l.source_listing_key, o.price_current, o.price_regular_stated,"
            " o.price_promo, o.price_type::text FROM offer_observation o"
            " JOIN source_listing l ON l.id = o.source_listing_id ORDER BY 1"
        ).fetchall()
    got = {key: (str(cur), reg, promo, kind) for key, cur, reg, promo, kind in rows}
    assert got["ABOVE"][3] == "promotional"
    assert got["EQUAL"] == ("80.0000", None, None, "full")
    assert got["BELOW"] == ("80.0000", None, None, "full")
