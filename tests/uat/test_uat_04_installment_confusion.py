"""UAT-04 · Installment confusion (PRC-01, PRC-13)."""

from uat.registry import pending, scenario


@scenario("UAT-04", "m1", reqs=("PRC-01", "PRC-13"))
def test_uat_04_installment_confusion() -> None:
    """Installment confusion.

    Check: full price 1200 with a monthly installment of 100 ranks on 1200; the installment
           appears only in a financing view.
    """
    pending()
