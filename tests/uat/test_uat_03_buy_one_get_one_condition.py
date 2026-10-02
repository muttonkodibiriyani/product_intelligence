"""UAT-03 · Buy-one-get-one condition (PRC-09, PRC-10)."""

from uat.registry import pending, scenario


@scenario("UAT-03", "m1", reqs=("PRC-09", "PRC-10"))
def test_uat_03_buy_one_get_one_condition() -> None:
    """Buy-one-get-one condition.

    Check: a two-unit BOGO with required payment 120 shows required spend 120, quantity received
           2 and effective unit price 60.
    """
    pending()
