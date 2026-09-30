"""UAT-32 · Backup and restore (DAT-12, OPS-03)."""

from uat.registry import pending, scenario


@scenario("UAT-32", "m5", reqs=("DAT-12", "OPS-03"))
def test_uat_32_backup_and_restore() -> None:
    """Backup and restore.

    Check: a restored test environment reproduces published comparisons and access decisions
           within the recovery objective.
    """
    pending()
