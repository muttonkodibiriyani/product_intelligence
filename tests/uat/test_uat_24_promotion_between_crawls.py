"""UAT-24 · Promotion between crawls (PRC-15, SRC-07)."""

from uat.registry import pending, scenario


@scenario("UAT-24", "m1", reqs=("PRC-15", "SRC-07"))
def test_uat_24_promotion_between_crawls() -> None:
    """Promotion between crawls.

    Check: a promotion falling entirely between weekly observations is not claimed as detected
           or continuously covered.
    """
    pending()
