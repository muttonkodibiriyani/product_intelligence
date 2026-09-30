"""UAT-10 · Pickup is not dine-in (PRC-14)."""

from uat.registry import pending, scenario


@scenario(
    "UAT-10",
    "m1",
    reqs=("PRC-14",),
    out_of_scope=("food/dine-in (restaurant pickup vs dine-in menus) is not in the beauty pilot"),
)
def test_uat_10_pickup_is_not_dine_in() -> None:
    """Pickup is not dine-in.

    Check: a pickup menu price without dine-in evidence stays pickup; dine-in is unavailable.
    """
    pending()
