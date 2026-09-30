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
