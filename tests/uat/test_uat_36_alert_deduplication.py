"""UAT-36 · Alert deduplication (SRC-10, EXP-07)."""

from uat.registry import pending, scenario


@scenario("UAT-36", "m3", reqs=("SRC-10", "EXP-07"))
def test_uat_36_alert_deduplication() -> None:
    """Alert deduplication.

    Check: replaying a price-change event and retrying a failed delivery yields one alert with
           traceable retries and acks.
    """
    pending()
