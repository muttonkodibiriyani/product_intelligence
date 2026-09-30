"""UAT-23 · Fresh versus stale offer (MAT-11, DQ-08)."""

from uat.registry import pending, scenario


@scenario("UAT-23", "m2", reqs=("MAT-11", "DQ-08"))
def test_uat_23_fresh_versus_stale_offer() -> None:
    """Fresh versus stale offer.

    Check: a competitor observation beyond the freshness limit is excluded from certified rank
           or warned in exploratory mode.
    """
    pending()
