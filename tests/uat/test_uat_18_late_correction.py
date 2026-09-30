"""UAT-18 · Late correction (DAT-03, DAT-08, DQ-09)."""

from uat.registry import pending, scenario


@scenario("UAT-18", "m1", reqs=("DAT-03", "DAT-08", "DQ-09"))
def test_uat_18_late_correction() -> None:
    """Late correction.

    Check: correcting a prior observation keeps the as-known report and labels the traceable
           restatement.
    """
    pending()
