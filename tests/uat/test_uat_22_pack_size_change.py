"""UAT-22 · Pack-size change (ANL-10, CAT-04)."""

from uat.registry import pending, scenario


@scenario("UAT-22", "m3", reqs=("ANL-10", "CAT-04"))
def test_uat_22_pack_size_change() -> None:
    """Pack-size change.

    Check: 250 g at 100 succeeded by 200 g at 100 gives ticket change 0%, quantity change -20%,
           unit-price change +25%.
    """
    pending()
