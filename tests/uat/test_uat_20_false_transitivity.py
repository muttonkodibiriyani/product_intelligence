"""UAT-20 · False transitivity (MAT-09)."""

from uat.registry import pending, scenario


@scenario("UAT-20", "m2", reqs=("MAT-09",))
def test_uat_20_false_transitivity() -> None:
    """False transitivity.

    Check: approving A~B and B~C never creates an exact A-C match.
    """
    pending()
