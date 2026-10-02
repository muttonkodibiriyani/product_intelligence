"""UAT-34 · Contract exit (DAT-11, INT-09)."""

from uat.registry import pending, scenario


@scenario("UAT-34", "m4", reqs=("DAT-11", "INT-09"))
def test_uat_34_contract_exit() -> None:
    """Contract exit.

    Check: an exported sample month ingests independently and its totals and selected reports
           reconcile.
    """
    pending()
