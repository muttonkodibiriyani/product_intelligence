"""db_url_guard: test runs refuse the pi_db servers and the stack database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from db_url_guard import ProtectedDatabaseError, check

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "postgresql+psycopg://pi:pw@127.0.0.1:55433/pi_test",
        "postgresql://u:pw@localhost:6543/anything",
    ],
)
def test_allows_unset_or_throwaway(url: str | None) -> None:
    check(url)


@pytest.mark.parametrize("ci", [False, True])
@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://pi:pw@127.0.0.1:55432/pi",
        "postgresql+psycopg://pi:pw@127.0.0.1:55432/pi_test",
        "postgresql+psycopg://pi:pw@localhost:55499/other",
        "postgresql://pi:pw@127.0.0.1/pi_test",
        "postgresql://pi:pw@127.0.0.1:notaport/pi_test",
        "postgresql:///pi_test",
    ],
)
def test_refuses_protected_server_even_in_ci(url: str, ci: bool) -> None:
    with pytest.raises(ProtectedDatabaseError):
        check(url, ci=ci)


def test_stack_database_name_is_refused_outside_ci() -> None:
    url = "postgresql+psycopg://pi:pw@127.0.0.1:5432/pi"
    with pytest.raises(ProtectedDatabaseError, match="'pi'"):
        check(url)
    check(url, ci=True)  # CI's disposable service container (ci.yml) is named pi


def test_pytest_refuses_before_any_test_runs() -> None:
    """The root conftest stops the whole session: exit code 4 (usage error), nothing collected."""
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    env["PI_DATABASE_URL"] = "postgresql+psycopg://pi:pw@127.0.0.1:55432/pi"
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            "--co",
            "infra/tests/test_db_url_guard.py",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == pytest.ExitCode.USAGE_ERROR, out.stdout + out.stderr
    assert "refusing to run tests" in out.stdout + out.stderr
