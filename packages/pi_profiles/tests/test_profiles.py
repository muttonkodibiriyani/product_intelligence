"""VerticalProfile: the export pinned to the committed declaration, the write path, the registry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

import pytest
from pydantic import ValidationError

from pi_dataset import AttributeType, committed_profile, committed_profiles
from pi_profiles import (
    BEAUTY_V1,
    PROFILES,
    REF_PATTERN,
    Attr,
    AttributeModel,
    UnknownProfileError,
    VerticalProfile,
    get_profile,
)


@pytest.mark.parametrize("ref", sorted(PROFILES))
def test_each_profile_exports_exactly_its_committed_declaration(ref: str) -> None:
    """ADR-0008 §0: profile code and the committed ``pi_dataset`` file can't drift."""
    profile = PROFILES[ref]
    assert profile.declaration() == committed_profile(profile.name, profile.version)


def test_every_committed_declaration_has_a_profile() -> None:
    assert sorted(PROFILES) == sorted(committed_profiles())


def test_refs_match_the_pattern() -> None:
    assert all(REF_PATTERN.fullmatch(ref) for ref in PROFILES)


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ({}, {}),
        ({"finish": "Matte"}, {"finish": "Matte"}),
        ({"finish": None, "shadeFamilies": []}, {}),
        (
            {"concentration": "EDP", "shadeFamilies": ["Nude", "Red"]},
            {"concentration": "EDP", "shadeFamilies": ["Nude", "Red"]},
        ),
    ],
)
def test_beauty_write_path_stores_the_canonical_jsonb(
    raw: dict[str, Any], stored: dict[str, Any]
) -> None:
    assert BEAUTY_V1.validate_attributes(raw) == stored


@pytest.mark.parametrize(
    "raw",
    [
        {"colour": "red"},  # undeclared key
        {"shade_families": ["Nude"]},  # the Python name, not the wire key
        {"finish": ""},
        {"finish": " "},
        {"finish": 1},
        {"shadeFamilies": "Nude"},
        {"shadeFamilies": ["Nude", ""]},
        {"concentration": ["EDP"]},
    ],
)
def test_beauty_write_path_rejects_without_coercing(raw: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"validation error|undeclared attribute keys"):
        BEAUTY_V1.validate_attributes(raw)


def test_python_names_are_refused_not_dropped() -> None:
    with pytest.raises(
        ValueError, match=r"beauty@1: undeclared attribute keys \['shade_families'\]"
    ):
        BEAUTY_V1.validate_attributes({"shade_families": ["Nude"]})


def test_type_errors_are_validation_errors() -> None:
    with pytest.raises(ValidationError):
        BEAUTY_V1.validate_attributes({"finish": 1})


@pytest.mark.parametrize("value", [Decimal("1.5"), float("nan"), date(2026, 10, 1)])
def test_non_json_values_are_value_errors(value: object) -> None:
    """Not a raw TypeError (#79 Reviewer nit): the documented error is ``ValueError``."""
    with pytest.raises(ValueError, match="attributes are not plain JSON values"):
        BEAUTY_V1.validate_attributes({"finish": value})


def test_get_profile() -> None:
    assert get_profile("beauty@1") is BEAUTY_V1
    with pytest.raises(UnknownProfileError, match="no registered profile beauty@2"):
        get_profile("beauty@2")
    with pytest.raises(UnknownProfileError, match="not a profile ref"):
        get_profile("beauty")


def test_a_field_without_attr_is_a_declaration_error() -> None:
    class Bad(AttributeModel):
        colour: str | None = None

    profile = VerticalProfile(
        name="bad",
        version=1,
        attributes=Bad,
        size_labels_comparable=False,
        size_system_required=False,
    )
    with pytest.raises(TypeError, match=r"Bad\.colour has no Attr"):
        profile.declaration()


def test_enum_values_are_declared() -> None:
    class Menu(AttributeModel):
        daypart: Annotated[
            str | None,
            Attr(
                AttributeType.ENUM,
                label={"en": "Daypart"},
                values=(("breakfast", {"en": "Breakfast"}),),
            ),
        ] = None

    profile = VerticalProfile(
        name="menu_test",
        version=1,
        attributes=Menu,
        size_labels_comparable=True,
        size_system_required=False,
    )
    (daypart,) = profile.declaration().attribute_set
    assert daypart.values is not None
    assert [v.id for v in daypart.values] == ["breakfast"]
    assert profile.ref == "menu_test@1"
