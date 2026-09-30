"""UAT-17 · Idempotent replay (DAT-09, INT-02)."""

from uat.registry import pending, scenario


@scenario("UAT-17", "m4", reqs=("DAT-09", "INT-02"))
def test_uat_17_idempotent_replay() -> None:
    """Idempotent replay.

    Check: replaying the same accepted batch leaves observation counts, trend points and alerts
           unchanged.
    """
    pending()
