"""UAT-29 · Unsafe source URL (SEC-08)."""

from uat.registry import pending, scenario


@scenario(
    "UAT-29",
    "m4",
    reqs=("SEC-08",),
    out_of_scope=("SEC-08 safe URL ingestion is later scope (no user-submitted URLs in the pilot)"),
)
def test_uat_29_unsafe_source_url() -> None:
    """Unsafe source URL.

    Check: URLs resolving to internal or metadata addresses, including via redirects, are
           blocked and audited.
    """
    pending()
