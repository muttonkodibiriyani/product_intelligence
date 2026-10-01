from __future__ import annotations

# ruff: noqa: S101
import pytest

from scripts.demo_export.tidy import brand_spellings, clean_text, display_name


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  Lip  Oil ", "Lip Oil"),
        ("Lip\tOil\nMini", "Lip Oil Mini"),
        ("Lip\u00a0Oil", "Lip Oil"),
        ("Lip\u200bOil", "LipOil"),
        ("\ufeffLip Oil", "Lip Oil"),
        ("Lip Oil", "Lip Oil"),
    ],
)
def test_clean_text_folds_whitespace_and_drops_zero_width_characters(raw: str, clean: str) -> None:
    assert clean_text(raw) == clean


@pytest.mark.parametrize(
    ("name", "brand", "shown"),
    [
        ("Brand Lip Oil", "Brand", "Lip Oil"),
        ("BRAND - Lip Oil", "Brand", "Lip Oil"),
        ("Brand \u2013 Lip Oil", "Brand", "Lip Oil"),
        ("Brand: Lip Oil", "Brand", "Lip Oil"),
        ("Brand  Lip  Oil ", "Brand", "Lip Oil"),
        ("Brandshow Mascara", "Brand", "Brandshow Mascara"),  # the brand runs into a longer word
        ("Brand", "Brand", "Brand"),  # nothing would be left
        ("Brand -", "Brand", "Brand -"),
        ("Lip Oil by Brand", "Brand", "Lip Oil by Brand"),
        ("Lip Oil", "", "Lip Oil"),
        ("ROUGE ALLURE", "Brand", "ROUGE ALLURE"),  # all-caps names are kept as published
    ],
)
def test_display_name_drops_only_a_leading_repeat_of_the_brand(
    name: str, brand: str, shown: str
) -> None:
    assert display_name(name, brand) == shown


def test_one_brand_has_one_spelling_most_rows_then_not_all_caps() -> None:
    spellings = brand_spellings(["SHU UEMURA", "Shu Uemura", "Shu Uemura", "Dior", "DIOR"])
    assert spellings == {"shu uemura": "Shu Uemura", "dior": "Dior"}
    assert brand_spellings(["SHU UEMURA", "SHU UEMURA", "Shu Uemura"]) == {
        "shu uemura": "SHU UEMURA"
    }
    assert brand_spellings([" Dior "]) == {"dior": "Dior"}
