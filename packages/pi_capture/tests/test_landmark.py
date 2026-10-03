"""Landmark extractor on synthetic Next.js-shaped HTML. No real retailer page is used here."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_capture.generic import LOOKED_FOR as GENERIC_LOOKED_FOR
from pi_capture.landmark import (
    LOOKED_FOR,
    LandmarkPageError,
    _gs1_check_ok,
    landmark_product,
    readings_from_landmark,
)
from pi_capture.model import Reading
from pi_capture.registry import ATTRIBUTES

_JSONLD = (
    '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
    '"name":"JSON-LD name","sku":"JSONLD-SKU","offers":{"@type":"Offer","price":"145",'
    '"priceCurrency":"AED","availability":"https://schema.org/InStock"}}</script>'
)


def _price(now: Any, was: Any, currency: str = "AED", was_currency: str = "AED") -> Any:
    return {
        "target": {"priceableFields": {"basePrice": {"amount": was, "currency": was_currency}}},
        "price": {"amount": now, "currency": currency},
    }


def _product(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "sku": "STYLE-1",
        "name": "Strappy Sandal",
        "brand": {"displayValue": "Brandy", "value": "BRANDY"},
        "description": "Soft <b>satin</b>&amp; buckle.</br>Evening wear.",
        "breadcrumbs": [
            {"label": "Women", "uri": "/women"},
            {"label": "Shoes", "uri": "/women-shoes"},
            {"label": "Sandals", "uri": "/women-shoes-sandals"},
            {"label": "Heeled", "uri": "/women-shoes-sandals-heeled"},
            {"label": "Stiletto", "uri": "/women-shoes-sandals-heeled-stiletto"},
            {"label": "Strappy Sandal"},
        ],
        "options": [
            {
                "attributeChoice": {
                    "attributeName": "Color",
                    "allowedValues": [
                        {"label": "Pink", "value": "C1-Pink"},
                        {"label": "Black", "value": "C1-Black"},
                    ],
                }
            },
            {"attributeChoice": {"attributeName": "Size", "allowedValues": [{"value": "35"}]}},
        ],
        "assets": [
            {"tags": ["color:c1-pink"], "contentUrl": "https://img.example/pink-1.jpg"},
            {"tags": ["color:c1-pink"], "contentUrl": "https://img.example/pink-2.jpg"},
            {"tags": ["color:c1-black"], "contentUrl": "https://img.example/black-1.jpg"},
        ],
        "priceInfo": _price(145, 145),
        "variants": [
            {
                "sku": "100001",
                "externalId": "5059957051226",
                "optionValues": {"Size": "35", "Color": "C1-Pink"},
                "priceInfo": _price(87, 145),
            },
            {
                "sku": "100002",
                "externalId": "4006381333931",
                "optionValues": {"Size": "36", "Color": "C1-Black"},
                "priceInfo": _price(145, 145),
            },
        ],
    }
    data.update(over)
    return data


def _page(data: Any, *, encode: bool = True, extra: str = _JSONLD) -> str:
    state = {"productPageReducerBL": {"data": data}, "otherReducer": {}}
    initial: Any = base64.b64encode(json.dumps(state).encode()).decode() if encode else state
    nd = json.dumps({"props": {"initialState": initial}, "page": "/p"})
    return (
        '<!doctype html><html lang="en"><head><title>t</title>'
        '<link rel="canonical" href="https://shop.example/ae/en/p/C1-Pink">'
        f'{extra}</head><body><script id="__NEXT_DATA__" type="application/json">{nd}</script>'
        "</body></html>"
    )


def _by_key(readings: list[Reading]) -> dict[str, Reading]:
    keys = [r.key for r in readings]
    assert len(keys) == len(set(keys)), "one reading per key"
    return {r.key: r for r in readings}


def test_one_reading_list_per_variant_with_variant_prices() -> None:
    pink, black = (_by_key(rs) for rs in readings_from_landmark(_page(_product()), locale="en"))
    assert pink["retailer_sku"].value == "100001"
    assert pink["gtin"].value == "05059957051226"
    assert pink["size_label"].value == "35"
    assert pink["colour_code"].value == "C1-Pink"
    assert pink["colour_name"].value == "Pink"
    # the variant's sale price, not the base price JSON-LD shows
    assert (pink["price_minor"].value, pink["price_minor"].currency) == (8700, "AED")
    assert (pink["regular_price_minor"].value, pink["regular_price_minor"].currency) == (
        14500,
        "AED",
    )
    assert pink["image_urls"].value == [
        "https://img.example/pink-1.jpg",
        "https://img.example/pink-2.jpg",
    ]
    assert pink["image_count"].value == 2
    assert black["image_urls"].value == ["https://img.example/black-1.jpg"]
    assert black["price_minor"].value == 14500
    assert black["regular_price_minor"].state == "not_shown"
    assert black["regular_price_minor"].value is None


def test_product_level_readings_repeat_on_every_variant() -> None:
    for rs in readings_from_landmark(_page(_product()), locale="en"):
        r = _by_key(rs)
        assert r["title"].value == "Strappy Sandal"  # not the JSON-LD name
        assert r["brand"].value == "Brandy"
        assert r["breadcrumb"].value == ["Women", "Shoes", "Sandals", "Heeled", "Stiletto"]
        assert r["category_l1..l4"].value == ["Women", "Shoes", "Sandals", "Heeled"]
        assert r["style_id"].value == "STYLE-1"
        assert r["style_id_source"].value == "captured"
        assert r["description"].value == "Soft satin & buckle. Evening wear."
        assert r["description"].raw_text == "Soft <b>satin</b>&amp; buckle.</br>Evening wear."
        # generic readers fill page-level keys this module does not read
        assert r["canonical_url"].value == "https://shop.example/ae/en/p/C1-Pink"
        assert r["structured_data"].state == "observed"


def test_single_sku_product_is_read_from_the_product_block() -> None:
    data = _product(variants=[], priceInfo=_price(156, 230), assets=[])
    (only,) = readings_from_landmark(_page(data), locale="en")
    r = _by_key(only)
    assert r["retailer_sku"].value == "STYLE-1"
    assert r["gtin"].state == "not_shown"
    assert r["price_minor"].value == 15600
    assert r["regular_price_minor"].value == 23000
    assert "size_label" not in r
    assert "colour_code" not in r
    assert "image_urls" not in r  # no assets, and the JSON-LD here carries no image either


def test_untagged_assets_fall_back_to_every_asset_with_a_note() -> None:
    data = _product(
        assets=[{"tags": [], "contentUrl": "https://img.example/a.jpg"}, {"contentUrl": ""}]
    )
    first = _by_key(readings_from_landmark(_page(data), locale="en")[0])
    assert first["image_urls"].value == ["https://img.example/a.jpg"]
    assert first["image_urls"].note == "no asset tagged with this colour; all product assets"


def test_initial_state_may_be_a_plain_object() -> None:
    rows = readings_from_landmark(_page(_product(), encode=False), locale="en")
    assert len(rows) == 2


@pytest.mark.parametrize(
    ("external_id", "state", "note"),
    [
        (None, "not_shown", "variant carries no externalId"),
        ("0", "not_shown", "externalId is '0': the shop records no barcode"),
        ("12345", "parse_failed", "externalId is not an 8/12/13/14 digit barcode"),
        ("ABCDEFGHIJKLM", "parse_failed", "externalId is not an 8/12/13/14 digit barcode"),
        ("5059957051227", "parse_failed", "externalId fails the GS1 check digit"),
        ("96385074", "observed", "padded to 14 digits"),
        (6292798899858, "observed", "padded to 14 digits"),
    ],
)
def test_gtin_states(external_id: Any, state: str, note: str) -> None:
    variant = {"sku": "1", "externalId": external_id, "priceInfo": _price(10, 10)}
    r = _by_key(readings_from_landmark(_page(_product(variants=[variant])), locale="en")[0])
    assert (r["gtin"].state, r["gtin"].note) == (state, note)


def test_missing_price_is_explicit_and_json_ld_price_is_not_used() -> None:
    variant = {"sku": "1", "priceInfo": {}}
    r = _by_key(readings_from_landmark(_page(_product(variants=[variant])), locale="en")[0])
    assert r["price_minor"].state == "not_shown"
    assert r["regular_price_minor"].state == "not_shown"


def test_missing_base_price_is_explicit() -> None:
    variant = {"sku": "1", "priceInfo": {"price": {"amount": 10, "currency": "AED"}}}
    r = _by_key(readings_from_landmark(_page(_product(variants=[variant])), locale="en")[0])
    assert r["price_minor"].value == 1000
    assert r["regular_price_minor"].state == "not_shown"
    assert r["regular_price_minor"].note == "variant price block carries no basePrice"


def test_base_price_in_another_currency_is_refused() -> None:
    variant = {"sku": "1", "priceInfo": _price(10, 20, was_currency="USD")}
    r = _by_key(readings_from_landmark(_page(_product(variants=[variant])), locale="en")[0])
    assert r["regular_price_minor"].state == "parse_failed"
    assert r["regular_price_minor"].currency == "USD"


def test_fractional_and_three_decimal_prices_stay_exact() -> None:
    variants = [
        {"sku": "1", "priceInfo": _price("12.5", "20.25")},
        {"sku": "2", "priceInfo": _price("1.234", "2.5", currency="KWD", was_currency="KWD")},
    ]
    aed, kwd = (
        _by_key(rs)
        for rs in readings_from_landmark(_page(_product(variants=variants)), locale="en")
    )
    assert (aed["price_minor"].value, aed["regular_price_minor"].value) == (1250, 2025)
    assert (kwd["price_minor"].value, kwd["regular_price_minor"].value) == (1234, 2500)
    assert kwd["price_minor"].currency == "KWD"


def test_unreadable_price_is_parse_failed() -> None:
    variant = {"sku": "1", "priceInfo": _price("abc", "20")}
    r = _by_key(readings_from_landmark(_page(_product(variants=[variant])), locale="en")[0])
    assert r["price_minor"].state == "parse_failed"
    assert r["regular_price_minor"].value == 2000


def test_sparse_product_emits_only_what_it_has() -> None:
    data = {"variants": [{"optionValues": "not a mapping", "priceInfo": _price(5, 5)}], "x": 1}
    r = _by_key(readings_from_landmark(_page(data, extra=""), locale="en")[0])
    assert r["retailer_sku"].state == "not_shown"
    for key in ("title", "brand", "breadcrumb", "style_id", "description", "colour_name"):
        assert key not in r


def test_colour_without_label_has_code_only() -> None:
    variant = {"sku": "1", "optionValues": {"Color": "C9-Teal"}, "priceInfo": _price(5, 5)}
    r = _by_key(readings_from_landmark(_page(_product(variants=[variant])), locale="en")[0])
    assert r["colour_code"].value == "C9-Teal"
    assert "colour_name" not in r


@pytest.mark.parametrize(
    ("html", "reason"),
    [
        ("<html><body>no data</body></html>", "no __NEXT_DATA__ script"),
        (
            '<script id="__NEXT_DATA__">{"props":{"initialState":"%%%"}}</script>',
            "initialState is not base64 JSON",
        ),
        ('<script id="__NEXT_DATA__">{"props":[]}</script>', "no initialState object"),
        (
            '<script id="__NEXT_DATA__">{"props":{"initialState":{"other":{}}}}</script>',
            "no productPageReducerBL.data",
        ),
    ],
)
def test_non_landmark_pages_raise_with_the_reason(html: str, reason: str) -> None:
    with pytest.raises(LandmarkPageError, match=reason):
        readings_from_landmark(html, locale="en")


def test_numbers_decode_without_floats() -> None:
    data = landmark_product(_page(_product(variants=[{"sku": "1", "priceInfo": _price(1.5, 2)}])))
    amount = data["variants"][0]["priceInfo"]["price"]["amount"]
    assert not isinstance(amount, float)


def test_every_emitted_key_is_registered_and_looked_for() -> None:
    assert GENERIC_LOOKED_FOR <= LOOKED_FOR
    assert {a.key for a in ATTRIBUTES} >= LOOKED_FOR
    for rs in readings_from_landmark(_page(_product()), locale="en"):
        for r in rs:
            assert r.key in LOOKED_FOR


def _check_digit(body: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


@given(
    st.sampled_from([7, 11, 12, 13]).flatmap(
        lambda n: st.text("0123456789", min_size=n, max_size=n)
    )
)
def test_gs1_check_digit_accepts_exactly_the_right_digit(body: str) -> None:
    good = _check_digit(body)
    for d in "0123456789":
        assert _gs1_check_ok(body + d) is (d == good)
