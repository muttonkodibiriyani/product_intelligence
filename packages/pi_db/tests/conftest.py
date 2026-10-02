"""Database fixtures. DB tests need PI_DATABASE_URL (``make up``); they skip when it is unset or
unreachable, except in CI (``CI`` set), where an unreachable database is an error."""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from sqlalchemy.engine import make_url

from pi_db import DATABASE_URL_ENV, alembic_config


def _libpq(url: str) -> str:
    """psycopg connection string from a SQLAlchemy URL."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def server_url() -> str:
    """Server for DB tests. Locally they skip when it is unset or down; in CI they must run."""
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{DATABASE_URL_ENV} not set; run `make up` and export it")
    try:
        psycopg.connect(_libpq(url), connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"database at {DATABASE_URL_ENV} unreachable (run `make up`): {exc}")
    return url


@pytest.fixture
def empty_db(server_url: str) -> Iterator[str]:
    """A brand-new database on the configured server; dropped afterwards."""
    name = f"pi_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq(server_url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_url(server_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(_libpq(server_url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def migrated_db(server_url: str) -> Iterator[str]:
    """One database at ``head`` shared by a module's read-mostly tests."""
    name = f"pi_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq(server_url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_url(server_url).set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        with psycopg.connect(_libpq(server_url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def conn(migrated_db: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Connection to the migrated database; every test's writes are rolled back."""
    with psycopg.connect(_libpq(migrated_db)) as connection:
        yield connection
        connection.rollback()
