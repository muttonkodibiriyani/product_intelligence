"""Migrate up and down on a fresh database (CI gate: DB migrations up/down)."""

import psycopg
import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError

from pi_db import alembic_config
from pi_db.migrations.versions.v0001_schema_v1 import TABLES

pytestmark = pytest.mark.db


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _objects(url: str) -> tuple[set[str], set[str], set[str]]:
    with psycopg.connect(_libpq(url)) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
                " AND NOT c.relispartition"
            )
        }
        types = {
            r[0]
            for r in conn.execute(
                "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace"
                " WHERE n.nspname = 'public' AND t.typtype = 'e'"
            )
        }
        functions = {
            r[0]
            for r in conn.execute(
                "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = 'public' AND p.proname LIKE 'pi\\_%'"
            )
        }
    return tables, types, functions


def test_upgrade_downgrade_upgrade_on_fresh_db(empty_db: str) -> None:
    config = alembic_config(empty_db)

    command.upgrade(config, "head")
    tables, types, functions = _objects(empty_db)
    assert tables == {*TABLES, "alembic_version"}
    assert len(TABLES) == 24
    assert {"availability_state", "field_state", "source_kind", "image_role"} <= types
    assert len(functions) == 4

    command.downgrade(config, "base")
    assert _objects(empty_db) == ({"alembic_version"}, set(), set())

    command.upgrade(config, "head")
    assert _objects(empty_db)[0] == {*TABLES, "alembic_version"}


def _evidence_checks(url: str) -> dict[str, str]:
    with psycopg.connect(_libpq(url)) as conn:
        return {
            str(name): str(definition)
            for name, definition in conn.execute(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conrelid = 'evidence'::regclass AND contype = 'c'"
                " AND pg_get_constraintdef(oid) LIKE '%fetch_method%'"
            )
        }


def _fetch_methods(url: str) -> list[str]:
    with psycopg.connect(_libpq(url)) as conn:
        row = conn.execute("SELECT enum_range(NULL::fetch_method)::text[]").fetchone()
    assert row is not None
    return list(row[0])


def test_0003_offline_import_up_down(empty_db: str) -> None:
    """0003 adds offline_import on rung 0; its downgrade restores 0001's CHECK, keeps the label."""
    config = alembic_config(empty_db)

    command.upgrade(config, "0002")
    before = _evidence_checks(empty_db)
    assert set(before) == {"evidence_check"}
    assert "offline_import" not in _fetch_methods(empty_db)

    command.upgrade(config, "0003")
    after = _evidence_checks(empty_db)
    assert set(after) == {"evidence_method_rung_check"}
    assert "WHEN 'offline_import'::text THEN 0" in after["evidence_method_rung_check"]
    assert _fetch_methods(empty_db)[-1] == "offline_import"

    command.downgrade(config, "0002")
    assert _evidence_checks(empty_db) == before
    assert "offline_import" in _fetch_methods(empty_db)  # PostgreSQL cannot drop enum labels

    command.upgrade(config, "head")  # ADD VALUE IF NOT EXISTS: re-upgrade is a no-op
    assert _evidence_checks(empty_db) == after


def _variant_columns(url: str) -> set[str]:
    with psycopg.connect(_libpq(url)) as conn:
        return {
            str(name)
            for (name,) in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'variant'"
            )
        }


def test_0004_attributes_schema_up_down(empty_db: str) -> None:
    """0004 only adds variant.attributes_schema; its downgrade removes exactly that."""
    config = alembic_config(empty_db)

    command.upgrade(config, "0003")
    before = _variant_columns(empty_db)
    assert "attributes_schema" not in before

    command.upgrade(config, "0004")
    assert _variant_columns(empty_db) == before | {"attributes_schema"}

    command.downgrade(config, "0003")
    assert _variant_columns(empty_db) == before


def _content_seed(url: str) -> object:
    """One source listing, so 0004-shaped content rows can be written."""
    with psycopg.connect(_libpq(url)) as conn:
        source = conn.execute(
            "INSERT INTO source (name, kind) VALUES ('s', 'web') RETURNING id"
        ).fetchone()
        assert source is not None
        listing = conn.execute(
            "INSERT INTO source_listing (source_id, source_listing_key, url, name_original,"
            " first_seen_at, last_seen_at) VALUES (%s, 'P1', 'https://example.test/p/1', 'n',"
            " now(), now()) RETURNING id",
            (source[0],),
        ).fetchone()
        assert listing is not None
        return listing[0]


def _content(url: str, listing: object, observed: str, content_hash: str) -> None:
    with psycopg.connect(_libpq(url)) as conn:
        conn.execute(
            "INSERT INTO listing_content (listing_id, observed_at, content_hash)"
            " VALUES (%s, %s, %s)",
            (listing, observed, content_hash),
        )


def _content_shape(url: str) -> tuple[set[str], list[str], set[str], int]:
    with psycopg.connect(_libpq(url)) as conn:
        columns = {
            str(name)
            for (name,) in conn.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'listing_content'"
            )
        }
        key = [
            str(name)
            for (name,) in conn.execute(
                "SELECT a.attname FROM pg_index i"
                " JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)"
                " WHERE i.indrelid = 'listing_content'::regclass AND i.indisprimary"
                " ORDER BY array_position(i.indkey, a.attnum)"
            )
        ]
        indexes = {
            str(name)
            for (name,) in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'listing_content'"
            )
        }
        rows = conn.execute("SELECT count(*) FROM listing_content").fetchone()
        assert rows is not None
        return columns, key, indexes, int(rows[0])


def test_0005_recorded_at_up_down_keeps_rows(empty_db: str) -> None:
    """0005 adds recorded_at to the key and the triple index; down restores 0004 exactly."""
    config = alembic_config(empty_db)
    command.upgrade(config, "0004")
    listing = _content_seed(empty_db)
    _content(empty_db, listing, "2026-10-01T00:00:00Z", "a")
    _content(empty_db, listing, "2026-10-02T00:00:00Z", "b")
    before = _content_shape(empty_db)
    assert before[1] == ["listing_id", "observed_at"]

    command.upgrade(config, "0005")
    columns, key, indexes, rows = _content_shape(empty_db)
    assert columns == before[0] | {"recorded_at"}
    assert key == ["listing_id", "observed_at", "recorded_at"]
    assert indexes == before[2] | {"listing_content_observed_hash_key"}
    assert rows == 2
    with psycopg.connect(_libpq(empty_db)) as conn:
        # existing rows are dated at the migration, never earlier than they were known
        stamped = conn.execute(
            "SELECT count(*) FROM listing_content WHERE recorded_at > observed_at"
        ).fetchone()
        assert stamped == (2,)

    command.downgrade(config, "0004")
    assert _content_shape(empty_db) == before

    command.upgrade(config, "0005")
    assert _content_shape(empty_db)[3] == 2


def test_0005_downgrade_refuses_rather_than_drop_rows(empty_db: str) -> None:
    """Two rows at one (listing, observed_at) cannot fit the 0004 key: STOP, delete nothing."""
    config = alembic_config(empty_db)
    command.upgrade(config, "0005")
    listing = _content_seed(empty_db)
    _content(empty_db, listing, "2026-10-01T00:00:00Z", "old")
    _content(empty_db, listing, "2026-10-01T00:00:00Z", "rederived")

    with pytest.raises(DBAPIError, match="STOP: 1 \\(listing_id, observed_at\\) pairs"):
        command.downgrade(config, "0004")
    columns, key, _, rows = _content_shape(empty_db)
    assert "recorded_at" in columns
    assert key == ["listing_id", "observed_at", "recorded_at"]
    assert rows == 2


def test_0005_upgrade_stops_on_existing_triple_duplicates(empty_db: str) -> None:
    """A duplicate (listing, observed_at, hash) under the 0004 key cannot exist, so the STOP is
    proven by widening the key by hand first; the migration counts and never deduplicates."""
    config = alembic_config(empty_db)
    command.upgrade(config, "0004")
    listing = _content_seed(empty_db)
    with psycopg.connect(_libpq(empty_db)) as conn:
        conn.execute("ALTER TABLE listing_content DROP CONSTRAINT listing_content_pkey")
    _content(empty_db, listing, "2026-10-01T00:00:00Z", "same")
    _content(empty_db, listing, "2026-10-01T00:00:00Z", "same")

    with pytest.raises(DBAPIError, match="STOP: 1 \\(listing_id, observed_at, content_hash\\)"):
        command.upgrade(config, "0005")
    columns, _, _, rows = _content_shape(empty_db)
    assert "recorded_at" not in columns
    assert rows == 2
