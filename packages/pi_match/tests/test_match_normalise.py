import json
from decimal import Decimal
from importlib import resources

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_match.normalise import (
    BRAND_ALIASES,
    MAX_LIST_TEXT,
    Concentration,
    ItemKind,
    Shade,
    Size,
    concentration,
    fold,
    item_kind,
    list_groups,
    name_tokens,
    normalise_brand,
    parse_brand_aliases,
    parse_shade,
    parse_size,
    valid_gtin,
)


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("Estée Lauder", "estee lauder"),
        ("ESTEE LAUDER", "estee lauder"),
        ("YSL Beauty", "yves saint laurent"),
        ("Yves Saint Laurent", "yves saint laurent"),
        ("M·A·C", "mac"),
        ("MAC Cosmetics", "mac"),
        ("NARS Cosmetics", "nars"),
        ("Fenty", "fenty beauty"),
        ("Fenty Beauty", "fenty beauty"),
        ("Too Faced", "too faced"),
        ("Kiehl's Since 1851", "kiehls"),
        ("L'Oréal Paris", "loreal paris"),
        ("Dolce & Gabbana", "dolce and gabbana"),
        ("Dolce and Gabbana", "dolce and gabbana"),
        ("Christian Dior", "dior"),
        ("Lancôme", "lancome"),
        ("Charlotte Tilbury", "charlotte tilbury"),
        # Ulta prints brands in capitals, Sephora in title case (#28).
        ("KYLIE COSMETICS", "kylie"),
        ("Kylie Cosmetics", "kylie"),
        ("Kylie Cosmetics by Kylie Jenner", "kylie"),
        ("FENTY BEAUTY BY RIHANNA", "fenty beauty"),
        ("MAKE UP FOR EVER", "make up for ever"),
        ("L'ORÉAL PARIS", "loreal paris"),
        ("BENEFIT COSMETICS", "benefit"),
    ],
)
def test_normalise_brand(raw: str, key: str) -> None:
    assert normalise_brand(raw) == key


def test_brand_aliases_are_reviewed_data() -> None:
    """ADR-0007 §4: a sorted ``{canonical: [aliases]}`` file, the shape of ``brand.aliases``."""
    raw = resources.files("pi_match").joinpath("brand_aliases.json").read_text(encoding="utf-8")
    data: dict[str, list[str]] = json.loads(raw)
    assert list(data) == sorted(data)
    assert all(spellings == sorted(spellings) and spellings for spellings in data.values())
    assert dict(BRAND_ALIASES) == {a: c for c, spellings in data.items() for a in spellings}
    assert BRAND_ALIASES["ysl"] == "yves saint laurent"


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ('{"dior": ["christian dior"], "ck": ["christian dior"]}', "listed twice"),
        ('{"dior": ["ck"], "ck": ["calvin klein"]}', "itself a canonical"),
        ('{"dior": ["Christian Dior"]}', "not folded"),
        ('{"Dior": ["christian dior"]}', "not folded"),
        # #79 Reviewer: json.loads would keep only the last "dior" ...
        ('{"dior": ["christian dior"], "dior": ["cd"]}', "canonical brand listed twice"),
        # ... and iterate a bare string as one alias per character (c -> dior, d -> dior).
        ('{"dior": "cd"}', "must map to a list of strings"),
        ('{"dior": [1]}', "must map to a list of strings"),
        ('{"dior": null}', "must map to a list of strings"),
        ('["dior"]', "expected an object"),
    ],
)
def test_parse_brand_aliases_rejects(raw: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_brand_aliases(raw)


def test_fold() -> None:
    assert fold("  Crème  de la MER! ") == "creme de la mer"
    assert fold("Rock & Roll") == "rock and roll"


@given(st.text(alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzéô&' ")))
def test_brand_key_ignores_case(text: str) -> None:
    assert normalise_brand(text.upper()) == normalise_brand(text) == normalise_brand(text.title())


@given(st.text())
def test_brand_normalisation_is_idempotent(text: str) -> None:
    once = normalise_brand(text)
    assert normalise_brand(once) == once


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("50ml", Size(Decimal(50), "ml")),
        ("Libre Eau de Parfum 90 ML", Size(Decimal(90), "ml")),
        ("1.7 fl oz", Size(Decimal("50.27495"), "ml")),
        ("1 fl. oz.", Size(Decimal("29.5735"), "ml")),
        ("3,5 g", Size(Decimal("3.5"), "g")),
        ("0.1 oz", Size(Decimal("2.83495"), "g")),
        ("1 L", Size(Decimal(1000), "ml")),
        ("500 mg", Size(Decimal("0.5"), "g")),
    ],
)
def test_parse_size(text: str, size: Size) -> None:
    assert parse_size(text) == size


@pytest.mark.parametrize("text", [None, "", "Foundation SPF 10", "No. 5", "24h wear", "5.5"])
def test_parse_size_absent(text: str | None) -> None:
    assert parse_size(text) is None


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("['100'] ['ML']", Size(Decimal(100), "ml")),
        ("['3.4'] ['oz']", Size(Decimal("96.3883"), "g")),
        ('["50 ml"]', Size(Decimal(50), "ml")),
        ("['1.7 fl oz / 50 ml']", Size(Decimal("50.27495"), "ml")),  # one size in two units
    ],
)
def test_parse_size_from_list_text(text: str, size: Size) -> None:
    assert parse_size(text) == size


@pytest.mark.parametrize(
    "text",
    [
        "['50', '90'] ['ML']",  # several sizes: ambiguous, never the first
        "['30 ml', '50 ml']",
        "['NOSIZE']",
        "['one size']",
        "['100']",  # a number without a unit
        "[]",
    ],
)
def test_parse_size_from_list_text_absent(text: str) -> None:
    assert parse_size(text) is None


@given(
    st.decimals(min_value=1, max_value=999, places=1),
    st.sampled_from(["ml", "ML", "g", "fl oz", "oz", "l", "mg"]),
)
def test_single_item_list_parses_like_plain_text(amount: Decimal, unit: str) -> None:
    assert parse_size(f"['{amount}'] ['{unit}']") == parse_size(f"{amount} {unit}")
    assert parse_size(f'["{amount} {unit}"]') == parse_size(f"{amount} {unit}")


def test_list_groups() -> None:
    assert list_groups("['50', '90'] ['ML']") == (("50", "90"), ("ML",))
    assert list_groups('["a", " ", ""]') == (("a",),)
    assert list_groups("['L\\'Oreal Red']") == (("L'Oreal Red",),)
    assert list_groups("['a]b', 'c']") == (("a]b", "c"),)
    assert list_groups(("50 ml",)) == (("50 ml",),)


@pytest.mark.parametrize(
    "text",
    [
        "50 ml",  # not a list
        "['50'",  # unclosed
        "['50'] trailing",
        "[['50']]",  # nested
        "[{'a': 1}]",
        "[True]",
        "[__import__('os')]",  # never evaluated
        "['x'] " * 200,  # longer than MAX_LIST_TEXT
    ],
)
def test_list_groups_rejects_other_shapes(text: str) -> None:
    assert list_groups(text) is None


def test_list_text_is_capped() -> None:
    assert len("['x'] " * 200) > MAX_LIST_TEXT


@pytest.mark.parametrize(
    "value",
    [
        "['50'] ['ML', 'G']",  # one value, two units: ambiguous
        "['50'] ['G', 'ML']",
        "['50', '50 g'] ['ML']",
        ("30 ml", "50 ml"),
    ],
)
def test_ambiguous_size_lists_give_none(value: str | tuple[str, ...]) -> None:
    assert parse_size(value) is None


def test_shade_list_text_with_quotes_inside() -> None:
    assert parse_shade("['L\\'Oreal Red']") == Shade(None, "loreal red")
    assert parse_shade('["He said \\"hi\\""]') == Shade(None, "he said hi")
    assert parse_shade(('He said "hi"',)) == Shade(None, "he said hi")


_SIZE_TEXT = st.builds(
    "{} {}".format,
    st.integers(min_value=1, max_value=999),
    st.sampled_from(["ml", "g", "fl oz", "oz", "l"]),
)


@given(st.lists(_SIZE_TEXT, min_size=2, max_size=5, unique=True))
def test_two_or_more_distinct_sizes_give_none(items: list[str]) -> None:
    assert parse_size(repr(items)) is None
    assert parse_size(tuple(items)) is None


@given(
    st.lists(
        st.text(min_size=1, max_size=12).map(str.strip).filter(bool),
        min_size=2,
        max_size=5,
        unique=True,
    )
)
def test_two_or_more_distinct_shades_give_none(items: list[str]) -> None:
    assert parse_shade(repr(items)) is None
    assert parse_shade(tuple(items)) is None


def test_size_same_as_tolerance() -> None:
    fl_oz = parse_size("1 fl oz")
    assert fl_oz is not None
    assert fl_oz.same_as(Size(Decimal(30), "ml"))
    assert not Size(Decimal(50), "ml").same_as(Size(Decimal(100), "ml"))
    assert not Size(Decimal(50), "ml").same_as(Size(Decimal(50), "g"))


@pytest.mark.parametrize(
    ("text", "shade"),
    [
        ("220 Natural Beige", Shade("220", "natural beige")),
        ("N12 - Vanilla", Shade("n12", "vanilla")),
        ("1W2 Sand", Shade("1w2", "sand")),
        ("No. 5", Shade("5", None)),
        ("Mont Blanc", Shade(None, "mont blanc")),
        ("2.5 Warm", Shade("2.5", "warm")),
    ],
)
def test_parse_shade(text: str, shade: Shade) -> None:
    assert parse_shade(text) == shade


def test_parse_shade_from_list_text() -> None:
    assert parse_shade("['220 Natural Beige']") == Shade("220", "natural beige")
    assert parse_shade("['Rose', 'Nude']") is None  # several shades: a parent row
    assert parse_shade("[]") is None


@pytest.mark.parametrize("text", [None, "", "!!"])
def test_parse_shade_absent(text: str | None) -> None:
    assert parse_shade(text) is None


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Libre Eau de Parfum", Concentration.EDP),
        ("Bleu EDT 100ml", Concentration.EDT),
        ("Bleu de Chanel Parfum", Concentration.PARFUM),
        ("Cloud Hair & Body Mist", Concentration.BODY_MIST),
        ("Acqua di Gio Eau de Cologne", Concentration.EDC),
        ("Double Wear Foundation", None),
    ],
)
def test_concentration(text: str, value: Concentration | None) -> None:
    assert concentration(text) is value


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Gloss Bomb Mini", ItemKind.MINI),
        ("Travel Size Setting Spray", ItemKind.MINI),
        ("Libre EDP Refill", ItemKind.REFILL),
        ("Holiday Gift Set", ItemKind.SET),
        ("Lip Kit", ItemKind.SET),
        ("Matte Lipstick", ItemKind.REGULAR),
    ],
)
def test_item_kind(text: str, kind: ItemKind) -> None:
    assert item_kind(text) is kind


def test_name_tokens_drop_brand_sizes_and_attributes() -> None:
    tokens = name_tokens("YSL Libre Eau de Parfum Spray 50 ml", "yves saint laurent")
    assert tokens == frozenset({"ysl", "libre"})
    assert name_tokens("Libre - Eau de Parfum", "ysl") == frozenset({"libre"})


@pytest.mark.parametrize(
    ("gtin", "value"),
    [
        ("020714919443", "00020714919443"),
        ("0020714919443", "00020714919443"),
        ("4006381333931", "04006381333931"),
        ("96385074", "00000096385074"),
        ("020714919446", None),
        ("12345", None),
        (None, None),
        ("abc", None),
    ],
)
def test_valid_gtin(gtin: str | None, value: str | None) -> None:
    assert valid_gtin(gtin) == value
