"""UAT-25 · Source-access restriction (SRC-08, SEC-05)."""

from uat.registry import pending, scenario


@scenario("UAT-25", "m1", reqs=("SRC-08", "SEC-05"))
def test_uat_25_source_access_restriction() -> None:
    """Source-access restriction.

    Check: when a source's approval is revoked, or access stays blocked after the rungs the owner
           has approved for it (ADR-0003 ladder, ADR-0005 per-source approvals), the source is
           marked blocked and collection stops. The coverage loss is visible and reported, and no
           escalation beyond the approved rungs is attempted. Fixture-driven (recorded 403/429/
           challenge pages), market-parameterised with UAE as the pilot market.
    """
    pending()
