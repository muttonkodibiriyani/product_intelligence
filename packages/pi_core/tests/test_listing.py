from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pi_core import (
    Concentration,
    FieldState,
    ImageRef,
    ImageRole,
    ListingRecord,
    Locale,
    gtin14,
    is_valid_gtin,
)
from pi_core.listing import gtin_check_digit

T0 = datetime(2026, 9, 30, tzinfo=UTC)
GTIN = "3614273069540"  # a real EAN-13


def listing_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_id": 2,
        "source_listing_key": "P123-50ML",
        "source_sku": "123456",
        "url": "https://www.sephora.me/sa-en/p/P123",
        "lang": Locale.EN,
        "name_original": "Libre Eau de Parfum",
        "name_ar": "ليبر أو دو بارفان",
        "brand": "YSL",
        "gtin": GTIN,
        "mpn": None,
        "shade": None,
        "shade_code": None,
        "size_value": "50",
        "size_unit": "ml",
        "pack_count": 1,
        "concentration": Concentration.EDP,
        "category_path_source": ("Fragrance", "Women", "Eau de Parfum"),
        "images": (
            {"source_url": "https://cdn.sephora.me/p123-1.jpg", "role": "main", "position": 0},
            {"source_url": "https://cdn.sephora.me/p123-2.jpg", "role": "alt", "position": 0},
        ),
        "evidence_id": 7,
        "observed_at": T0,
        "field_state": {
            "mpn": FieldState.NOT_PUBLISHED,
            "shade": FieldState.NOT_APPLICABLE,
            "shade_code": FieldState.NOT_APPLICABLE,
        },
    }
    return data | overrides


def listing(**overrides: Any) -> ListingRecord:
    return ListingRecord.model_validate(listing_data(**overrides))


def test_valid_listing() -> None:
    rec = listing()
    assert rec.size_value == Decimal(50)
    assert rec.images is not None
    assert rec.images[0] == ImageRef(
        source_url="https://cdn.sephora.me/p123-1.jpg",  # type: ignore[arg-type]
        role=ImageRole.MAIN,
        position=0,
    )
    assert rec.natural_key == (2, "P123-50ML")


def test_natural_key_ignores_locale_and_content() -> None:
    ar = listing(lang=Locale.AR, name_original="ليبر", url="https://www.sephora.me/sa-ar/p/P123")
    assert ar.natural_key == listing().natural_key
    assert listing(source_listing_key="P123-90ML").natural_key != listing().natural_key


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"brand": None}, "brand is null without a field_state reason"),
        (
            {"field_state": {"brand": FieldState.UNKNOWN, **listing_data()["field_state"]}},
            "brand has a value and a field_state reason",
        ),
        ({"field_state": {"attributes": FieldState.UNKNOWN}}, "untracked"),
        ({"gtin": "3614273069541"}, "invalid GTIN"),
        ({"size_unit": None}, "size_value and size_unit"),
        ({"size_value": 50.0}, "float"),
        ({"pack_count": 0}, "greater than or equal"),
        ({"category_path_source": ()}, "at least 1"),
        ({"name_original": "  "}, "should match pattern"),
        ({"colour": "red"}, "Extra inputs"),
        (
            {
                "images": (
                    {"source_url": "https://cdn/a.jpg", "role": "main", "position": 0},
                    {"source_url": "https://cdn/b.jpg", "role": "main", "position": 0},
                )
            },
            "duplicate image",
        ),
    ],
)
def test_listing_invariants(overrides: dict[str, Any], error: str) -> None:
    with pytest.raises((ValidationError, TypeError), match=error):
        listing(**overrides)


def test_missing_fields_with_reasons_are_accepted() -> None:
    missing = ("brand", "gtin", "size_value", "images", "category_path_source")
    states = dict.fromkeys(missing, FieldState.NOT_PUBLISHED)
    rec = listing(
        brand=None,
        gtin=None,
        size_value=None,
        size_unit=None,
        images=None,
        category_path_source=None,
        field_state=listing_data()["field_state"] | states,
    )
    assert rec.gtin is None
    assert rec.field_state["images"] is FieldState.NOT_PUBLISHED


@given(
    st.text(alphabet="0123456789", min_size=7, max_size=13).filter(
        lambda s: len(s) in {7, 11, 12, 13}
    )
)
def test_gtin_check_digit_property(body: str) -> None:
    code = body + gtin_check_digit(body)
    assert is_valid_gtin(code)
    assert len(gtin14(code)) == 14
    wrong = str((int(code[-1]) + 1) % 10)
    assert not is_valid_gtin(code[:-1] + wrong)


@pytest.mark.parametrize("bad", ["", "abc", "123", "٣٦١٤٢٧٣٠٦٩٥٤٠", "36142730695400000"])
def test_bad_gtins(bad: str) -> None:
    assert not is_valid_gtin(bad)
    with pytest.raises(ValueError, match="invalid GTIN"):
        gtin14(bad)


text = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=("Cs", "Cc", "Zs", "Zl", "Zp")),
    min_size=1,
    max_size=20,
)


@given(
    key=text,
    name=text,
    lang=st.sampled_from(Locale),
    size=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(10000), places=2),
    path=st.lists(text, min_size=1, max_size=4).map(tuple),
)
def test_listing_round_trip(
    key: str, name: str, lang: Locale, size: Decimal, path: tuple[str, ...]
) -> None:
    rec = listing(
        source_listing_key=key,
        name_original=name,
        lang=lang,
        size_value=size,
        category_path_source=path,
    )
    again = ListingRecord.model_validate_json(rec.model_dump_json())
    assert again == rec
    assert again.natural_key == rec.natural_key
    assert again.size_value is not None
    assert again.size_value.as_tuple() == size.as_tuple()
