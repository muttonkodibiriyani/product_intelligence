"""UAT-02 · Candle size comparability (CAT-03, PRC-05, MAT-01)."""

from uat.registry import pending, scenario


@scenario("UAT-02", "m2", reqs=("CAT-03", "PRC-05", "MAT-01"))
def test_uat_02_candle_size_comparability() -> None:
    """Candle size comparability.

    Check: 200 g at 80 vs 300 g at 99 (same currency and tax basis) gives 40 vs 33 per 100 g,
           the first 21.21% dearer per unit, and is not an exact match.
    """
    pending()
