from __future__ import annotations

# ruff: noqa: S101
import pytest

from scripts.demo_export.export import ListingRow
from scripts.demo_export.test_export import row
from scripts.demo_export.tidy import brand_spellings, clean_text, display_name, tidy_rows


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
        ("Brand 10ml", "Brand", "Brand 10ml"),  # only a size would be left
        ("Brand 1.7 fl oz", "Brand", "Brand 1.7 fl oz"),
        ("Brand (Limited)", "Brand", "Brand (Limited)"),  # only a bracketed note would be left
        ("Brand (Limited) 50 ml", "Brand", "Brand (Limited) 50 ml"),
        ("Brand Lip Oil 10ml", "Brand", "Lip Oil 10ml"),
        ("Brand No 5", "Brand", "No 5"),
        (
            "Brand \u0639\u0637\u0631",
            "Brand",
            "\u0639\u0637\u0631",
        ),  # an Arabic word names something
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


def named(name: str, brand: str, source: str, variant: int) -> ListingRow:
    return ListingRow(
        **(row(source=source, variant=variant).__dict__ | {"name": name, "brand": brand})
    )


def test_only_sephora_rows_are_tidied_and_only_sephora_rows_vote_on_spelling() -> None:
    ulta = [
        named(" Shu Uemura  Art Of Brow ", "Shu Uemura", "ulta_ae", variant)
        for variant in (1, 2, 3)
    ]
    sephora = [
        named("SHU UEMURA Ultime8", "SHU UEMURA", "sephora_me", 4),
        named("Ultime8 Mini", "SHU UEMURA", "sephora_me", 5),
        named("Cleansing Oil", "Shu Uemura", "sephora_me", 6),
    ]
    tidied = tidy_rows([*ulta, *sephora])
    assert tidied[:3] == ulta  # Ulta untouched, and its three rows did not outvote Sephora
    assert [(r.brand, r.name) for r in tidied[3:]] == [
        ("SHU UEMURA", "Ultime8"),
        ("SHU UEMURA", "Ultime8 Mini"),
        ("SHU UEMURA", "Cleansing Oil"),
    ]
