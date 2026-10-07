"""Bloomingdale's UAE reader. Synthetic pages only, shaped like the storefront's ``productData``
record; no real retailer page is used."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from pi_capture.bloomingdales import LOOKED_FOR, readings_from_bloomingdales
from pi_capture.feed import SHOPS, build_feed
from pi_capture.model import ProductCapture, Reading
from pi_capture.page_json import NoProductObject, OutOfScopePage

CaptureFactory = Callable[..., ProductCapture]


def _sales(value: int, currency: str = "AED") -> dict[str, Any]:
    return {"value": value, "currency": currency}


def _product(**over: Any) -> dict[str, Any]:
    product: dict[str, Any] = {
        "id": "900000101",
        "master": {"masterId": "BEA900000100"},
        "name": " Hydra Gel Cleanser ",
        "c_brand": "Synthetic Lab",
        "c_barcode": "3000000000024",
        "c_rms_div": "Beauty",
        "c_rms_dept": "Skincare",
        "c_rms_class": "Cleansers And Exfoliators",
        "c_rms_subclass": "Face Wash",
        "c_rms_group": "Mens",
        "c_isBeauty": False,
        "c_price": {"sales": _sales(140), "list": None},
        "c_size": "200ml",
        "c_images": {
            "xlarge": [
                {"url": "https://img.example/b/900000101_IN.jpg"},
                {"url": "https://img.example/b/900000101_FR.jpg"},
            ]
        },
        "inventory": {"orderable": True, "ats": 3},
        "productPromotions": [{"promotionId": "GWP_SYNTH"}],
    }
    return product | over


def _page(product: dict[str, Any], availability: str | None = "InStock") -> str:
    offers = {"@type": "Offer", "price": 140, "priceCurrency": "AED"}
    if availability is not None:
        offers["availability"] = f"https://schema.org/{availability}"
    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "x",
        "description": "Cleans without drying.",
        "offers": offers,
    }
    query = json.dumps({"queries": [{"state": {"data": {"productData": product}}}]})
    return (
        '<html lang="en-AE"><head><script type="application/ld+json">'
        f"{json.dumps(ld)}</script></head><body><script>window.__Q__={query}</script>"
        "</body></html>"
    )


def _by_key(readings: list[Reading]) -> dict[str, Reading]:
    return {r.key: r for r in readings if r.key != "structured_data"}


def test_a_beauty_page_reads_identity_price_taxonomy_size_and_images() -> None:
    got = _by_key(readings_from_bloomingdales(_page(_product()), locale="en-AE"))
    assert got["retailer_sku"].value == "900000101"
    assert got["style_id"].value == "BEA900000100"
    assert (got["brand"].value, got["title"].value) == ("Synthetic Lab", "Hydra Gel Cleanser")
    assert got["gtin"].value == "03000000000024"
    assert (got["price_minor"].value, got["price_minor"].currency) == (14000, "AED")
    assert "regular_price_minor" not in got
    assert got["department"].value == "men"
    assert got["category_l1..l4"].value == [
        "Beauty",
        "Skincare",
        "Cleansers And Exfoliators",
        "Face Wash",
    ]
    assert (got["size_value"].value, got["size_unit"].value) == (Decimal(200), "ml")
    assert got["image_urls"].value == [
        "https://img.example/b/900000101_IN.jpg",
        "https://img.example/b/900000101_FR.jpg",
    ]
    assert got["description"].value == "Cleans without drying."  # from the JSON-LD
    assert "badges" not in got  # promotion ids are not shopper-facing labels
    assert "gift_with_purchase" not in got
    assert got["rating_count"].state == "not_shown"
    assert set(got) <= LOOKED_FOR


def test_a_liquid_size_is_used_when_there_is_no_size_and_a_concentration_is_read() -> None:
    product = _product(c_size=None, c_liquidSize="50 ml", c_rms_subclass="Eau De Parfum")
    got = _by_key(readings_from_bloomingdales(_page(product), locale="en-AE"))
    assert got["size_label"].source_path == "productData.c_liquidSize"
    assert got["concentration"].value == "edp"


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ({"sales": _sales(140), "list": _sales(200)}, ("observed", 20000)),
        ({"sales": _sales(140), "list": _sales(140)}, ("parse_failed", None)),
        ({"sales": _sales(140), "list": _sales(200, "USD")}, ("parse_failed", None)),
    ],
)
def test_a_list_price_counts_only_above_the_sale_price_in_the_same_currency(
    price: dict[str, Any], expected: tuple[str, int | None]
) -> None:
    got = _by_key(readings_from_bloomingdales(_page(_product(c_price=price)), locale="en-AE"))
    assert (got["regular_price_minor"].state, got["regular_price_minor"].value) == expected


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"c_rms_div": "Fashion"}, "c_rms_div 'Fashion', not Beauty"),
        ({"c_rms_dept": "Home"}, "c_rms_dept Home"),
    ],
)
def test_pages_outside_beauty_or_in_home_are_out_of_scope(
    over: dict[str, Any], reason: str
) -> None:
    with pytest.raises(OutOfScopePage, match=reason):
        readings_from_bloomingdales(_page(_product(**over)), locale="en-AE")


def test_a_page_without_product_data_is_not_a_product() -> None:
    with pytest.raises(NoProductObject):
        readings_from_bloomingdales("<html></html>", locale="en-AE")


@pytest.mark.parametrize(
    ("orderable", "availability", "expected"),
    [
        (True, "InStock", "instock"),
        (False, "OutOfStock", "outofstock"),
        (True, "OutOfStock", None),  # the page contradicts itself: unknown
        (..., "InStock", "instock"),  # no flag: the JSON-LD alone
        (None, "InStock", None),  # a flag that is not a boolean: unknown
        (1, "InStock", None),
    ],
)
def test_bloomingdales_rows_carry_the_stock_the_page_states(
    make_capture: CaptureFactory,
    orderable: object,
    availability: str,
    expected: str | None,
) -> None:
    inventory = {} if orderable is ... else {"orderable": orderable}
    html = _page(_product(inventory=inventory), availability)
    readings = readings_from_bloomingdales(html, locale="en-AE")
    capture = make_capture(readings=tuple(readings))
    (row,) = build_feed([capture], SHOPS["bloomingdales_ae"]).rows
    assert row.get("availability") == expected
    assert (row["listing_key"], row["price_current"]) == ("900000101", "140.00")
