"""UAT-07 · Tax mismatch (PRC-04)."""

from uat.registry import pending, scenario


@scenario("UAT-07", "m1", reqs=("PRC-04",))
def test_uat_07_tax_mismatch() -> None:
    """Tax mismatch.

    Check: a tax-included vs tax-unknown comparison is blocked or explicitly exploratory until
           the basis aligns.
    """
    pending()
