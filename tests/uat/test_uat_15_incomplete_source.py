"""UAT-15 · Incomplete source (SRC-03, DQ-04)."""

from uat.registry import pending, scenario


@scenario("UAT-15", "m1", reqs=("SRC-03", "DQ-04"))
def test_uat_15_incomplete_source() -> None:
    """Incomplete source.

    Check: interrupted pagination shows partial coverage and asserts no removals from the
           incomplete snapshot.
    """
    pending()
