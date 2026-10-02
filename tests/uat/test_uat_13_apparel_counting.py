"""UAT-13 · Apparel counting (ANL-05, ANL-07)."""

from uat.registry import pending, scenario


@scenario("UAT-13", "m3", reqs=("ANL-05", "ANL-07"))
def test_uat_13_apparel_counting() -> None:
    """Apparel counting.

    Check: one family with 3 colours x 5 sizes reports family, colourway, variant and available-
           size counts separately (beauty analogue: shades x sizes).
    """
    pending()
