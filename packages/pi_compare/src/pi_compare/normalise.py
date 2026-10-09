"""Lossless, deterministic variant-axis and commercial normalisation."""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

from pydantic import JsonValue

from pi_compare.models import (
    Axis,
    AxisEvidence,
    AxisValue,
    Discount,
    DiscountResult,
    NormalisationMethod,
    ValueState,
)
from pi_dataset.models import MoneyValue
from pi_dataset.v3 import SizeV3

RULE_VERSION = "pi_compare.axes/1"
_VOLUME = {
    "ml": (Decimal("1"), "ml"),
    "milliliter": (Decimal("1"), "ml"),
    "millilitre": (Decimal("1"), "ml"),
    "cl": (Decimal("10"), "ml"),
    "l": (Decimal("1000"), "ml"),
    "fl oz": (Decimal("29.5735"), "ml"),
    "floz": (Decimal("29.5735"), "ml"),
}
_MASS = {
    "mg": (Decimal("0.001"), "g"),
    "g": (Decimal("1"), "g"),
    "gr": (Decimal("1"), "g"),
    "kg": (Decimal("1000"), "g"),
    "oz": (Decimal("28.3495"), "g"),
}
_PACK = frozenset({"pc", "pcs", "piece", "pieces", "count", "ct"})


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def normalise_size(size: SizeV3 | None, *, field: str = "size") -> AxisValue:
    """A published size as a comparable axis while retaining its exact raw object."""
    if size is None:
        return AxisValue(
            axis=Axis.SIZE,
            raw=None,
            canonical=None,
            canonical_unit=None,
            state=ValueState.NOT_OBSERVED,
            evidence=AxisEvidence(field=field, method=NormalisationMethod.NONE),
            reason="not_observed",
        )
    raw = size.model_dump(mode="json", by_alias=True)
    if size.value is None:
        label = size.label
        if label is None:  # pragma: no cover - SizeV3 validates this invariant
            raise ValueError("a label-only size needs a label")
        canonical = fold_text(label)
        suffix = f":{size.system.casefold()}" if size.system else ""
        return AxisValue(
            axis=Axis.SIZE,
            raw=raw,
            canonical=f"{canonical}{suffix}",
            canonical_unit=None,
            state=ValueState.OBSERVED,
            evidence=AxisEvidence(field=field, method=NormalisationMethod.PAGE),
        )
    declared_unit = size.unit
    if declared_unit is None:  # pragma: no cover - SizeV3 validates this invariant
        raise ValueError("a measured size needs a unit")
    unit = " ".join(declared_unit.casefold().replace(".", "").split())
    value = Decimal(size.value)
    if unit in _VOLUME:
        factor, target = _VOLUME[unit]
        return _converted(Axis.VOLUME, raw, value, unit, factor, target, field)
    if unit in _MASS:
        factor, target = _MASS[unit]
        return _converted(Axis.SIZE, raw, value, unit, factor, target, field)
    if unit in _PACK:
        return AxisValue(
            axis=Axis.PACK,
            raw=raw,
            canonical=_decimal_text(value),
            canonical_unit="count",
            state=ValueState.OBSERVED,
            evidence=AxisEvidence(field=field, method=NormalisationMethod.DECLARED_UNIT),
        )
    return AxisValue(
        axis=Axis.SIZE,
        raw=raw,
        canonical=None,
        canonical_unit=None,
        state=ValueState.UNKNOWN,
        evidence=AxisEvidence(field=field, method=NormalisationMethod.NONE),
        reason=f"unsupported_unit:{unit}",
    )


def _converted(  # noqa: PLR0913, PLR0917 - one closed conversion record
    axis: Axis,
    raw: JsonValue,
    value: Decimal,
    unit: str,
    factor: Decimal,
    target: str,
    field: str,
) -> AxisValue:
    method = (
        NormalisationMethod.DECLARED_UNIT
        if factor == 1 and unit == target
        else NormalisationMethod.DETERMINISTIC_CONVERSION
    )
    return AxisValue(
        axis=axis,
        raw=raw,
        canonical=_decimal_text(value * factor),
        canonical_unit=target,
        state=ValueState.OBSERVED,
        evidence=AxisEvidence(
            field=field,
            method=method,
            rule_version=RULE_VERSION
            if method is NormalisationMethod.DETERMINISTIC_CONVERSION
            else None,
            factor=_decimal_text(factor)
            if method is NormalisationMethod.DETERMINISTIC_CONVERSION
            else None,
        ),
    )


def fold_text(value: str) -> str:
    """A display alignment key; the raw retailer text remains beside it."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.findall(r"[\w]+", plain))


def normalise_text_axis(value: str | None, axis: Axis, *, field: str) -> AxisValue:
    if axis not in {Axis.SHADE, Axis.COLOR}:
        msg = f"text normalisation is only valid for shade or color, got {axis}"
        raise ValueError(msg)
    if value is None or not value.strip():
        return AxisValue(
            axis=axis,
            raw=value,
            canonical=None,
            canonical_unit=None,
            state=ValueState.UNKNOWN,
            evidence=AxisEvidence(field=field, method=NormalisationMethod.NONE),
            reason="not_published",
        )
    return AxisValue(
        axis=axis,
        raw=value,
        canonical=fold_text(value),
        canonical_unit=None,
        state=ValueState.OBSERVED,
        evidence=AxisEvidence(field=field, method=NormalisationMethod.PAGE),
    )


def discount(current: MoneyValue | None, regular: MoneyValue | None) -> DiscountResult:
    """Exact public discount arithmetic; missing or inconsistent inputs never become zero."""
    if current is None or regular is None:
        missing = "current" if current is None else "regular"
        return DiscountResult(
            state=ValueState.UNKNOWN, value=None, reason=f"{missing}_price_unknown"
        )
    if current.currency != regular.currency:
        return DiscountResult(state=ValueState.CONFLICT, value=None, reason="currency_mismatch")
    now, was = current.decimal(), regular.decimal()
    if now > was:
        return DiscountResult(state=ValueState.CONFLICT, value=None, reason="current_above_regular")
    amount = MoneyValue.of(was - now, current.currency)
    percent = ((was - now) / was * Decimal(100)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return DiscountResult(
        state=ValueState.OBSERVED,
        value=Discount(amount=amount, percent=format(percent, "f")),
        reason=None,
    )
