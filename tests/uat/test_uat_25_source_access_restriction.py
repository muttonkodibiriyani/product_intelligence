"""UAT-25 · Source-access restriction (SRC-08, SEC-05)."""

from uat.registry import pending, scenario


@scenario(
    "UAT-25",
    "m1",
    reqs=("SRC-08", "SEC-05"),
    out_of_scope=(
        "SRC-08/SEC-05 are owner deviations (ADR-0003): collection escalates instead of "
        "stopping; the replacement control is asserted by the SRC-08 and SEC-05 cases"
    ),
)
def test_uat_25_source_access_restriction() -> None:
    """Source-access restriction.

    Check: revoked approval or an access block stops collection visibly with no bypass
           (superseded by ADR-0003).
    """
    pending()
