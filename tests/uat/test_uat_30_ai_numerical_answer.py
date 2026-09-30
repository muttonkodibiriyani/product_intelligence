"""UAT-30 · AI numerical answer (AIG-01, AIG-02)."""

from uat.registry import pending, scenario


@scenario("UAT-30", "m4", reqs=("AIG-01", "AIG-02"))
def test_uat_30_ai_numerical_answer() -> None:
    """AI numerical answer.

    Check: the cheaper saved exact basket this week equals the governed calculation and cites
           cohort, time and sources.
    """
    pending()
