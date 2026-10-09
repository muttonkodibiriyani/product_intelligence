from decimal import Decimal

import pytest

from pi_compare import Axis, MatrixState, ValueState, discount, normalise_size, normalise_text_axis
from pi_compare.presence import retailer_cell
from pi_dataset.models import MoneyValue
from pi_dataset.v3 import SizeV3


def size(value: str | None, unit: str | None, label: str | None = None) -> SizeV3:
    return SizeV3(value=value, unit=unit, label=label, system=None)


def test_volume_conversion_retains_raw_and_provenance() -> None:
    result = normalise_size(size("1", "fl. oz"))

    assert result.axis is Axis.VOLUME
    assert result.raw == {"value": "1", "unit": "fl. oz", "label": None, "system": None}
    assert result.canonical == "29.5735"
    assert result.canonical_unit == "ml"
    assert result.evidence.factor == "29.5735"
    assert result.evidence.rule_version == "pi_compare.axes/1"


@pytest.mark.parametrize(
    ("value", "unit", "axis", "canonical", "target"),
    [
        ("50", "ml", Axis.VOLUME, "50", "ml"),
        ("2", "cl", Axis.VOLUME, "20", "ml"),
        ("0.5", "l", Axis.VOLUME, "500", "ml"),
        ("1", "oz", Axis.SIZE, "28.3495", "g"),
        ("1000", "mg", Axis.SIZE, "1", "g"),
        ("2", "pcs", Axis.PACK, "2", "count"),
    ],
)
def test_supported_size_ladders(
    value: str, unit: str, axis: Axis, canonical: str, target: str
) -> None:
    result = normalise_size(size(value, unit))
    assert (result.axis, result.canonical, result.canonical_unit) == (axis, canonical, target)
    assert result.state is ValueState.OBSERVED


def test_label_size_and_unsupported_unit_stay_distinct() -> None:
    label = SizeV3(value=None, unit=None, label="Medium", system="alpha")
    assert normalise_size(label).canonical == "medium:alpha"

    unsupported = normalise_size(size("5", "sachets"))
    assert unsupported.raw == {
        "value": "5",
        "unit": "sachets",
        "label": None,
        "system": None,
    }
    assert unsupported.state is ValueState.UNKNOWN
    assert unsupported.canonical is None
    assert unsupported.reason == "unsupported_unit:sachets"


def test_missing_size_is_not_observed() -> None:
    result = normalise_size(None)
    assert result.state is ValueState.NOT_OBSERVED
    assert result.raw is None


def test_shade_fold_is_a_key_not_a_replacement() -> None:
    result = normalise_text_axis("  Rosé Glow  ", Axis.SHADE, field="variant.shade")
    assert result.raw == "  Rosé Glow  "
    assert result.canonical == "rose glow"


def test_missing_text_axis_is_unknown_and_other_axes_are_refused() -> None:
    result = normalise_text_axis(None, Axis.COLOR, field="attributes.color")
    assert result.state is ValueState.UNKNOWN
    assert result.reason == "not_published"
    with pytest.raises(ValueError, match="only valid for shade or color"):
        normalise_text_axis("10", Axis.PACK, field="size")


def test_discount_uses_decimal_and_currency() -> None:
    result = discount(
        MoneyValue.of(Decimal("75.00"), "AED"), MoneyValue.of(Decimal("100.00"), "AED")
    )
    assert result.state is ValueState.OBSERVED
    assert result.value is not None
    assert result.value.amount == MoneyValue.of(Decimal("25.00"), "AED")
    assert result.value.percent == "25.0000"


def test_discount_never_invents_missing_or_inconsistent_values() -> None:
    aed = MoneyValue.of(Decimal("10.00"), "AED")
    usd = MoneyValue.of(Decimal("10.00"), "USD")
    assert discount(aed, None).reason == "regular_price_unknown"
    assert discount(aed, usd).reason == "currency_mismatch"
    assert discount(MoneyValue.of(Decimal("11.00"), "AED"), aed).reason == "current_above_regular"


@pytest.mark.parametrize(
    ("accepted", "ambiguous", "complete", "expected"),
    [
        (("a",), ("p",), False, MatrixState.PRESENT),
        ((), ("p",), True, MatrixState.AMBIGUOUS),
        ((), (), True, MatrixState.ABSENT),
        ((), (), False, MatrixState.NOT_OBSERVED),
    ],
)
def test_retailer_matrix_needs_explicit_complete_capture(
    accepted: tuple[str, ...],
    ambiguous: tuple[str, ...],
    complete: bool,
    expected: MatrixState,
) -> None:
    cell = retailer_cell(
        retailer="ulta_ae",
        as_of=__import__("datetime").date(2026, 10, 9),
        generation="g1",
        accepted_tokens=accepted,
        ambiguous_tokens=ambiguous,
        complete_capture=complete,
        completeness_basis="saved_capture",
    )
    assert cell.state is expected
    if expected is MatrixState.PRESENT:
        assert cell.ambiguous_tokens == ()
