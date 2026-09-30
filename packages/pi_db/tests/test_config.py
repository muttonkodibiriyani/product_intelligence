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
    enum = _pi_core_str_enums().get(class_name)
    if enum is None:
        pytest.skip(f"pi_core does not export {class_name} yet")
    assert migration_0001().SCHEMA_ENUMS[pg_type] == tuple(m.value for m in enum)


def test_migration_covers_every_pi_core_str_enum() -> None:
    module = migration_0001()
    mapped = {e.__name__ for e in PI_CORE_ENUM_TYPES.values()} | set(SCHEMA_ENUM_CLASSES.values())
    assert set(_pi_core_str_enums()) - TEXT_ENUM_CLASSES <= mapped
    assert set(module.PI_CORE_ENUMS) == set(PI_CORE_ENUM_TYPES)
    assert set(module.SCHEMA_ENUMS) == set(SCHEMA_ENUM_CLASSES)


def test_fetch_method_rungs_match_pi_core() -> None:
    module = migration_0001()
    assert set(module.FETCH_METHOD_RUNG) == set(module.SCHEMA_ENUMS["fetch_method"])
    methods = _pi_core_str_enums().get("FetchMethod")
    if methods is None:
        pytest.skip("pi_core does not export FetchMethod yet")
    assert {m.value: int(m.rung) for m in methods} == module.FETCH_METHOD_RUNG  # type: ignore[attr-defined]


def test_forbidden_rungs_match_pi_core_policy() -> None:
    """Rung 3 (stealth browsers) is disabled program-wide; pi_core and the schema must agree."""
    forbidden = set(migration_0001().FORBIDDEN_RUNGS)
    assert forbidden == {3}
    policy = getattr(pi_core, "FORBIDDEN_RUNGS", None)
    if policy is None and hasattr(pi_core.LadderRung, "is_permitted"):
        policy = {r for r in pi_core.LadderRung if not getattr(r, "is_permitted")}  # noqa: B009
    if policy is None:
        pytest.skip("pi_core has no rung policy yet")
    assert {int(r) for r in policy} == forbidden


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
