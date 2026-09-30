"""UAT-19 · Locked match (MAT-05, MAT-07)."""

from uat.registry import pending, scenario


@scenario("UAT-19", "m2", reqs=("MAT-05", "MAT-07"))
def test_uat_19_locked_match() -> None:
    """Locked match.

    Check: after a matching-model deploy a locked pair survives and a rejected pair is not
           recreated.
    """
    pending()
