"""Tests that need no database: configuration, frozen migration constants, offline SQL."""

from enum import StrEnum
from types import ModuleType

import pytest
from alembic import command
from alembic.script import ScriptDirectory

import pi_core
import pi_db
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


def migration_0001() -> ModuleType:
    script = ScriptDirectory.from_config(alembic_config()).get_revision("0001")
    assert script is not None
    return script.module


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
    assert script.get_heads() == ["0001"]


@pytest.mark.parametrize(("pg_type", "enum"), PI_CORE_ENUM_TYPES.items())
def test_migration_enum_values_match_pi_core(pg_type: str, enum: type[StrEnum]) -> None:
    assert migration_0001().PI_CORE_ENUMS[pg_type] == tuple(m.value for m in enum)


def test_migration_covers_every_pi_core_str_enum() -> None:
    exported = {
        obj
        for name in pi_core.__all__
        if isinstance(obj := getattr(pi_core, name), type) and issubclass(obj, StrEnum)
    }
    assert exported == set(PI_CORE_ENUM_TYPES.values())
    assert set(migration_0001().PI_CORE_ENUMS) == set(PI_CORE_ENUM_TYPES)


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
