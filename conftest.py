"""Session guard for every test run: never run tests against a real pi_db (see db_url_guard)."""

import os

import pytest
from db_url_guard import ProtectedDatabaseError, check


def pytest_configure(config: pytest.Config) -> None:
    try:
        check(os.environ.get("PI_DATABASE_URL"), ci=bool(os.environ.get("CI")))
    except ProtectedDatabaseError as exc:
        raise pytest.UsageError(f"refusing to run tests: {exc}") from None
