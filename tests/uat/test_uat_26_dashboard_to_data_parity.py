"""UAT-26 · Dashboard-to-data parity (EXP-06, INT-01)."""

from uat.registry import pending, scenario


@scenario("UAT-26", "m4", reqs=("EXP-06", "INT-01"))
def test_uat_26_dashboard_to_data_parity() -> None:
    """Dashboard-to-data parity.

    Check: a filtered dashboard export rebuilt from delivered facts reconciles values, cohort,
           cutoff, rounding and exclusions.
    """
    pending()
