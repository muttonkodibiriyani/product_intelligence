"""The reviewed 154-slot Product Detail attribute contract.

Definitions come from the frozen requirements-v2 registry and the committed beauty profile.
The projection code below never invents a value for a missing slot and never substitutes one
retailer's observation for another retailer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cache
from typing import Annotated, Any, Literal

from pydantic import Field, JsonValue, ValidationError, model_validator

from pi_capture.registry import ATTRIBUTES, BaseType, type_spec
from pi_dataset import ContractModel, MoneyValue
from pi_dataset.profiles import AttributeDef as ProfileAttributeDef
from pi_dataset.profiles import AttributeType as ProfileAttributeType
from pi_dataset.profiles import committed_profile

ATTRIBUTE_MANIFEST_VERSION: Literal["requirements-v2+beauty2+variant-relationships@1"] = (
    "requirements-v2+beauty2+variant-relationships@1"
)


class AttributeTargetLevel(StrEnum):
    MASTER = "master"
    PRODUCT = "product"
    OFFER = "offer"
    VARIANT = "variant"


class AttributeKind(StrEnum):
    TEXT = "text"
    ENUM = "enum"
    INTEGER = "integer"
    DECIMAL = "decimal"
    MONEY = "money"
    BOOLEAN = "boolean"
    LIST = "list"
    OBJECT = "object"


class AttributeState(StrEnum):
    OBSERVED = "observed"
    NOT_PUBLISHED = "not_published"
    NOT_OBSERVED = "not_observed"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    INVALID = "invalid"
    NOT_APPLICABLE = "not_applicable"


class AttributeLabel(ContractModel):
    en: str
    #: Null when the reviewed source has no Arabic field-name translation. The Arabic UI falls
    #: back to the stable key rather than fabricating a translation.
    ar: str | None = None


class AttributeDefinition(ContractModel):
    key: str
    group: str
    level: AttributeTargetLevel
    kind: AttributeKind
    declared_type: str
    label: AttributeLabel
    #: A literal unit only when the contract fixes one; otherwise the value or sibling unit field
    #: carries it. No conversion is performed.
    unit: str | None = None
    #: Where a money value's ISO-4217 code comes from; null for non-money values.
    currency_from: str | None = None
    enum_values: tuple[str, ...] = ()


_LEVELS = {
    "style": AttributeTargetLevel.MASTER,
    "colour": AttributeTargetLevel.PRODUCT,
    "offer": AttributeTargetLevel.OFFER,
    "variant": AttributeTargetLevel.VARIANT,
}


def _label(key: str) -> AttributeLabel:
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", key).replace("_", " ").replace("..", "-")
    return AttributeLabel(en=words[:1].upper() + words[1:])


def _registry_kind(key: str, raw_type: str) -> tuple[AttributeKind, tuple[str, ...]]:
    parsed = type_spec(raw_type)
    if key.endswith("_minor"):
        return AttributeKind.MONEY, ()
    if parsed.is_array:
        return AttributeKind.LIST, parsed.enum_values
    kind = {
        BaseType.TEXT: AttributeKind.TEXT,
        BaseType.BOOL: AttributeKind.BOOLEAN,
        BaseType.INT: AttributeKind.INTEGER,
        BaseType.BIGINT: AttributeKind.INTEGER,
        BaseType.NUMERIC: AttributeKind.DECIMAL,
        BaseType.JSONB: AttributeKind.OBJECT,
        BaseType.ENUM: AttributeKind.ENUM,
        BaseType.DATE: AttributeKind.TEXT,
        BaseType.TIMESTAMPTZ: AttributeKind.TEXT,
        BaseType.UUID: AttributeKind.TEXT,
    }[parsed.base]
    return kind, parsed.enum_values


def _profile_kind(definition: ProfileAttributeDef) -> AttributeKind:
    return {
        ProfileAttributeType.TEXT: AttributeKind.TEXT,
        ProfileAttributeType.ENUM: AttributeKind.ENUM,
        ProfileAttributeType.DECIMAL: AttributeKind.DECIMAL,
        ProfileAttributeType.MONEY: AttributeKind.MONEY,
        ProfileAttributeType.BOOL: AttributeKind.BOOLEAN,
        ProfileAttributeType.TEXT_LIST: AttributeKind.LIST,
        ProfileAttributeType.OBJECT: AttributeKind.OBJECT,
    }[definition.type]


@cache
def attribute_manifest() -> tuple[AttributeDefinition, ...]:
    definitions = [
        AttributeDefinition(
            key=definition.key,
            group=definition.group.value,
            level=_LEVELS[definition.level.value],
            kind=(kind := _registry_kind(definition.key, definition.type))[0],
            declared_type=definition.type,
            label=_label(definition.key),
            currency_from="offer.currency" if kind[0] is AttributeKind.MONEY else None,
            enum_values=kind[1],
        )
        for definition in ATTRIBUTES
    ]
    profile = committed_profile("beauty", 2)
    if profile is None:  # pragma: no cover - the committed package contract is mandatory
        raise RuntimeError("missing committed beauty@2 profile")
    known = {definition.key for definition in definitions}
    for definition in profile.attribute_set:
        if definition.key in known:
            continue
        definitions.append(
            AttributeDefinition(
                key=definition.key,
                group=definition.block.value if definition.block is not None else "beauty",
                level=AttributeTargetLevel(definition.level.value),
                kind=_profile_kind(definition),
                declared_type=definition.type.value,
                label=AttributeLabel(
                    en=definition.label.get("en", definition.key),
                    ar=definition.label.get("ar"),
                ),
                currency_from=(
                    "attribute.currency" if definition.type is ProfileAttributeType.MONEY else None
                ),
                enum_values=tuple(value.id for value in definition.values or ()),
            )
        )
    definitions.append(
        AttributeDefinition(
            key="variant_relationships",
            group="identity",
            level=AttributeTargetLevel.VARIANT,
            kind=AttributeKind.OBJECT,
            declared_type="object",
            label=AttributeLabel(en="Variant relationships", ar="علاقات المتغيرات"),
        )
    )
    return tuple(definitions)


class AttributeManifest(ContractModel):
    version: Literal["requirements-v2+beauty2+variant-relationships@1"] = (
        ATTRIBUTE_MANIFEST_VERSION
    )
    definitions: tuple[AttributeDefinition, ...] = Field(min_length=154, max_length=154)


class TextAttributeValue(ContractModel):
    kind: Literal["text"] = "text"
    text: str


class EnumAttributeValue(ContractModel):
    kind: Literal["enum"] = "enum"
    code: str


class IntegerAttributeValue(ContractModel):
    kind: Literal["integer"] = "integer"
    value: int


class DecimalAttributeValue(ContractModel):
    kind: Literal["decimal"] = "decimal"
    amount: str
    unit: str | None = None


class MoneyAttributeValue(ContractModel):
    kind: Literal["money"] = "money"
    amount: str
    minor: int
    currency: str


class BooleanAttributeValue(ContractModel):
    kind: Literal["boolean"] = "boolean"
    value: bool


class ListAttributeValue(ContractModel):
    kind: Literal["list"] = "list"
    items: tuple[str, ...]


class ObjectAttributeValue(ContractModel):
    kind: Literal["object"] = "object"
    fields: dict[str, JsonValue]


AttributeValue = Annotated[
    TextAttributeValue
    | EnumAttributeValue
    | IntegerAttributeValue
    | DecimalAttributeValue
    | MoneyAttributeValue
    | BooleanAttributeValue
    | ListAttributeValue
    | ObjectAttributeValue,
    Field(discriminator="kind"),
]


class AttributeFieldEvidence(ContractModel):
    """Sanitized public evidence: no run id, auth material, storage path, or source URL."""

    source: str = Field(min_length=1, max_length=40)
    field: str = Field(min_length=1, max_length=160)
    excerpt: str | None = Field(default=None, max_length=120)
    captured_at: datetime | None = None
    context: str | None = Field(default=None, max_length=63)
    retailer: str | None = Field(default=None, max_length=63)


class AttributeTarget(ContractModel):
    id: str = Field(min_length=1, max_length=300)
    level: AttributeTargetLevel
    label: str = Field(min_length=1, max_length=200)
    context: str | None = Field(default=None, max_length=63)
    retailer: str | None = Field(default=None, max_length=63)


class AttributeAlternative(ContractModel):
    value: AttributeValue
    evidence: tuple[AttributeFieldEvidence, ...] = Field(min_length=1)


class AttributeSlot(ContractModel):
    target_id: str
    definition: AttributeDefinition
    state: AttributeState
    value: AttributeValue | None = None
    evidence: tuple[AttributeFieldEvidence, ...] = ()
    alternatives: tuple[AttributeAlternative, ...] = ()
    reason: AttributeLabel | None = None
    raw_value: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _state_shape(self) -> AttributeSlot:
        if self.state is AttributeState.OBSERVED:
            valid = self.value is not None and bool(self.evidence)
        elif self.state is AttributeState.CONFLICT:
            valid = len(self.alternatives) >= 2
        elif self.state is AttributeState.INVALID:
            valid = self.raw_value is not None and self.reason is not None and bool(self.evidence)
        else:
            valid = self.reason is not None
        if not valid:
            raise ValueError(f"attribute slot has invalid shape for state {self.state}")
        if self.state is not AttributeState.OBSERVED and self.value is not None:
            raise ValueError(f"attribute slot {self.state} cannot carry value")
        if self.state is not AttributeState.CONFLICT and self.alternatives:
            raise ValueError(f"attribute slot {self.state} cannot carry alternatives")
        if self.state is not AttributeState.INVALID and self.raw_value is not None:
            raise ValueError(f"attribute slot {self.state} cannot carry rawValue")
        return self


@dataclass(frozen=True, slots=True)
class AttributeFact:
    key: str
    raw: Any
    evidence: tuple[AttributeFieldEvidence, ...]


class UnknownAttributeError(ValueError):
    """A fact names no reviewed definition; projection fails rather than dropping it."""


class AttributeProjectionError(ValueError):
    """A reviewed fact is structurally inconsistent with its declared target or type."""


_REASONS = {
    AttributeState.NOT_PUBLISHED: AttributeLabel(
        en="The field was covered and this source published no value.",
        ar="تمت تغطية الحقل ولم ينشر المصدر قيمة.",
    ),
    AttributeState.NOT_OBSERVED: AttributeLabel(
        en="The source was not observed for this field.",
        ar="لم يتم رصد المصدر لهذا الحقل.",
    ),
    AttributeState.UNKNOWN: AttributeLabel(
        en="The evidence cannot classify this missing value.",
        ar="لا يمكن للأدلة تصنيف هذه القيمة المفقودة.",
    ),
    AttributeState.NOT_APPLICABLE: AttributeLabel(
        en="This field belongs to another entity level.",
        ar="ينتمي هذا الحقل إلى مستوى كيان آخر.",
    ),
}


def _typed_value(  # noqa: PLR0912 - exhaustive declared-type decoder
    definition: AttributeDefinition, raw: Any
) -> tuple[AttributeValue | None, str | None]:
    try:
        match definition.kind:
            case AttributeKind.TEXT:
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError("expected non-empty text")
                value: AttributeValue = TextAttributeValue(text=raw)
            case AttributeKind.ENUM:
                if not isinstance(raw, str) or (
                    definition.enum_values and raw not in definition.enum_values
                ):
                    raise ValueError("expected a declared enum code")
                value = EnumAttributeValue(code=raw)
            case AttributeKind.INTEGER:
                if not isinstance(raw, int) or isinstance(raw, bool):
                    raise ValueError("expected an integer")
                value = IntegerAttributeValue(value=raw)
            case AttributeKind.DECIMAL:
                if not isinstance(raw, str) or re.fullmatch(r"^-?\d+(\.\d+)?$", raw) is None:
                    raise ValueError("expected an exact decimal string")
                value = DecimalAttributeValue(amount=raw, unit=definition.unit)
            case AttributeKind.MONEY:
                money = MoneyValue.model_validate(raw, strict=True)
                value = MoneyAttributeValue(
                    amount=money.amount, minor=money.minor, currency=money.currency
                )
            case AttributeKind.BOOLEAN:
                if not isinstance(raw, bool):
                    raise ValueError("expected a boolean")
                value = BooleanAttributeValue(value=raw)
            case AttributeKind.LIST:
                if not isinstance(raw, list) or not all(
                    isinstance(item, str) and item.strip() for item in raw
                ):
                    raise ValueError("expected a list of non-empty text values")
                value = ListAttributeValue(items=tuple(raw))
            case AttributeKind.OBJECT:
                if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
                    raise ValueError("expected an object")
                value = ObjectAttributeValue(fields=raw)
        return value, None
    except (ValueError, ValidationError) as exc:
        return None, str(exc).splitlines()[0][:120]


def _raw_text(raw: Any) -> str:
    try:
        rendered = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        rendered = repr(raw)
    return rendered[:120]


def project_target(  # noqa: PLR0912 - explicit evidence-state precedence
    target: AttributeTarget,
    facts: tuple[AttributeFact, ...],
    missing: dict[str, AttributeState] | None = None,
) -> tuple[AttributeSlot, ...]:
    """Project exactly one slot per definition, preserving all evidence states.

    ``missing`` may classify only reviewed, applicable keys as ``not_published`` or
    ``not_observed``. An omitted key is ``unknown``. Facts win over missing classifications;
    invalid beats conflict, which beats observed.
    """

    definitions = attribute_manifest()
    by_key = {definition.key: definition for definition in definitions}
    grouped: dict[str, list[AttributeFact]] = {}
    for fact in facts:
        definition = by_key.get(fact.key)
        if definition is None:
            raise UnknownAttributeError(fact.key)
        if definition.level is not target.level:
            raise AttributeProjectionError(
                f"{fact.key} belongs to {definition.level}, not {target.level}"
            )
        if not fact.evidence:
            raise AttributeProjectionError(f"{fact.key} has no field evidence")
        grouped.setdefault(fact.key, []).append(fact)

    missing = {} if missing is None else missing
    allowed_missing = {AttributeState.NOT_PUBLISHED, AttributeState.NOT_OBSERVED}
    for key, state in missing.items():
        definition = by_key.get(key)
        if definition is None:
            raise UnknownAttributeError(key)
        if definition.level is not target.level or state not in allowed_missing:
            raise AttributeProjectionError(f"invalid missing classification for {key}")

    slots: list[AttributeSlot] = []
    for definition in definitions:
        if definition.level is not target.level:
            slots.append(
                AttributeSlot(
                    target_id=target.id,
                    definition=definition,
                    state=AttributeState.NOT_APPLICABLE,
                    reason=_REASONS[AttributeState.NOT_APPLICABLE],
                )
            )
            continue
        candidates = grouped.get(definition.key, [])
        typed = [(fact, *_typed_value(definition, fact.raw)) for fact in candidates]
        invalid = next(((fact, error) for fact, _, error in typed if error is not None), None)
        if invalid is not None:
            fact, error = invalid
            slots.append(
                AttributeSlot(
                    target_id=target.id,
                    definition=definition,
                    state=AttributeState.INVALID,
                    evidence=fact.evidence,
                    reason=AttributeLabel(
                        en=f"Value violates the declared type: {error}",
                        ar="تخالف القيمة النوع المعلن.",
                    ),
                    raw_value=_raw_text(fact.raw),
                )
            )
            continue
        unique: dict[str, tuple[AttributeValue, list[AttributeFieldEvidence]]] = {}
        for fact, value, _ in typed:
            if value is None:  # pragma: no cover - invalid values returned above
                raise RuntimeError("typed value vanished")
            fingerprint = value.model_dump_json(by_alias=True)
            if fingerprint not in unique:
                unique[fingerprint] = (value, [])
            unique[fingerprint][1].extend(fact.evidence)
        if len(unique) > 1:
            slots.append(
                AttributeSlot(
                    target_id=target.id,
                    definition=definition,
                    state=AttributeState.CONFLICT,
                    alternatives=tuple(
                        AttributeAlternative(value=value, evidence=tuple(evidence))
                        for value, evidence in unique.values()
                    ),
                    reason=AttributeLabel(
                        en="Conflicting observed values; no winner was selected.",
                        ar="قيم مرصودة متعارضة؛ لم يتم اختيار قيمة فائزة.",
                    ),
                )
            )
            continue
        if unique:
            value, evidence = next(iter(unique.values()))
            slots.append(
                AttributeSlot(
                    target_id=target.id,
                    definition=definition,
                    state=AttributeState.OBSERVED,
                    value=value,
                    evidence=tuple(evidence),
                )
            )
            continue
        state = missing.get(definition.key, AttributeState.UNKNOWN)
        slots.append(
            AttributeSlot(
                target_id=target.id,
                definition=definition,
                state=state,
                reason=_REASONS[state],
            )
        )
    return tuple(slots)
