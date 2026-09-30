"""UAT-05 · Member versus public (PRC-01, PRC-09)."""

from uat.registry import pending, scenario


@scenario("UAT-05", "m1", reqs=("PRC-01", "PRC-09"))
def test_uat_05_member_versus_public() -> None:
    """Member versus public.

    Check: a members-only lower price is labelled conditional and excluded from the default
           public index.
    """
    pending()
