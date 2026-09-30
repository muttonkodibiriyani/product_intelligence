"""UAT-11 · Menu item identity (MAT-01, MAT-02)."""

from uat.registry import pending, scenario


@scenario(
    "UAT-11",
    "m2",
    reqs=("MAT-01", "MAT-02"),
    out_of_scope=("food (burger menu item identity) is not in the beauty pilot"),
)
def test_uat_11_menu_item_identity() -> None:
    """Menu item identity.

    Check: similar-named burgers with different patty counts are not an exact match.
    """
    pending()
