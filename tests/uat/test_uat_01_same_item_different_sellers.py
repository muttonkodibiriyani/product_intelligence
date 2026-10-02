"""UAT-01 · Same item, different sellers (CAT-01, CAT-11, DAT-02)."""

from uat.registry import pending, scenario


@scenario("UAT-01", "m0", reqs=("CAT-01", "CAT-11", "DAT-02"))
def test_uat_01_same_item_different_sellers() -> None:
    """Same item, different sellers.

    Check: one GTIN offered by two sellers yields one variant identity with separate seller
           offers and prices.
    """
    pending()
