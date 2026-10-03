"""Refuse a test run whose PI_DATABASE_URL points at a real pi_db.

DB tests create and drop ``pi_test_*`` databases on the server named by PI_DATABASE_URL. On
2026-10-03 a plain ``make check`` used the old Makefile default (the stack database on port
55432), filled that server's disk and crashed pi_db. Tests now run against a throwaway tmpfs
server (``make test-db``); the root ``conftest.py`` calls :func:`check` before any test runs.
"""

from urllib.parse import urlsplit

# Ports of the pi_db servers on the shared build server; never a test target.
PROTECTED_PORTS = frozenset({55432, 55499})
# The stack database name. CI's own disposable service also uses it, so CI is exempt from this
# one rule (never from the port rule) until its URL names a test database.
PROTECTED_DATABASE = "pi"


class ProtectedDatabaseError(Exception):
    """PI_DATABASE_URL names a database that tests must never touch."""


def check(url: str | None, *, ci: bool = False) -> None:
    """Raise ProtectedDatabaseError unless ``url`` is unset or a disposable test database."""
    if not url:
        return
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ProtectedDatabaseError(f"PI_DATABASE_URL is not a valid URL ({exc})") from None
    if parts.hostname is None:
        raise ProtectedDatabaseError("PI_DATABASE_URL has no host; name the test server explicitly")
    if port is None:
        raise ProtectedDatabaseError("PI_DATABASE_URL has no port; name the test server's port")
    if port in PROTECTED_PORTS:
        raise ProtectedDatabaseError(
            f"PI_DATABASE_URL port {port} is a pi_db server, never a test target. "
            "Run `make test-db` and use its URL"
        )
    database = parts.path.lstrip("/")
    if database == PROTECTED_DATABASE and not ci:
        raise ProtectedDatabaseError(
            f"PI_DATABASE_URL names database {PROTECTED_DATABASE!r}, the stack database. "
            "Run `make test-db` and use its URL"
        )
