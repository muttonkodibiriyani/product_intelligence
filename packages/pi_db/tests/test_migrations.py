"""Migrate up and down on a fresh database (CI gate: DB migrations up/down)."""

import psycopg
import pytest
from alembic import command

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
