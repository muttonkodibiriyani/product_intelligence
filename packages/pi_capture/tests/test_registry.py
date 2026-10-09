"""The registry matches the spec file exactly and answers the basic questions about it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pi_capture import registry
from pi_capture.registry import (
    ATTRIBUTES,
    AttributeGroup,
    AttributeLevel,
    AttributeSource,
    BaseType,
    TypeSpec,
    UnknownAttributeError,
    Vertical,
    applicable,
    by_key,
    for_group,
    for_level,
    get,
    page_sourced,
    type_spec,
)
from pi_capture.registry_gen import (
    SPEC_PATH,
    TARGET_PATH,
    SpecError,
    load_spec,
    member_name,
    render,
    write,
)


def test_generated_module_matches_spec() -> None:
    assert TARGET_PATH.read_text(encoding="utf-8") == render(load_spec(SPEC_PATH))


def test_counts_from_the_requirements() -> None:
    assert len(ATTRIBUTES) == 145
    assert len(by_key()) == 145
    assert len(AttributeGroup) == 15
    assert len(AttributeLevel) == 4
    assert len(Vertical) == 3
    assert len(page_sourced()) == 118
    assert len(applicable("beauty")) == 114
    assert {str(a.level) for a in ATTRIBUTES} == {"style", "colour", "variant", "offer"}


def test_lookups() -> None:
    assert get("gtin").level is AttributeLevel.VARIANT
    assert get("gtin").source is AttributeSource.PAGE_OR_FEED
    assert get("price_minor") in for_group(AttributeGroup.COMMERCIAL)
    assert all(a.level is AttributeLevel.OFFER for a in for_level("offer"))
    assert all(Vertical.FOOD in a.verticals for a in applicable(Vertical.FOOD))
    assert all(a.source in registry.PAGE_SOURCES for a in page_sourced())
    assert get("page_template_hash") not in page_sourced()
    assert get("rise") not in applicable("beauty")
    with pytest.raises(UnknownAttributeError):
        get("colour_of_the_sky")
    with pytest.raises(ValueError, match="not a valid"):
        for_group("weather")


def test_the_retailer_go_live_date_never_shares_a_column_with_ours() -> None:
    # launch_date is ours (feed only); a rival's published go-live date is its own page key
    assert get("launch_date").source is AttributeSource.FEED
    assert get("launch_date") not in page_sourced()
    live = get("listing_live_date")
    assert live in page_sourced()
    assert (live.level, live.type, live.group) == (
        AttributeLevel.STYLE,
        "date",
        AttributeGroup.LIFECYCLE,
    )
    assert get("first_seen").source is AttributeSource.DERIVED


def test_every_type_string_parses() -> None:
    for a in ATTRIBUTES:
        assert isinstance(type_spec(a), TypeSpec)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("text", TypeSpec(BaseType.TEXT)),
        ("text[]", TypeSpec(BaseType.TEXT, is_array=True)),
        ("text(14)", TypeSpec(BaseType.TEXT, length=14)),
        ("bigint null", TypeSpec(BaseType.BIGINT, nullable=True)),
        ("enum ar|en", TypeSpec(BaseType.ENUM, enum_values=("ar", "en"))),
        ("enum", TypeSpec(BaseType.ENUM)),
        ("int 1-20", TypeSpec(BaseType.INT, detail="1-20")),
        ("jsonb [{fibre,pct}]", TypeSpec(BaseType.JSONB, detail="[{fibre,pct}]")),
        ("uuid[]", TypeSpec(BaseType.UUID, is_array=True)),
    ],
)
def test_type_spec(raw: str, expected: TypeSpec) -> None:
    assert type_spec(raw) == expected


def test_type_spec_rejects_unknown_base() -> None:
    with pytest.raises(ValueError, match="unknown type"):
        type_spec("money")
    with pytest.raises(ValueError, match="unknown type"):
        type_spec("Text")


def test_member_name() -> None:
    assert member_name("page or feed") == "PAGE_OR_FEED"
    assert member_name("page, mapped") == "PAGE_MAPPED"
    with pytest.raises(SpecError):
        member_name("1st")
    with pytest.raises(SpecError):
        member_name("--")


def _spec_with(tmp_path: Path, items: object) -> Path:
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(items), encoding="utf-8")
    return p


def test_load_spec_rejects_bad_shapes(tmp_path: Path) -> None:
    good = load_spec(SPEC_PATH)
    with pytest.raises(SpecError, match="non-empty"):
        load_spec(_spec_with(tmp_path, []))
    with pytest.raises(SpecError):
        load_spec(_spec_with(tmp_path, {"a": 1}))
    with pytest.raises(SpecError):
        load_spec(_spec_with(tmp_path, ["x"]))
    broken = dict(good[0])
    del broken["lvl"]
    with pytest.raises(SpecError, match="missing"):
        load_spec(_spec_with(tmp_path, [broken]))
    with pytest.raises(SpecError, match="unknown"):
        load_spec(_spec_with(tmp_path, [{**good[0], "extra": 1}]))
    with pytest.raises(SpecError, match="duplicate"):
        load_spec(_spec_with(tmp_path, [good[0], good[0]]))
    with pytest.raises(SpecError):
        load_spec(_spec_with(tmp_path, [{**good[0], "v": []}]))
    with pytest.raises(SpecError):
        load_spec(_spec_with(tmp_path, [{**good[0], "k": ""}]))
    with pytest.raises(SpecError):
        load_spec(_spec_with(tmp_path, [{**good[0], "note": 3}]))
    with pytest.raises(SpecError):
        load_spec(_spec_with(tmp_path, [{**good[0], "detail_only": "yes"}]))


def test_write_regenerates_identical_module(tmp_path: Path) -> None:
    out = write(SPEC_PATH, tmp_path / "_attributes.py")
    assert out.read_text(encoding="utf-8") == TARGET_PATH.read_text(encoding="utf-8")
