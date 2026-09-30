"""UAT-21 · Fixed basket stability (ANL-02, MAT-10)."""

from uat.registry import pending, scenario


@scenario("UAT-21", "m3", reqs=("ANL-02", "MAT-10"))
def test_uat_21_fixed_basket_stability() -> None:
    """Fixed basket stability.

    Check: removing a competitor item from a frozen basket applies the missing-item policy
           visibly without silent reweighting.
    """
    pending()
