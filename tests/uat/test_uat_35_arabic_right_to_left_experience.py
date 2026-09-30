"""UAT-35 · Arabic right-to-left experience (SCP-06, EXP-10)."""

from uat.registry import pending, scenario


@scenario("UAT-35", "m3", reqs=("SCP-06", "EXP-10"))
def test_uat_35_arabic_right_to_left_experience() -> None:
    """Arabic right-to-left experience.

    Check: search, compare, filter and export in Arabic and English keep original text, RTL
           layout, numbers and filters.
    """
    pending()
