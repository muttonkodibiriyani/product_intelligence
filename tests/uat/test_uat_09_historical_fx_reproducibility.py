"""UAT-09 · Historical FX reproducibility (PRC-07, DAT-08)."""

from uat.registry import pending, scenario


@scenario("UAT-09", "m3", reqs=("PRC-07", "DAT-08"))
def test_uat_09_historical_fx_reproducibility() -> None:
    """Historical FX reproducibility.

    Check: a saved converted-price report reproduces its original result with its pinned FX rate
           after rates change.
    """
    pending()
