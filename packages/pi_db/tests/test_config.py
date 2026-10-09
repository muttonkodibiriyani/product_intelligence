"""Tests that need no database: configuration, frozen migration constants, offline SQL."""

from enum import StrEnum
from types import ModuleType

import pytest
from alembic import command
from alembic.script import ScriptDirectory

import pi_core
import pi_db
import pi_profiles
from pi_db import DATABASE_URL_ENV, DatabaseUrlMissingError, alembic_config, database_url

PI_CORE_ENUM_TYPES: dict[str, type[StrEnum]] = {
    "availability_state": pi_core.AvailabilityState,
    "field_state": pi_core.FieldState,
    "price_type": pi_core.PriceType,
    "tax_status": pi_core.TaxStatus,
    "channel": pi_core.Channel,
    "match_class": pi_core.MatchClass,
    "review_state": pi_core.ReviewState,
    "quality_status": pi_core.QualityStatus,
    "coverage_status": pi_core.CoverageStatus,
}


def _migration(revision: str) -> ModuleType:
    script = ScriptDirectory.from_config(alembic_config()).get_revision(revision)
    assert script is not None
    return script.module


def migration_0001() -> ModuleType:
    return _migration("0001")


def migration_0003() -> ModuleType:
    return _migration("0003")


def schema_enum_at_head(pg_type: str) -> tuple[str, ...]:
    """0001's labels plus the ones later revisions appended (0003: fetch_method)."""
    added: tuple[str, ...] = migration_0003().NEW_FETCH_METHODS if pg_type == "fetch_method" else ()
    return tuple(migration_0001().SCHEMA_ENUMS[pg_type]) + added


def test_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql+psycopg://u@h/db")
    assert database_url() == "postgresql+psycopg://u@h/db"


def test_database_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(DatabaseUrlMissingError, match=DATABASE_URL_ENV):
        database_url()


def test_alembic_config_escapes_percent_in_url() -> None:
    config = alembic_config("postgresql+psycopg://u:p%40ss@h/db")
    assert config.get_main_option("sqlalchemy.url") == "postgresql+psycopg://u:p%40ss@h/db"
    assert config.get_main_option("script_location") == str(pi_db.MIGRATIONS_DIR)


def test_single_linear_head() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_heads() == ["0005"]
    assert [r.revision for r in script.walk_revisions()] == ["0005", "0004", "0003", "0002", "0001"]


def test_0002_only_qualifies_the_enum() -> None:
    from pi_db.migrations.versions.v0002_qualify_field_state_enum import (  # noqa: PLC0415
        FIELD_STATE_VALID_SQL,
    )

    assert "NULL::public.field_state" in FIELD_STATE_VALID_SQL
    assert "NULL::field_state" not in FIELD_STATE_VALID_SQL
    # Still inlinable: plain SQL, no SET clause.
    assert "LANGUAGE sql STABLE AS" in FIELD_STATE_VALID_SQL
    assert "SET search_path" not in FIELD_STATE_VALID_SQL


def test_0003_follows_0002() -> None:
    assert migration_0003().down_revision == "0002"


# Schema enums whose pi_core class lands in PR3 (#6); checked as soon as pi_core exports it.
SCHEMA_ENUM_CLASSES = {
    "source_kind": "SourceKind",
    "image_role": "ImageRole",
    "fetch_method": "FetchMethod",
}
# pi_core vocabularies stored as text or char(n) and validated in pi_core, not Postgres enums.
TEXT_ENUM_CLASSES = {"Market", "Locale", "Device", "Concentration", "PromotionMechanic"}


def _pi_core_str_enums() -> dict[str, type[StrEnum]]:
    return {
        name: obj
        for name in pi_core.__all__
        if isinstance(obj := getattr(pi_core, name), type) and issubclass(obj, StrEnum)
    }


@pytest.mark.parametrize(("pg_type", "enum"), PI_CORE_ENUM_TYPES.items())
def test_migration_enum_values_match_pi_core(pg_type: str, enum: type[StrEnum]) -> None:
    assert migration_0001().PI_CORE_ENUMS[pg_type] == tuple(m.value for m in enum)


@pytest.mark.parametrize(("pg_type", "class_name"), SCHEMA_ENUM_CLASSES.items())
def test_schema_enum_values_match_pi_core(pg_type: str, class_name: str) -> None:
    enum = _pi_core_str_enums()[class_name]
    assert schema_enum_at_head(pg_type) == tuple(m.value for m in enum)


def test_migration_covers_every_pi_core_str_enum() -> None:
    module = migration_0001()
    mapped = {e.__name__ for e in PI_CORE_ENUM_TYPES.values()} | set(SCHEMA_ENUM_CLASSES.values())
    assert set(_pi_core_str_enums()) - TEXT_ENUM_CLASSES <= mapped
    assert set(module.PI_CORE_ENUMS) == set(PI_CORE_ENUM_TYPES)
    assert set(module.SCHEMA_ENUMS) == set(SCHEMA_ENUM_CLASSES)


def test_fetch_method_rungs_match_pi_core() -> None:
    v1, v3 = migration_0001(), migration_0003()
    assert set(v1.FETCH_METHOD_RUNG) == set(v1.SCHEMA_ENUMS["fetch_method"])
    # 0003 widens 0001's map without changing any existing method's rung.
    assert v1.FETCH_METHOD_RUNG == v3.FETCH_METHOD_RUNG_BEFORE
    assert set(v3.FETCH_METHOD_RUNG) == set(schema_enum_at_head("fetch_method"))
    assert {m.value: int(m.rung) for m in pi_core.FetchMethod} == v3.FETCH_METHOD_RUNG
    assert v3.FETCH_METHOD_RUNG["offline_import"] == int(pi_core.LadderRung.SITE_DATA)


def test_forbidden_rungs_match_pi_core_policy() -> None:
    """Rung 3 (stealth browsers) is disabled program-wide; pi_core and the schema must agree."""
    forbidden = set(migration_0001().FORBIDDEN_RUNGS)
    assert forbidden == {3}
    assert {int(r) for r in pi_core.FORBIDDEN_RUNGS} == forbidden
    assert {int(r) for r in pi_core.LadderRung if not r.is_permitted} == forbidden


def test_migration_constants_match_package() -> None:
    module = migration_0001()
    assert max(pi_core.LadderRung) == module.LADDER_RUNG_MAX
    assert module.IMAGE_EMBEDDING_DIM == pi_db.IMAGE_EMBEDDING_DIM
    assert module.TEXT_EMBEDDING_DIM == pi_db.TEXT_EMBEDDING_DIM
    assert module.APP_ROLE == pi_db.APP_ROLE


def test_offline_sql_renders(capsys: pytest.CaptureFixture[str]) -> None:
    command.upgrade(alembic_config("postgresql+psycopg://offline/pi"), "head", sql=True)
    sql = capsys.readouterr().out
    assert "PARTITION BY RANGE (observed_at)" in sql
    assert f"vector({pi_db.IMAGE_EMBEDDING_DIM})" in sql
    assert "GRANT SELECT, INSERT ON evidence" in sql
    assert "ALTER TYPE fetch_method ADD VALUE IF NOT EXISTS 'offline_import'" in sql
    assert "WHEN 'offline_import' THEN 0" in sql
    assert "ADD COLUMN attributes_schema text" in sql
    # 0005's STOP checks are SQL, so the preview shows them before the key swap
    assert "%" not in sql[sql.index("Running upgrade 0004 -> 0005") :]
    assert sql.index(
        "(listing_id, observed_at, content_hash) groups hold more than one row"
    ) < sql.index("PRIMARY KEY (listing_id, observed_at, recorded_at)")


def test_attributes_schema_pattern_matches_pi_profiles() -> None:
    """The DB CHECK and the profile registry accept exactly the same refs."""
    assert pi_profiles.REF_PATTERN.pattern == _migration("0004").REF_PATTERN
