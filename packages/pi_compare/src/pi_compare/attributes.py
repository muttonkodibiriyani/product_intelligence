"""Profile-driven attribute validation with explicit missing and conflict states."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import cast

from pydantic import JsonValue, ValidationError

from pi_compare.models import (
    AttributeCell,
    AttributeIssue,
    AttributeObservation,
    AttributeReport,
    AttributeSpec,
    ValueState,
)
from pi_dataset.models import MoneyValue
from pi_dataset.profiles import AttributeType


def validate_attribute(
    spec: AttributeSpec,
    observations: Sequence[AttributeObservation],
    *,
    captured: bool,
) -> AttributeCell:
    """Validate every observation of one declared key; no observation is ever invented."""
    definition = spec.definition
    if not observations:
        state = (
            ValueState.UNKNOWN if definition.capability and captured else ValueState.NOT_OBSERVED
        )
        return AttributeCell(
            key=definition.key,
            definition=definition,
            state=state,
            raw=(),
            canonical=(),
            evidence=(),
        )

    raw = tuple(o.raw for o in observations)
    evidence = tuple(o.evidence for o in observations)
    canonical: list[JsonValue] = []
    errors: list[str] = []
    for observation in observations:
        try:
            canonical.append(_canonical(spec, observation.raw))
        except ValueError as exc:
            errors.append(str(exc))
        if observation.evidence.source == "model" and observation.evidence.model_name is None:
            errors.append("model_evidence_missing_identity_or_confidence")
    if errors:
        return AttributeCell(
            key=definition.key,
            definition=definition,
            state=ValueState.INVALID,
            raw=raw,
            canonical=tuple(canonical),
            evidence=evidence,
            errors=tuple(sorted(set(errors))),
        )
    unique = {_stable(value) for value in canonical}
    state = ValueState.OBSERVED if len(unique) == 1 else ValueState.CONFLICT
    return AttributeCell(
        key=definition.key,
        definition=definition,
        state=state,
        raw=raw,
        canonical=tuple(canonical),
        evidence=evidence,
        errors=() if state is ValueState.OBSERVED else ("incompatible_observed_values",),
    )


def validate_attributes(
    specs: Sequence[AttributeSpec],
    observations: Mapping[str, Sequence[AttributeObservation]],
    *,
    captured: frozenset[str],
) -> AttributeReport:
    """One cell per definition, including all missing states, plus undeclared-key issues."""
    keys = [s.definition.key for s in specs]
    if len(keys) != len(set(keys)):
        msg = "attribute specs repeat a key"
        raise ValueError(msg)
    cells = tuple(
        validate_attribute(
            spec,
            observations.get(spec.definition.key, ()),
            captured=spec.definition.key in captured,
        )
        for spec in specs
    )
    declared = set(keys)
    issues = tuple(
        AttributeIssue(key=key, code="undeclared_attribute")
        for key in sorted(set(observations) - declared)
    )
    counts = Counter(cell.state for cell in cells)
    observed = counts[ValueState.OBSERVED]
    completeness = Decimal(observed) / Decimal(len(cells)) if cells else Decimal(1)
    return AttributeReport(
        cells=cells,
        completeness=format(completeness.quantize(Decimal("0.000001")), "f"),
        counts={state: counts[state] for state in ValueState},
        issues=issues,
    )


def _canonical(spec: AttributeSpec, raw: JsonValue) -> JsonValue:  # noqa: PLR0911, PLR0912
    kind = spec.definition.type
    allowed = {v.id for v in spec.definition.values or ()}
    if kind is AttributeType.TEXT:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("not_nonempty_text")
        return raw.strip()
    if kind is AttributeType.ENUM:
        if not isinstance(raw, str) or raw not in allowed:
            raise ValueError("not_allowed_enum")
        return raw
    if kind is AttributeType.DECIMAL:
        if not isinstance(raw, str):
            raise ValueError("decimal_not_string")
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("invalid_decimal") from exc
        if not value.is_finite():
            raise ValueError("nonfinite_decimal")
        return format(value, "f")
    if kind is AttributeType.MONEY:
        if not isinstance(raw, dict):
            raise ValueError("money_not_object")
        try:
            money = MoneyValue.model_validate(raw, strict=True)
        except ValidationError as exc:
            raise ValueError("invalid_money") from exc
        if spec.allowed_currencies and money.currency not in spec.allowed_currencies:
            raise ValueError("currency_not_allowed")
        return cast(JsonValue, money.model_dump(mode="json", by_alias=True))
    if kind is AttributeType.BOOL:
        if not isinstance(raw, bool):
            raise ValueError("not_boolean")
        return raw
    if kind is AttributeType.TEXT_LIST:
        if (
            not isinstance(raw, list)
            or not raw
            or not all(isinstance(v, str) and v.strip() for v in raw)
        ):
            raise ValueError("not_nonempty_text_list")
        values = cast(list[str], raw)
        if allowed and any(value not in allowed for value in values):
            raise ValueError("list_value_not_allowed")
        return cast(JsonValue, [value.strip() for value in values])
    if kind is AttributeType.OBJECT:
        if not isinstance(raw, dict):
            raise ValueError("not_object")
        if spec.allowed_units:
            unit = raw.get("unit")
            if not isinstance(unit, str) or unit not in spec.allowed_units:
                raise ValueError("unit_not_allowed")
        return raw
    raise AssertionError(f"unhandled attribute type {kind}")


def _stable(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
