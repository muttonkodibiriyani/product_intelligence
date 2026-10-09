"""The attribute registry: lookups over the 145 requirement attributes and their type strings.

Storage rules (requirements v2, "attribute_storage"): every attribute must exist here before a
value can be written against it, the registry fixes the level an attribute belongs to, and
enumerated attributes list their allowed values. ``_attributes.py`` holds the generated data;
this module adds the lookups and parses the spec's type strings (``"enum matte|satin"``,
``"text(14)"``, ``"bigint null"``, ``"text[]"``, ``"int 1-20"``) into a ``TypeSpec``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Literal

from pi_capture._attributes import (
    ATTRIBUTES,
    Attribute,
    AttributeGroup,
    AttributeLevel,
    AttributeSource,
    Vertical,
)

__all__ = [
    "ATTRIBUTES",
    "PAGE_SOURCES",
    "Attribute",
    "AttributeGroup",
    "AttributeLevel",
    "AttributeSource",
    "BaseType",
    "TypeSpec",
    "UnknownAttributeError",
    "Vertical",
    "applicable",
    "by_key",
    "for_group",
    "for_level",
    "get",
    "page_sourced",
    "type_spec",
]

#: Sources that put the value on the retailer's page (what a capture can read).
PAGE_SOURCES: frozenset[AttributeSource] = frozenset(
    {
        AttributeSource.PAGE,
        AttributeSource.PAGE_OR_FEED,
        AttributeSource.PAGE_OR_DERIVED,
        AttributeSource.PAGE_MAPPED,
    }
)

VerticalName = Literal["beauty", "fashion", "food"]


class UnknownAttributeError(KeyError):
    """A key that is not in the registry: rejected, never stored (storage rule 1)."""


@cache
def by_key() -> Mapping[str, Attribute]:
    """Every attribute by key (keys are unique; the generator enforces it)."""
    return {a.key: a for a in ATTRIBUTES}


def get(key: str) -> Attribute:
    try:
        return by_key()[key]
    except KeyError:
        raise UnknownAttributeError(key) from None


def for_group(group: AttributeGroup | str) -> tuple[Attribute, ...]:
    wanted = AttributeGroup(group)
    return tuple(a for a in ATTRIBUTES if a.group is wanted)


def for_level(level: AttributeLevel | str) -> tuple[Attribute, ...]:
    wanted = AttributeLevel(level)
    return tuple(a for a in ATTRIBUTES if a.level is wanted)


def page_sourced() -> tuple[Attribute, ...]:
    """Attributes a page can show (source ``page``, ``page or feed``, ``page or derived``,
    ``page, mapped``). Derived and feed-only attributes are never read from a page."""
    return tuple(a for a in ATTRIBUTES if a.source in PAGE_SOURCES)


def applicable(vertical: Vertical | VerticalName) -> tuple[Attribute, ...]:
    """Attributes whose spec lists ``vertical`` (fashion-only cuts are not expected on beauty)."""
    wanted = Vertical(vertical)
    return tuple(a for a in ATTRIBUTES if wanted in a.verticals)


class BaseType(StrEnum):
    TEXT = "text"
    BOOL = "bool"
    INT = "int"
    NUMERIC = "numeric"
    JSONB = "jsonb"
    BIGINT = "bigint"
    ENUM = "enum"
    TIMESTAMPTZ = "timestamptz"
    DATE = "date"
    UUID = "uuid"


@dataclass(frozen=True, slots=True)
class TypeSpec:
    """A parsed spec type string."""

    base: BaseType
    is_array: bool = False
    nullable: bool = False
    #: Allowed values of an ``enum`` type; empty means the spec leaves the values open.
    enum_values: tuple[str, ...] = ()
    #: ``text(14)``: a declared length.
    length: int | None = None
    #: Anything else the spec appended: ``1-20``, ``x4``, ``[{fibre,pct}]``.
    detail: str | None = None


_HEAD_RE = re.compile(r"^(?P<base>[a-z]+)(?P<len>\(\d+\))?(?P<arr>\[\])?$")


def type_spec(attribute: Attribute | str) -> TypeSpec:
    """Parse ``attribute.type`` (or a raw type string). Unknown bases are an error, not text."""
    raw = attribute if isinstance(attribute, str) else attribute.type
    head, *rest = raw.split()
    m = _HEAD_RE.match(head)
    if m is None or m["base"] not in BaseType.__members__.values():
        raise ValueError(f"unknown type {raw!r}")
    nullable = "null" in rest
    rest = [r for r in rest if r != "null"]
    enum_values: tuple[str, ...] = ()
    if m["base"] == BaseType.ENUM and rest and "|" in rest[0]:
        enum_values = tuple(rest.pop(0).split("|"))
    return TypeSpec(
        base=BaseType(m["base"]),
        is_array=m["arr"] is not None,
        nullable=nullable,
        enum_values=enum_values,
        length=int(m["len"][1:-1]) if m["len"] else None,
        detail=" ".join(rest) or None,
    )
