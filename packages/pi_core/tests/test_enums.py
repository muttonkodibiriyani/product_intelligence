import pytest

from pi_core import AvailabilityState, LadderRung, PriceType


def test_only_real_stock_observations_are_known() -> None:
    # KPI-15: out-of-stock rate excludes unknown, blocked and not-observed states.
    known = {s for s in AvailabilityState if s.is_known}
    assert known == {
        AvailabilityState.IN_STOCK,
        AvailabilityState.LOW_STOCK,
        AvailabilityState.OUT_OF_STOCK,
    }
    assert not AvailabilityState.BLOCKED.is_known


@pytest.mark.parametrize(
    ("price_type", "rankable"),
    [
        (PriceType.FULL, True),
        (PriceType.PROMOTIONAL, True),
        (PriceType.INSTALLMENT, False),  # UAT-04
        (PriceType.RANGE, False),
        (PriceType.MEMBER, False),
    ],
)
def test_rankable_price_types(price_type: PriceType, rankable: bool) -> None:
    assert price_type.rankable is rankable


def test_only_proxy_rung_is_paid() -> None:
    assert [r for r in LadderRung if r.is_paid] == [LadderRung.PAID_PROXY]
    assert list(LadderRung) == sorted(LadderRung)


def test_enum_values_are_stable() -> None:
    # Persisted values: renaming them requires a migration.
    assert AvailabilityState.NOT_OBSERVED.value == "not_observed"
    assert int(LadderRung.SITE_DATA) == 0
