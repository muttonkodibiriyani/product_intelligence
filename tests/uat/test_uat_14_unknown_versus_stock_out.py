"""UAT-14 · Unknown versus stock-out (DAT-06, DQ-02)."""

from uat.registry import pending, scenario


@scenario("UAT-14", "m1", reqs=("DAT-06", "DQ-02"))
def test_uat_14_unknown_versus_stock_out() -> None:
    """Unknown versus stock-out.

    Check: a failed crawl of previously in-stock items records not-observed/failed, never a mass
           out-of-stock event.
    """
    pending()
