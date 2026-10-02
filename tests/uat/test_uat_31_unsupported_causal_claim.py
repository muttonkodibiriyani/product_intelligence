"""UAT-31 · Unsupported causal claim (ANL-16, AIG-03)."""

from uat.registry import pending, scenario


@scenario("UAT-31", "m4", reqs=("ANL-16", "AIG-03"))
def test_uat_31_unsupported_causal_claim() -> None:
    """Unsupported causal claim.

    Check: asked for sales uplift from public prices only, the assistant names the missing
           inputs and invents nothing.
    """
    pending()
