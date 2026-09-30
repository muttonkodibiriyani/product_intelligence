"""UAT-12 · Fragrance concentration (CAT-03, MAT-02)."""

from uat.registry import pending, scenario


@scenario("UAT-12", "m2", reqs=("CAT-03", "MAT-02"))
def test_uat_12_fragrance_concentration() -> None:
    """Fragrance concentration.

    Check: same-name eau de parfum and eau de toilette are separate variants; exact matching
           rejects the concentration conflict.
    """
    pending()
