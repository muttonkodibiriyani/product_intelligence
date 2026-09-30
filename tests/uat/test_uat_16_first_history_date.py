"""UAT-16 · First history date (SRC-15, DAT-07)."""

from uat.registry import pending, scenario


@scenario("UAT-16", "m1", reqs=("SRC-15", "DAT-07"))
def test_uat_16_first_history_date() -> None:
    """First history date.

    Check: a one-year history request against one month of valid data leaves eleven months
           visibly unavailable, never filled.
    """
    pending()
