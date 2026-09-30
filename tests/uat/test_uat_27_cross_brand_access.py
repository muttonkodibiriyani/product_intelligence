"""UAT-27 · Cross-brand access (SCP-04, SEC-02)."""

from uat.registry import pending, scenario


@scenario("UAT-27", "m4", reqs=("SCP-04", "SEC-02"))
def test_uat_27_cross_brand_access() -> None:
    """Cross-brand access.

    Check: another restricted brand is denied via UI, API, export and AI without leaking record
           existence or content.
    """
    pending()
