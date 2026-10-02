"""Vertical profile declarations on the wire (ADR-0008 §1, §3): attribute sets and size flags.

A ``ProfileDeclaration`` is data, committed as ``contracts/profiles/<name>@<version>.json`` in
this package, so ``pi_dataset`` never imports the ``VerticalProfile`` code (PR-E). From step 2 a
PR-E test pins each profile's export to its committed file.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache
from importlib import resources
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from pi_core.types import NonEmptyStr
from pi_dataset.models import ContractModel, LocalizedText, SourceKey

#: An attribute key: a ``SourceKey`` shape, plus lowerCamel for the keys v2 already publishes
#: (``shadeFamilies``), so ``upgrade`` keeps every v2 key as it is.
AttributeKey = Annotated[str, StringConstraints(pattern=r"^[a-z][A-Za-z0-9_]{1,62}$")]


class AttributeLevel(StrEnum):
    PRODUCT = "product"
    OFFER = "offer"


class AttributeType(StrEnum):
    TEXT = "text"
    ENUM = "enum"
    DECIMAL = "decimal"
    MONEY = "money"
    BOOL = "bool"
    TEXT_LIST = "text_list"
    OBJECT = "object"


class AttributeBlock(StrEnum):
    """Where the product page shows a key; a client renders an unknown block as key/value."""

    SUMMARY = "summary"
    SIZE_RUN = "size_run"
    SWATCHES = "swatches"
    NUTRITION = "nutrition"
    COMBO = "combo"
    FEES = "fees"
    CHANNEL = "channel"


class EnumValue(ContractModel):
    id: NonEmptyStr
    label: LocalizedText


class AttributeDef(ContractModel):
    key: AttributeKey
    level: AttributeLevel
    type: AttributeType
    #: The closed value list: set exactly when ``type`` is ``enum``.
    values: Annotated[tuple[EnumValue, ...], Field(min_length=1)] | None
    label: LocalizedText
    #: Usable as a filter (``attr=<key>:<value>``) and a facet count.
    facet: bool
    block: AttributeBlock | None
    #: Collected in this snapshot. ``false``: explicitly not collected, and the key never appears.
    capability: bool

    @model_validator(mode="after")
    def _check_values(self) -> Self:
        if (self.type is AttributeType.ENUM) != (self.values is not None):
            msg = f"attribute {self.key}: values are required exactly for type enum"
            raise ValueError(msg)
        ids = [v.id for v in self.values or ()]
        if len(ids) != len(set(ids)):
            msg = f"attribute {self.key}: duplicate enum value ids"
            raise ValueError(msg)
        return self


class ProfileInfo(ContractModel):
    """``meta.profile``: which profile version is in force, and its size rules (ADR-0008 §1)."""

    name: SourceKey
    version: Annotated[int, Field(ge=1)]
    #: Label-only sizes of the same item compare equal on the same folded label and system.
    size_labels_comparable: bool
    #: Every size label names its system (``alpha``, ``eu``, ...).
    size_system_required: bool


class ProfileDeclaration(ProfileInfo):
    """A profile version as committed: ``meta.profile`` plus its ``meta.attributeSet``."""

    attribute_set: tuple[AttributeDef, ...]

    @model_validator(mode="after")
    def _check_keys(self) -> Self:
        keys = [a.key for a in self.attribute_set]
        if len(keys) != len(set(keys)):
            msg = f"profile {self.name}@{self.version}: duplicate attribute keys"
            raise ValueError(msg)
        return self

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def info(self) -> ProfileInfo:
        return ProfileInfo(
            name=self.name,
            version=self.version,
            size_labels_comparable=self.size_labels_comparable,
            size_system_required=self.size_system_required,
        )


def _profiles_dir() -> resources.abc.Traversable:
    return resources.files("pi_dataset").joinpath("contracts", "profiles")


def committed_profiles() -> tuple[str, ...]:
    """Every committed ``<name>@<version>``, sorted."""
    return tuple(
        sorted(
            p.name.removesuffix(".json")
            for p in _profiles_dir().iterdir()
            if p.name.endswith(".json")
        )
    )


@cache
def committed_profile(name: str, version: int) -> ProfileDeclaration | None:
    """The committed declaration of ``name@version``, or ``None`` when there is none."""
    path = _profiles_dir().joinpath(f"{name}@{version}.json")
    if not path.is_file():
        return None
    return ProfileDeclaration.model_validate_json(path.read_text(encoding="utf-8"), strict=True)
