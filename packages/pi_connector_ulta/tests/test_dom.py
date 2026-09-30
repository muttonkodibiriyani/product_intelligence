"""DOM + JSON-LD parser on trimmed real ulta.ae captures (2026-09-30)."""

from decimal import Decimal
from pathlib import Path

import pytest

from pi_connector_ulta.catalog import CatalogError, parse_pdp_payload
from pi_connector_ulta.dom import merge_page_json, parse_pdp_html, parse_plp_html

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_configurable_pdp_en() -> None:
    p = parse_pdp_html(_read("ulta_ae_pdp_en_morphe_trio.html"), "en")
    assert (p.sku, p.name, p.brand, p.brand_key) == (
        "PF0000089742",
        "Cheek Thrills Multi-Finish Face Trio",
        "Morphe",
        "morphe",
    )
    assert p.url_key == "buy-cheek-thrills-multi-finish-face-trio"
    assert p.category_path == "Makeup & Nails|Face|Blush"
    assert p.rating_count == 198
    assert p.rating_average is not None
    assert len(p.variants) == 7
    stock = {v.shade: v.in_stock for v in p.variants}
    assert stock["Beach Bonfire"] is True
    assert stock["Après-Ski"] is False
    selected = [v for v in p.variants if v.final.amount is not None]
    assert [(v.sku, v.final.amount) for v in selected] == [("345530690", Decimal("81.00"))]
    assert selected[0].images
    assert all("?" not in u for u in selected[0].images)
    assert selected[0].size is None  # the page shows "NOSIZE"


def test_unselected_variant_prices_are_unknown_not_copied() -> None:
    p = parse_pdp_html(_read("ulta_ae_pdp_en_kylie_tint.html"), "en")
    others = [v for v in p.variants if v.sku != "346725332"]
    assert len(others) == 11
    assert all(v.final.amount is None and v.final.reason == "unknown" for v in others)
    assert all(v.barcode is None for v in p.variants)  # EAN is not in the DOM
    assert p.rating_count is None  # no reviews yet: absent, never 0


def test_arabic_page_shares_skus_and_brand_key() -> None:
    en = parse_pdp_html(_read("ulta_ae_pdp_en_morphe_trio.html"), "en")
    ar = parse_pdp_html(_read("ulta_ae_pdp_ar_morphe_trio.html"), "ar")
    assert ar.locale == "ar"
    assert ar.brand_key == en.brand_key == "morphe"
    assert ar.brand != en.brand
    assert [v.sku for v in ar.variants] == [v.sku for v in en.variants]
    assert [v.in_stock for v in ar.variants] == [v.in_stock for v in en.variants]


def test_page_json_fills_only_dom_gaps() -> None:
    dom = parse_pdp_html(_read("ulta_ae_pdp_en_kylie_tint.html"), "en")
    (page_json,) = parse_pdp_payload(_read("ulta_ae_page_json_kylie_tint.json"), "en")
    merged = merge_page_json(dom, page_json)
    by_sku = {v.sku: v for v in merged.variants}
    assert by_sku["346725332"].final.amount == Decimal("160.00")  # DOM value kept
    assert by_sku["346900338"].final.amount == Decimal("155")  # filled from page JSON
    assert all(v.barcode for v in merged.variants)
    assert [v.in_stock for v in merged.variants] == [v.in_stock for v in dom.variants]


def test_page_json_for_another_product_is_ignored() -> None:
    dom = parse_pdp_html(_read("ulta_ae_pdp_en_morphe_trio.html"), "en")
    (page_json,) = parse_pdp_payload(_read("ulta_ae_page_json_kylie_tint.json"), "en")
    assert merge_page_json(dom, page_json) is dom


@pytest.mark.parametrize(
    "document", ["", "<html><body><h1>Attention Required! | Cloudflare</h1></body></html>"]
)
def test_block_or_empty_page_is_not_a_product(document: str) -> None:
    with pytest.raises(CatalogError):
        parse_pdp_html(document, "en")


def test_free_gift_placeholder_price_is_not_applicable() -> None:
    page = _read("ulta_ae_pdp_en_kylie_tint.html").replace("&nbsp;160.00", "&nbsp;0.00")
    selected = next(v for v in parse_pdp_html(page, "en").variants if v.sku == "346725332")
    assert selected.final.amount is None
    assert selected.final.reason == "not_applicable"
    assert selected.free_gift


def test_plp_tiles() -> None:
    hits = parse_plp_html(_read("ulta_ae_plp_en_makeup.html"), "en")
    first = hits[0]
    assert (first.sku, first.brand, first.url_path) == (
        "PF0000091796",
        "SACHEU",
        "/en/buy-liquid-contour-stay-n",
    )
    assert first.final_price.amount == Decimal("38.50")
    assert first.original_price.amount == Decimal("77.00")
    assert (first.rating_average, first.rating_count) == (Decimal("3.3"), 23)
