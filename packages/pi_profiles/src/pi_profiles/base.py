"""The ``VerticalProfile`` plugin shape (ADR-0007 §4, ADR-0008 §3).

A profile is a versioned pydantic **attribute model** plus its size rules. The model is the one
source for three things:

- the snapshot's ``meta.attributeSet`` and ``meta.profile`` (``declaration()``), which a test
  pins to the committed ``pi_dataset`` declaration so code and contract can't drift;
- the write path for ``variant.attributes`` (``validate_attributes()``), stored next to
  ``variant.attributes_schema = profile.ref``;
- typed reads, later: the per-vertical SQL views project the same keys.

Normalisers, match rules, the taxonomy root and UI modules join the profile in later steps.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ConfigDict, JsonValue

from pi_core.base import PiModel
from pi_dataset import (
    AttributeBlock,
    AttributeDef,
    AttributeLevel,
    AttributeType,
    EnumValue,
    ProfileDeclaration,
)


@dataclass(frozen=True, slots=True)
class Attr:
    """How one attribute-model field is declared: ``Annotated[T, Attr(...)]``.

    The wire key is the field's alias, else its name. ``values`` lists ``(id, label)`` pairs and
    is set exactly for ``enum``.
    """

    type: AttributeType
    label: Mapping[str, str]
    level: AttributeLevel = AttributeLevel.PRODUCT
    facet: bool = False
    block: AttributeBlock | None = None
    capability: bool = True
    values: tuple[tuple[str, Mapping[str, str]], ...] | None = None


class AttributeModel(PiModel):
    """Base of every profile attribute model: frozen, strict, unknown keys rejected.

    Validate through ``VerticalProfile.validate_attributes``. Calling the model directly with a
    field's Python name (``shade_families`` for ``shadeFamilies``) is not an error in pydantic:
    the key is dropped silently. The write path refuses it before parsing.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        validate_default=True,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
    )


@dataclass(frozen=True, slots=True)
class VerticalProfile:
    """One version of one vertical, registered as ``<name>@<version>``."""

    name: str
    version: int
    attributes: type[AttributeModel]
    #: Label-only sizes of the same item compare equal on the same folded label and system.
    size_labels_comparable: bool
    #: Every size label names its system (``alpha``, ``eu``, ...).
    size_system_required: bool

    @property
    def ref(self) -> str:
        """``<name>@<version>``: the ``meta.profile`` ref and the ``attributes_schema`` value."""
        return f"{self.name}@{self.version}"

    def declaration(self) -> ProfileDeclaration:
        """``meta.profile`` + ``meta.attributeSet``, in the attribute model's field order."""
        defs = []
        for name, field in self.attributes.model_fields.items():
            attr = next((m for m in field.metadata if isinstance(m, Attr)), None)
            if attr is None:
                msg = f"{self.attributes.__name__}.{name} has no Attr declaration"
                raise TypeError(msg)
            values = None
            if attr.values is not None:
                values = tuple(EnumValue(id=i, label=dict(label)) for i, label in attr.values)
            defs.append(
                AttributeDef(
                    key=field.alias or name,
                    level=attr.level,
                    type=attr.type,
                    values=values,
                    label=dict(attr.label),
                    facet=attr.facet,
                    block=attr.block,
                    capability=attr.capability,
                )
            )
        return ProfileDeclaration(
            name=self.name,
            version=self.version,
            size_labels_comparable=self.size_labels_comparable,
            size_system_required=self.size_system_required,
            attribute_set=tuple(defs),
        )

    def validate_attributes(self, raw: Mapping[str, Any]) -> dict[str, JsonValue]:
        """The write path for ``variant.attributes``: strict check, then the canonical jsonb.

        Raises ``ValueError`` on a key that isn't a declared wire key, and
        ``pydantic.ValidationError`` (also a ``ValueError``) on a wrong type; nothing is coerced.
        Unset and default values are dropped, so ``{}`` means "none".
        """
        keys = {field.alias or name for name, field in self.attributes.model_fields.items()}
        unknown = sorted(set(raw) - keys)
        if unknown:
            msg = f"{self.ref}: undeclared attribute keys {unknown}"
            raise ValueError(msg)
        try:
            payload = json.dumps(dict(raw), allow_nan=False)
        except (TypeError, ValueError) as exc:  # Decimal, datetime, NaN...: not JSON values
            msg = f"{self.ref}: attributes are not plain JSON values ({exc})"
            raise ValueError(msg) from exc
        model = self.attributes.model_validate_json(payload, strict=True)
        dumped: dict[str, JsonValue] = model.model_dump(mode="json", exclude_defaults=True)
        return dumped
