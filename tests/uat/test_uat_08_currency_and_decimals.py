"""UAT-08 · Currency and decimals (PRC-03, DQ-03)."""

from uat.registry import pending, scenario


@scenario("UAT-08", "m1", reqs=("PRC-03", "DQ-03"))
def test_uat_08_currency_and_decimals() -> None:
    """Currency and decimals.

    Check: decimal-comma, three-decimal currency and Arabic-Indic numeral fixtures keep exact
           values and currency through parsing and export (pilot market UAE/AED; fixtures stay
           market-parameterised).
    """
    pending()
