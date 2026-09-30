import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from pi_core import (
    COUNTRY_CODES,
    CountryCode,
    Locale,
    LocaleTag,
    Market,
    Money,
    is_rtl,
    language_of,
    region_of,
)
from pi_core.money import CURRENCY_EXPONENTS

COUNTRY = TypeAdapter(CountryCode)
LOCALE = TypeAdapter(LocaleTag)


def test_country_codes_are_iso_3166_alpha_2() -> None:
    assert {"AE", "SA", "KW", "QA", "BH", "OM", "FR", "US", "JP", "GB"} <= COUNTRY_CODES
    assert len(COUNTRY_CODES) >= 249
    assert all(len(c) == 2 and c.isupper() for c in COUNTRY_CODES)
    assert {m.value for m in Market} <= COUNTRY_CODES  # the deprecated enum is a subset of data


@pytest.mark.parametrize("bad", ["XX", "sa", "UAE", "", "EU"])
def test_unknown_country_rejected(bad: str) -> None:
    with pytest.raises(ValidationError, match="ISO 3166-1"):
        COUNTRY.validate_python(bad)


@pytest.mark.parametrize(
    ("tag", "language", "region", "rtl"),
    [
        ("en", "en", None, False),
        ("ar", "ar", None, True),
        ("ar-AE", "ar", "AE", True),
        ("fr-FR", "fr", "FR", False),
        ("es-419", "es", "419", False),
        ("zh-Hant-TW", "zh", "TW", False),
        ("az-Arab", "az", None, True),  # the script decides
        ("ku-Latn", "ku", None, False),  # an explicit Latin script overrides an RTL language
        ("he-IL", "he", "IL", True),
        ("fa", "fa", None, True),
    ],
)
def test_locale_tags(tag: str, language: str, region: str | None, rtl: bool) -> None:
    assert LOCALE.validate_python(tag) == tag
    assert language_of(tag) == language
    assert region_of(tag) == region
    assert is_rtl(tag) is rtl


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        ("en_US", "canonical BCP 47"),
        ("EN", "canonical BCP 47"),
        ("en-us", "canonical BCP 47"),
        ("english", "canonical BCP 47"),
        ("en-XX", "ISO 3166-1"),
        ("", "canonical BCP 47"),
    ],
)
def test_bad_locale_rejected(bad: str, error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        LOCALE.validate_python(bad)


def test_deprecated_locale_enum_agrees_with_data() -> None:
    for locale in Locale:
        assert LOCALE.validate_python(locale) == locale.value
        assert is_rtl(locale) is locale.is_rtl


@pytest.mark.parametrize(
    ("currency", "exponent"),
    [("AED", 2), ("SAR", 2), ("KWD", 3), ("BHD", 3), ("OMR", 3), ("JPY", 0), ("CLF", 4)],
)
def test_iso_4217_exponents(currency: str, exponent: int) -> None:
    assert CURRENCY_EXPONENTS[currency] == exponent
    assert Money.of("1", currency).exponent == exponent


def test_iso_4217_table_is_complete_and_current() -> None:
    assert len(CURRENCY_EXPONENTS) >= 150
    assert {"EUR", "USD", "GBP", "INR", "EGP", "QAR"} <= set(CURRENCY_EXPONENTS)
    assert not {"HRK", "SLL", "CUC", "ANG", "ZWL"} & set(CURRENCY_EXPONENTS)  # withdrawn


def test_kwd_keeps_fils() -> None:
    price = Money.of("12.345", "KWD")
    assert str(price.rounded()) == "12.345 KWD"
    assert (price + Money.of("0.005", "KWD")).amount == Money.of("12.350", "KWD").amount


@given(st.sampled_from(sorted(COUNTRY_CODES)), st.sampled_from(["en", "ar", "fr", "zh-Hant"]))
def test_any_language_with_any_country_is_a_tag(country: str, language: str) -> None:
    tag = f"{language}-{country}"
    assert LOCALE.validate_python(tag) == tag
    assert region_of(tag) == country
