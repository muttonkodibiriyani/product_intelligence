"""Coverage counts per retailer and attribute, and both renderings."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal

from pi_capture.coverage import AttributeCoverage, coverage
from pi_capture.model import ProductCapture, Reading
from pi_capture.registry import AttributeLevel, Vertical, applicable, page_sourced


def _row(report_rows: tuple[AttributeCoverage, ...], key: str) -> AttributeCoverage:
    return next(r for r in report_rows if r.key == key)


def test_counts_and_shares(make_capture: Callable[..., ProductCapture]) -> None:
    gtin_ok = Reading("gtin", AttributeLevel.VARIANT, "observed", "1", "00000000000001")
    gtin_bad = Reading("gtin", AttributeLevel.VARIANT, "parse_failed", "ABC")
    gtin_na = Reading("gtin", AttributeLevel.VARIANT, "not_applicable")
    title = Reading("title", AttributeLevel.COLOUR, "observed", "T")
    rise = Reading("rise", AttributeLevel.STYLE, "observed", "high")  # fashion-only, ignored
    pages = [
        make_capture("shop", (gtin_ok, title, rise)),
        make_capture("shop", (gtin_bad, title)),
        make_capture(
            "shop", (gtin_na, Reading("gtin", AttributeLevel.VARIANT, "observed", "2", None, "p"))
        ),
        make_capture("other", (title,)),
        make_capture("other", (), capture_state="blocked"),
        make_capture("other", (), capture_state="unparsed"),
    ]
    report = coverage(pages, vertical="beauty")
    assert report.vertical == "beauty"
    assert [r.retailer for r in report.retailers] == ["other", "shop"]
    beauty_page_keys = {a.key for a in page_sourced() if Vertical.BEAUTY in a.verticals}
    shop = report.retailers[1]
    assert shop.pages == 3
    assert {a.key for a in shop.attributes} == beauty_page_keys
    assert len(shop.attributes) == 91
    assert "rise" not in {a.key for a in shop.attributes}
    gtin = _row(shop.attributes, "gtin")
    assert (gtin.observed, gtin.parse_failed, gtin.not_shown) == (2, 1, 0)
    assert gtin.observed_share == Decimal("0.6667")
    assert _row(shop.attributes, "title").observed_share == Decimal("0.6667")
    never = _row(shop.attributes, "breadcrumb")
    assert never.not_shown == never.pages == 3
    assert never.observed_share == Decimal("0.0000")
    other = report.retailers[0]
    t = _row(other.attributes, "title")
    assert (t.observed, t.blocked, t.parse_failed, t.not_shown) == (1, 1, 1, 0)
    assert t.observed_share == Decimal("0.3333")


def test_attributes_nobody_looked_for_are_not_called_missing(
    make_capture: Callable[..., ProductCapture],
) -> None:
    title = Reading("title", AttributeLevel.COLOUR, "observed", "T")
    gtin_bad = Reading("gtin", AttributeLevel.VARIANT, "parse_failed", "ABC")
    pages = [
        make_capture("shop", (title,), looked_for=("title", "gtin")),
        make_capture("shop", (title, gtin_bad), looked_for=("title", "gtin")),
        make_capture("shop", (title,)),  # legacy capture without looked_for: old meaning holds
        make_capture("shop", (), capture_state="blocked", looked_for=("title",)),
    ]
    shop = coverage(pages, vertical="beauty").retailers[0]
    gtin = _row(shop.attributes, "gtin")
    assert (gtin.observed, gtin.parse_failed, gtin.not_shown, gtin.blocked) == (0, 1, 2, 1)
    assert gtin.not_looked_for == 0
    rating = _row(shop.attributes, "rating_value")
    assert (rating.not_looked_for, rating.not_shown, rating.blocked) == (2, 1, 1)
    assert rating.observed_share == Decimal("0.0000")
    assert _row(shop.attributes, "title").observed == 3
    # a reading for a key outside looked_for still counts: what was read was read
    extra = make_capture("shop", (gtin_bad,), looked_for=("title",))
    only = coverage([extra], vertical="beauty").retailers[0]
    assert _row(only.attributes, "gtin").parse_failed == 1
    md = coverage(pages, vertical="beauty").to_markdown()
    assert "| rating value | colour | content | 0 | 1 | 1 | 0 | 0 | 2 | 0.0% |" in md
    assert "not_looked_for" in str(coverage(pages, vertical="beauty").to_json())


def test_empty_and_fashion_vertical(make_capture: Callable[..., ProductCapture]) -> None:
    report = coverage([], vertical=Vertical.FASHION)
    assert report.retailers == ()
    assert "No pages were captured." in report.to_markdown()
    fashion = coverage([make_capture()], vertical="fashion").retailers[0]
    assert {a.key for a in fashion.attributes} == {
        a.key for a in applicable("fashion") if a in page_sourced()
    }


def test_renderings(make_capture: Callable[..., ProductCapture]) -> None:
    title = Reading("title", AttributeLevel.COLOUR, "observed", "T")
    report = coverage([make_capture("shop", (title,))], vertical="beauty")
    data = json.loads(report.to_json())
    assert data["vertical"] == "beauty"
    row = next(a for a in data["retailers"][0]["attributes"] if a["key"] == "title")
    assert row == {
        "key": "title",
        "level": "colour",
        "group": "content",
        "pages": 1,
        "observed": 1,
        "not_shown": 0,
        "blocked": 0,
        "parse_failed": 0,
        "not_applicable": 0,
        "not_looked_for": 0,
        "observed_share": "1.0000",
    }
    md = report.to_markdown()
    assert "## shop" in md
    assert "Pages read: 1" in md
    assert "| Not looked for |" in md
    assert "| title | colour | content | 1 | 0 | 0 | 0 | 0 | 0 | 100.0% |" in md
    assert "| image count | colour | content | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |" in md
    assert "_" not in md.split("| image count")[1].split("|")[0]
