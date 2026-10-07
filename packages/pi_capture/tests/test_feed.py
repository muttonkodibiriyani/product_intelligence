"""Readings -> offline_import feed. Synthetic captures only; no real retailer page is used."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from offline_import.mapping import ImportMapping
from offline_import.validate import validate_file
from pi_capture.feed import SHOPS, Shop, _major, build_feed, main, mapping_for
from pi_capture.generic import readings_from_generic
from pi_capture.model import JsonValue, ProductCapture, Reading, ReadingState, dumps
from pi_capture.registry import get

CaptureFactory = Callable[..., ProductCapture]

SHOP = Shop(
    source="example_ae",
    base_url="https://shop.example",
    country="AE",
    locale="en-AE",
    currency="AED",
    time_zone="Asia/Dubai",
    notes="synthetic",
)


def r(
    key: str,
    value: JsonValue = None,
    state: ReadingState = "observed",
    currency: str | None = None,
    path: str | None = None,
) -> Reading:
    """A reading at the key's registry level; ``raw_text`` only where the state allows it."""
    raw = None if state in {"not_shown", "blocked", "not_applicable"} else str(value)
    return Reading(key, get(key).level, state, raw, value, path or f"test.{key}", None, currency)


def page(make_capture: CaptureFactory, *readings: Reading, **kw: object) -> ProductCapture:
    base = (r("retailer_sku", "SKU-1"), r("title", "Glow Serum"), r("brand", "Glow"))
    return make_capture(readings=base + readings, **kw)


def _validate(tmp_path: Path, captures: list[ProductCapture], shop: Shop = SHOP) -> dict:  # type: ignore[type-arg]
    out = tmp_path / "out"
    readings = tmp_path / "readings.jsonl"
    readings.write_text("".join(dumps(c) + "\n" for c in captures), "utf-8")
    assert main([*_shop_args(shop), str(readings), str(out)]) == 0
    mapping = ImportMapping.model_validate_json(
        (out / f"{shop.source}.mapping.json").read_text("utf-8")
    )
    return validate_file(out / f"{shop.source}.feed.json", mapping).to_json()


def _shop_args(shop: Shop) -> list[str]:
    SHOPS[shop.source] = shop  # registered for the CLI only within this test
    return [shop.source]


@pytest.fixture(autouse=True)
def _restore_shops() -> object:
    before = dict(SHOPS)
    yield
    SHOPS.clear()
    SHOPS.update(before)


def test_a_generic_page_becomes_one_valid_importer_row(
    tmp_path: Path, make_capture: CaptureFactory, product_html: str
) -> None:
    capture = make_capture(readings=tuple(readings_from_generic(product_html, locale="en-AE")))
    result = build_feed([capture], SHOP)
    assert result.excluded == []
    (row,) = result.rows
    assert row["listing_key"] == "SEP-11029384"
    assert row["price_current"] == "189.00"
    assert row["url"] == "https://shop.example/en/p/foundation-240"
    assert row["observed_at"] == "2026-10-02T09:00:00+00:00"
    report = _validate(tmp_path, [capture])
    assert (report["rows"], report["accepted"], report["rejected"]) == (1, 1, [])


def test_a_reduced_price_fills_regular_and_promo(make_capture: CaptureFactory) -> None:
    capture = page(
        make_capture,
        r("price_minor", 8000, currency="AED"),
        r("regular_price_minor", 10000, currency="AED"),
    )
    (row,) = build_feed([capture], SHOP).rows
    assert (row["price_current"], row["price_regular"], row["price_promo"]) == (
        "80.00",
        "100.00",
        "80.00",
    )


@pytest.mark.parametrize(
    ("regular", "reason"),
    [
        (8000, "regular price equals current price"),
        (7000, "regular price below current price"),
    ],
)
def test_a_regular_price_not_above_the_current_one_is_not_a_promotion(
    make_capture: CaptureFactory, regular: int, reason: str
) -> None:
    capture = page(
        make_capture,
        r("price_minor", 8000, currency="AED"),
        r("regular_price_minor", regular, currency="AED"),
    )
    result = build_feed([capture], SHOP)
    (row,) = result.rows
    assert row["price_current"] == "80.00"
    assert not {"price_regular", "price_promo"} & row.keys()
    assert result.report()["regular_price_dropped"] == {reason: 1}


def test_a_dropped_regular_price_on_a_duplicate_page_is_not_counted(
    make_capture: CaptureFactory,
) -> None:
    first = page(make_capture, r("price_minor", 8000, currency="AED"))
    again = page(
        make_capture,
        r("price_minor", 8000, currency="AED"),
        r("regular_price_minor", 8000, currency="AED"),
    )
    result = build_feed([first, again], SHOP)
    assert len(result.rows) == 1
    assert result.report()["regular_price_dropped"] == {}


def test_no_observed_price_leaves_the_columns_out_and_the_importer_says_not_published(
    tmp_path: Path, make_capture: CaptureFactory
) -> None:
    capture = page(make_capture, r("price_minor", state="not_shown"))
    (row,) = build_feed([capture], SHOP).rows
    assert not {"price_current", "price_regular", "price_promo"} & row.keys()
    report = _validate(tmp_path, [capture])
    assert report["accepted"] == 1
    assert "no price published" in json.dumps(report["warnings"])


def test_a_regular_price_without_a_current_one_is_not_written(make_capture: CaptureFactory) -> None:
    capture = page(make_capture, r("regular_price_minor", 10000, currency="AED"))
    (row,) = build_feed([capture], SHOP).rows
    assert "price_regular" not in row


@pytest.mark.parametrize("currency", ["SAR", None])
def test_a_price_in_another_currency_leaves_the_page_out(
    make_capture: CaptureFactory, currency: str | None
) -> None:
    reading = (
        r("price_minor", 8000, currency=currency)
        if currency
        else Reading("price_minor", get("price_minor").level, "observed", "80", 8000, "p")
    )
    result = build_feed([page(make_capture, reading)], SHOP)
    assert result.rows == []
    assert result.excluded[0]["reason"] == f"price in {currency or 'no currency'}, feed is AED"


def test_pages_without_a_key_duplicates_other_locales_and_blocked_captures_are_listed(
    make_capture: CaptureFactory,
) -> None:
    keyless = make_capture(readings=(r("title", "No Key"),))
    first = page(make_capture)
    again = page(make_capture, url="https://shop.example/en/p/again")
    arabic = page(make_capture, locale="ar-AE")
    blocked = make_capture(capture_state="blocked")
    result = build_feed([keyless, first, again, arabic, blocked], SHOP)
    assert [row["listing_key"] for row in result.rows] == ["SKU-1"]
    assert result.report()["excluded_by_reason"] == {
        "capture blocked": 1,
        "duplicate retailer_sku": 1,
        "locale ar-AE": 1,
        "no retailer_sku on the page": 1,
    }


def test_optional_columns_come_only_from_observed_readings(make_capture: CaptureFactory) -> None:
    capture = page(
        make_capture,
        r("gtin", "03000000000017"),
        r("category_l1..l4", ["Makeup", " ", "Face"]),
        r("size_label", "30 ml"),
        r("shade_name", state="not_shown"),
        r("image_urls", ["https://img.example/1.jpg", "https://img.example/2.jpg"]),
        r("canonical_url", state="not_shown"),
    )
    result = build_feed([capture], SHOP)
    (row,) = result.rows
    assert row["gtin"] == "03000000000017"
    assert row["category_path"] == "Makeup > Face"
    assert row["size"] == "30 ml"
    assert row["image_url"] == "https://img.example/1.jpg"
    assert row["url"] == "https://shop.example/en/p/x"
    assert "shade" not in row
    assert result.report()["filled"]["shade"] == 0


def _markup(*availability: str) -> Reading:
    offers: list[JsonValue] = [{"@type": "Offer", "availability": a} for a in availability]
    return r("structured_data", [{"@type": "Product", "offers": offers}])


@pytest.mark.parametrize(
    ("statements", "expected"),
    [
        (("http://schema.org/InStock",), "instock"),
        (("https://schema.org/OutOfStock",), "outofstock"),
        (("LimitedAvailability",), "limitedavailability"),
        (("http://schema.org/InStock", "http://schema.org/OutOfStock"), None),
        (("http://schema.org/PreOrder",), None),
    ],
)
def test_markup_availability_is_used_only_when_the_page_states_one_known_value(
    make_capture: CaptureFactory, statements: tuple[str, ...], expected: str | None
) -> None:
    shop = replace(SHOP, markup_availability=True)
    result = build_feed([page(make_capture, _markup(*statements))], shop)
    assert result.rows[0].get("availability") == expected
    if statements == ("http://schema.org/PreOrder",):
        assert result.report()["unmapped_availability"] == {"preorder": 1}


def test_markup_availability_is_ignored_unless_the_shop_trusts_it(
    make_capture: CaptureFactory,
) -> None:
    result = build_feed([page(make_capture, _markup("http://schema.org/InStock"))], SHOP)
    assert "availability" not in result.rows[0]
    assert "availability" not in mapping_for(SHOP)["columns"]
    assert "availability_map" not in mapping_for(SHOP)


def test_trusted_availability_validates_in_the_importer(
    tmp_path: Path, make_capture: CaptureFactory
) -> None:
    shop = replace(SHOP, source="example_trusted", markup_availability=True)
    captures = [
        page(make_capture, _markup("http://schema.org/OutOfStock")),
        make_capture(readings=(r("retailer_sku", "SKU-2"), _markup("http://schema.org/InStock"))),
    ]
    report = _validate(tmp_path, captures, shop)
    assert (report["accepted"], report["rejected"]) == (2, [])


@pytest.mark.parametrize(
    ("minor", "currency", "major"),
    [(51500, "AED", "515.00"), (12345, "KWD", "12.345"), (1, "SAR", "0.01")],
)
def test_minor_units_keep_the_currency_exponent(minor: int, currency: str, major: str) -> None:
    assert _major(minor, currency) == major


@pytest.mark.parametrize("bad", [0, -5, True, Decimal("1.5"), "100", None])
def test_non_positive_or_non_integer_minor_units_are_not_prices(bad: JsonValue) -> None:
    assert _major(bad, "AED") is None


def test_the_faces_shop_mapping_is_valid_for_the_importer() -> None:
    mapping = ImportMapping.model_validate(mapping_for(SHOPS["faces_ae"]))
    assert (mapping.source.name, mapping.country, mapping.currency) == ("faces_ae", "AE", "AED")
    assert mapping.columns.observed_at == "observed_at"
    assert mapping.observed_at is None
    assert not mapping.complete_catalogue  # partial: a page not seen is never a removal
    assert mapping.columns.availability == "availability"


def _flag(in_stock: JsonValue) -> Reading:
    return r(
        "structured_data",
        {"item_in_stock": in_stock},
        path="dataLayer.view_item.items[0].item_in_stock",
    )


@pytest.mark.parametrize(
    ("statements", "expected"),
    [
        ((_flag(True),), "instock"),
        ((_flag(False),), "outofstock"),
        ((_markup("http://schema.org/InStock"), _flag(True)), "instock"),
        ((_markup("http://schema.org/OutOfStock"), _flag(False)), "outofstock"),
        # the page contradicts itself: unknown, never in or out of stock
        ((_markup("http://schema.org/InStock"), _flag(False)), None),
        ((_markup("http://schema.org/OutOfStock"), _flag(True)), None),
        # a flag that is present but not a boolean makes the page's stock unknown
        ((_flag("true"),), None),
        ((_markup("http://schema.org/InStock"), _flag(1)), None),
        ((_markup("http://schema.org/InStock"), _flag(0)), None),
        ((_markup("http://schema.org/InStock"), _flag("false")), None),
        ((_markup("http://schema.org/InStock"), _flag(None)), None),
    ],
)
def test_the_datalayer_stock_flag_must_agree_with_the_markup(
    make_capture: CaptureFactory, statements: tuple[Reading, ...], expected: str | None
) -> None:
    result = build_feed([page(make_capture, *statements)], SHOPS["faces_ae"])
    assert result.rows[0].get("availability") == expected


def test_a_non_boolean_flag_is_counted_as_unmapped(make_capture: CaptureFactory) -> None:
    capture = page(make_capture, _markup("http://schema.org/InStock"), _flag("false"))
    result = build_feed([capture], SHOPS["faces_ae"])
    assert result.report()["unmapped_availability"] == {"item_in_stock='false'": 1}


def test_a_numeric_key_is_written_as_text_and_an_image_list_of_blanks_is_skipped(
    make_capture: CaptureFactory,
) -> None:
    capture = make_capture(readings=(r("retailer_sku", 712845), r("image_urls", ["  "])))
    (row,) = build_feed([capture], SHOP).rows
    assert row["listing_key"] == "712845"
    assert "image_url" not in row


def _content_page(make_capture: CaptureFactory) -> ProductCapture:
    return page(
        make_capture,
        r("price_minor", 12000, currency="AED"),
        r("description", "  A warm amber eau de parfum.  "),
        r("department", "women"),
        r("concentration", "edp"),
        r("badges", ["new", " ", "onlineexclusive", "new"]),
        r("gift_with_purchase", "Free Gifts"),
        r("image_urls", [" ", "https://img.example/1.jpg", "https://img.example/2.jpg"]),
    )


def test_page_content_columns_come_from_observed_readings(make_capture: CaptureFactory) -> None:
    result = build_feed([_content_page(make_capture)], SHOP)
    (row,) = result.rows
    assert row["description"] == "A warm amber eau de parfum."
    assert (row["gender"], row["concentration"]) == ("women", "edp")
    assert row["badges"] == ["new", "onlineexclusive"]
    assert row["promotions"] == ["Free Gifts"]
    assert row["image_urls"] == ["https://img.example/1.jpg", "https://img.example/2.jpg"]
    assert row["image_url"] == "https://img.example/1.jpg"
    filled = result.report()["filled"]
    assert (filled["description"], filled["badges"], filled["image_urls"]) == (1, 1, 1)


def test_page_content_is_left_out_unless_observed(make_capture: CaptureFactory) -> None:
    capture = page(
        make_capture,
        r("description", state="not_shown"),
        r("department", state="parse_failed"),
        r("badges", []),
        r("image_urls", state="not_shown"),
    )
    (row,) = build_feed([capture], SHOP).rows
    for column in ("description", "gender", "concentration", "badges", "promotions", "image_urls"):
        assert column not in row
    assert "image_url" not in row


def test_page_content_validates_in_the_importer(
    tmp_path: Path, make_capture: CaptureFactory
) -> None:
    report = _validate(tmp_path, [_content_page(make_capture)])
    assert (report["rows"], report["accepted"], report["rejected"]) == (1, 1, [])
    assert [w for w in report["warnings"] if w["listing_key"] is not None] == []
