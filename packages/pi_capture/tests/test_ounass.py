"""Ounass reader. Synthetic pages only, shaped like the storefront's ``pdp`` object; no real
retailer page is used."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from pi_capture.feed import SHOPS, build_feed
from pi_capture.model import ProductCapture, Reading
from pi_capture.ounass import LOOKED_FOR, readings_from_ounass
from pi_capture.page_json import NoProductObject, OutOfScopePage

CaptureFactory = Callable[..., ProductCapture]


def _pdp(**over: Any) -> dict[str, Any]:
    pdp: dict[str, Any] = {
        "division": "Beauty",
        "department": "Fragrance",
        "class": "Fragrance",
        "subClass": "Eau De Parfum",
        "gender": "Unisex",
        "styleColorId": "900000001_242",
        "parentSku": "900000001",
        "designerCategoryEnglishName": "Synthetic House",
        "name": "Cedar Note Eau de Parfum, 100ml  ",
        "nameInEnglish": "Cedar Note Eau de Parfum, 100ml",
        "barcode": "3000000000017",
        "priceInAED": 450,
        "badge": {"valueEn": "GIFT WITH PURCHASE"},
        "breadcrumbs": [{"name": "Women"}, {"name": "Beauty"}, {"name": "Fragrance"}],
        "sizes": [{"sku": "900000002", "sizeCode": "NO SIZE", "stock": 4}],
        "images": [
            {"oneX": "//img.example/p/900000001_in.jpg"},
            {"oneX": "//img.example/p/900000001_fr.jpg"},
            {"oneX": "//img.example/p/900000001_in.jpg"},
        ],
        "descriptionText": " A dry cedar scent. ",
        "outOfStock": False,
    }
    return pdp | over


def _page(pdp: dict[str, Any], availability: str | None = "InStock") -> str:
    offers = {"@type": "Offer", "price": 450, "priceCurrency": "AED"}
    if availability is not None:
        offers["availability"] = f"https://schema.org/{availability}"
    ld = {"@context": "https://schema.org", "@type": "Product", "name": "x", "offers": offers}
    state = json.dumps({"props": {"pageProps": {"pdp": pdp}}})
    return (
        '<html lang="en"><head><script type="application/ld+json">'
        f"{json.dumps(ld)}</script></head><body><script>window.__STATE__={state}</script>"
        "</body></html>"
    )


def _by_key(readings: list[Reading]) -> dict[str, Reading]:
    return {r.key: r for r in readings if r.key != "structured_data"}


def test_a_beauty_page_reads_identity_price_taxonomy_size_and_merch() -> None:
    got = _by_key(readings_from_ounass(_page(_pdp()), locale="en-AE"))
    assert got["retailer_sku"].value == "900000001_242"
    assert (got["style_id"].value, got["style_id_source"].value) == ("900000001", "captured")
    assert (got["brand"].value, got["title"].value) == (
        "Synthetic House",
        "Cedar Note Eau de Parfum, 100ml",
    )
    assert got["gtin"].value == "03000000000017"
    assert (got["price_minor"].value, got["price_minor"].currency) == (45000, "AED")
    assert "regular_price_minor" not in got
    assert got["department"].value == "unisex"
    assert got["category_l1..l4"].value == ["Beauty", "Fragrance", "Fragrance", "Eau De Parfum"]
    assert got["product_type"].value == "Eau De Parfum"
    assert got["breadcrumb"].value == ["Women", "Beauty", "Fragrance"]
    assert (got["size_value"].value, got["size_unit"].value) == (Decimal(100), "ml")
    assert "end of the name" in (got["size_label"].source_path or "")
    assert got["badges"].value == ["GIFT WITH PURCHASE"]
    assert got["gift_with_purchase"].value == "GIFT WITH PURCHASE"
    assert got["image_urls"].value == [
        "https://img.example/p/900000001_in.jpg",
        "https://img.example/p/900000001_fr.jpg",
    ]
    assert got["image_count"].value == 2
    assert got["description"].value == "A dry cedar scent."
    assert got["concentration"].value == "edp"
    assert got["rating_value"].state == "not_shown"
    assert set(got) <= LOOKED_FOR


def test_a_size_code_wins_over_the_name_and_a_multi_size_page_reads_no_size() -> None:
    one = _pdp(sizes=[{"sizeCode": "50ml", "stock": 1}])
    got = _by_key(readings_from_ounass(_page(one), locale="en-AE"))
    assert (got["size_label"].value, got["size_label"].source_path) == (
        "50ml",
        "pdp.sizes[0].sizeCode",
    )
    two = _pdp(sizes=[{"sizeCode": "50ml"}, {"sizeCode": "100ml"}])
    assert "size_label" not in _by_key(readings_from_ounass(_page(two), locale="en-AE"))


@pytest.mark.parametrize(
    ("struck", "expected"),
    [(600, ("observed", 60000)), (450, ("parse_failed", None)), (300, ("parse_failed", None))],
)
def test_a_struck_price_counts_only_above_the_sale_price(
    struck: int, expected: tuple[str, int | None]
) -> None:
    got = _by_key(readings_from_ounass(_page(_pdp(slashedPriceInAED=struck)), locale="en-AE"))
    assert (got["regular_price_minor"].state, got["regular_price_minor"].value) == expected


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"division": "Fashion"}, "division 'Fashion', not Beauty"),
        ({"department": "Home"}, "department Home"),
        ({"division": None}, "division None"),
    ],
)
def test_pages_outside_beauty_or_in_home_are_out_of_scope(
    over: dict[str, Any], reason: str
) -> None:
    with pytest.raises(OutOfScopePage, match=reason):
        readings_from_ounass(_page(_pdp(**over)), locale="en-AE")


def test_a_page_without_a_pdp_object_is_not_a_product() -> None:
    with pytest.raises(NoProductObject):
        readings_from_ounass("<html><body>no product</body></html>", locale="en-AE")


def test_the_out_of_stock_flag_is_its_own_structured_data_block() -> None:
    readings = readings_from_ounass(_page(_pdp(outOfStock=True), "OutOfStock"), locale="en-AE")
    blocks = [(r.source_path, r.value) for r in readings if r.key == "structured_data"]
    assert blocks[-1] == ("pdp.outOfStock", {"item_in_stock": False})
    assert blocks[0][0] == "jsonld"
    pdp = _pdp()
    del pdp["outOfStock"]
    no_flag = readings_from_ounass(_page(pdp), locale="en-AE")
    assert [r.source_path for r in no_flag if r.key == "structured_data"] == ["jsonld"]
    null = readings_from_ounass(_page(_pdp(outOfStock=None)), locale="en-AE")
    (block,) = [r for r in null if r.source_path == "pdp.outOfStock"]
    assert (block.raw_text, block.value) == ("null", {"item_in_stock": None})


@pytest.mark.parametrize(
    ("out_of_stock", "availability", "expected"),
    [
        (False, "InStock", "instock"),
        (True, "OutOfStock", "outofstock"),  # stays a row, published as out of stock
        (True, None, "outofstock"),
        (False, "OutOfStock", None),  # the page contradicts itself: unknown
        (None, "InStock", None),  # a flag that is not a boolean: unknown
        ("false", "InStock", None),
    ],
)
def test_ounass_rows_carry_the_stock_the_page_states(
    make_capture: CaptureFactory,
    out_of_stock: object,
    availability: str | None,
    expected: str | None,
) -> None:
    html = _page(_pdp(outOfStock=out_of_stock), availability)
    capture = make_capture(readings=tuple(readings_from_ounass(html, locale="en-AE")))
    result = build_feed([capture], SHOPS["ounass_ae"])
    (row,) = result.rows
    assert row.get("availability") == expected
    assert (row["listing_key"], row["price_current"]) == ("900000001_242", "450.00")
