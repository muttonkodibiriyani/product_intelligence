"""Caveat texts: English agrees in number, Arabic reads right for any count, digits stay digits."""

from __future__ import annotations

import re

import pytest

from pi_api.wire import _PLURAL, CAVEAT_TEXT, render
from pi_metrics import Caveat, CaveatCode

PARAMS = {
    "retailer": "shop_a",
    "base": "M",
    "other": "Medium",
    "pairs": "7",
    "asOf": "2026-09-22",
}


def _text(code: CaveatCode, count: str) -> tuple[str, str]:
    view = render(Caveat(code=code, params={**PARAMS, "count": count}))
    return view.en, view.ar


@pytest.mark.parametrize("code", list(CAVEAT_TEXT))
@pytest.mark.parametrize("count", ["0", "1", "2", "11", "100"])
def test_every_caveat_renders_its_numbers_as_digits(code: CaveatCode, count: str) -> None:
    for text in _text(code, count):
        assert "{" not in text
        assert "|" not in text
        if "{count}" in CAVEAT_TEXT[code].en:
            assert re.search(rf"(?<!\d){count}(?!\d)", text)


@pytest.mark.parametrize("code", [c for c, t in CAVEAT_TEXT.items() if "{count}" in t.en])
def test_one_is_singular_and_other_counts_are_plural(code: CaveatCode) -> None:
    one, _ = _text(code, "1")
    many, _ = _text(code, "2")
    assert not re.search(r"\b1 (\w+ )*(items|removals|ratings)\b", one)
    assert not re.search(r"\b(items|removals|ratings) (are|were|have|use)\b", one)
    assert re.search(r"\b2 (\w+ )*(items|removals|ratings)\b", many)


def test_singular_and_plural_texts() -> None:
    assert _text(CaveatCode.LAUNCHES_WITHHELD, "1")[0] == (
        "1 item first seen after an incomplete run is not shown as launches."
    )
    assert _text(CaveatCode.LAUNCHES_WITHHELD, "3")[0] == (
        "3 items first seen after an incomplete run are not shown as launches."
    )
    assert _text(CaveatCode.RATING_SCALE_MIXED, "1")[0] == (
        "1 rating at shop_a uses another scale and is left out."
    )
    assert _text(CaveatCode.SIZE_LABELS_DIFFER_TOTAL, "9")[0] == (
        "9 items have equal sizes labelled differently across 7 label pairs;"
        " the most frequent are listed."
    )


def test_arabic_ends_with_the_count_whatever_it_is() -> None:
    for count in ("1", "2", "5", "11"):
        assert _text(CaveatCode.EARLY_EXCLUDED, count)[1].endswith(f": {count}.")


def test_a_spec_without_a_bar_formats_as_usual() -> None:
    assert _PLURAL.format("{n:>3}", n="1") == "  1"


def test_a_stale_source_names_its_date_in_both_languages() -> None:
    view = render(
        Caveat(code=CaveatCode.STALE_SOURCE, params={"retailer": "shop_a", "asOf": "2026-09-22"})
    )
    for text in (view.en, view.ar):
        assert "shop_a" in text
        assert "2026-09-22" in text
