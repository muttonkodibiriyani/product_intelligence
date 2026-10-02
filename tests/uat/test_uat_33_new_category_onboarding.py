"""UAT-33 · New category onboarding (SCP-01, SCP-12, CAT-05)."""

from uat.registry import pending, scenario


@scenario(
    "UAT-33",
    "m0",
    reqs=("SCP-01", "SCP-12", "CAT-05"),
    out_of_scope=("electronics category is not in the beauty pilot; SCP-01 keeps its own case"),
)
def test_uat_33_new_category_onboarding() -> None:
    """New category onboarding.

    Check: adding an electronics category leaves existing food, fashion and beauty schemas and
           reports correct.
    """
    pending()
