"""UAT-06 · Unknown basket fee (PRC-08)."""

from uat.registry import pending, scenario


@scenario(
    "UAT-06",
    "m1",
    reqs=("PRC-08",),
    out_of_scope=(
        "PRC-08 total payable basket (delivery/service fees) is later scope (Scale gate)"
    ),
)
def test_uat_06_unknown_basket_fee() -> None:
    """Unknown basket fee.

    Check: a delivered basket with an unknown service fee is reported incomplete, never falsely
           exact.
    """
    pending()
