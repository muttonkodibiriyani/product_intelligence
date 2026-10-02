"""Generic extractors on synthetic HTML."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pi_capture.generic import (
    find_json_objects,
    generic_facts,
    jsonld_blocks,
    meta_tags,
    meta_tags_all,
    microdata_items,
    next_data,
    parse_jsonld,
    readings_from_generic,
    rsc_chunks,
    rsc_text,
)
from pi_capture.model import Reading


def _by_key(readings: list[Reading]) -> dict[str, Reading]:
    out: dict[str, Reading] = {}
    for r in readings:
        out.setdefault(r.key, r)
    return out


def test_readings_from_a_full_product_page(product_html: str) -> None:
    readings = readings_from_generic(
        product_html, locale="en-AE", url="https://shop.example/en/p/foundation-240?utm=x"
    )
    r = _by_key(readings)
    assert r["title"].value == "Radiant Foundation 240"
    assert r["title"].raw_text == "Radiant Foundation 240"
    assert r["title"].source_path == "jsonld[0].name"
    assert r["brand"].value == "Glow"
    assert r["description"].value == "A buildable foundation."
    assert r["image_urls"].value == ["https://img.example/a.jpg", "https://img.example/b.jpg"]
    assert r["image_count"].value == 2
    assert r["retailer_sku"].value == "SEP-11029384"
    assert r["gtin"].value == "03614273661096"
    assert r["gtin"].raw_text == "3614273661096"
    assert r["mpn"].value == "T3-240-30"
    assert r["price_minor"].value == 18900
    assert r["price_minor"].raw_text == "189.00 AED"
    assert r["price_minor"].note == "currency=AED"
    assert r["regular_price_minor"].value == 22900
    assert r["rating_value"].value == Decimal("4.3")
    assert r["rating_count"].value == 214
    assert r["breadcrumb"].value == ["Beauty", "Face", "Foundation"]
    assert r["canonical_url"].value == "https://shop.example/en/p/foundation-240"
    assert r["listing_id"].value == "/en/p/foundation-240"
    assert r["page_url"].value == "https://shop.example/en/p/foundation-240?utm=x"
    assert r["page_language"].value == "en-AE"
    assert r["language"].value == "en"
    assert r["structured_data"].state == "observed"
    assert isinstance(r["structured_data"].value, list)
    assert len(r["structured_data"].value) == 2
    assert all(x.state == "observed" for x in readings)
    assert len({(x.key, x.source_path) for x in readings}) == len(readings)
    facts = generic_facts(product_html)
    assert facts.availability == "https://schema.org/InStock"
    assert facts.seller == "Example Shop"
    assert facts.currency == "AED"
    assert facts.og_type == "product"
    assert facts.og_locale == "en_AE"


def test_opengraph_fills_gaps_and_page_level_fallbacks() -> None:
    html = """<html><head>
    <meta property="og:title" content="OG Only">
    <meta property="og:description" content="OG desc">
    <meta property="og:brand" content="OGBrand">
    <meta property="og:image" content="https://img.example/1.jpg">
    <meta property="og:image" content="https://img.example/2.jpg">
    <meta property="og:video" content="https://v.example/1.mp4">
    <meta property="product:price:amount" content="12.500">
    <meta property="product:price:currency" content="KWD">
    <meta property="product:availability" content="instock">
    <meta property="og:url" content="https://shop.example/ar/p/x">
    <meta property="og:locale" content="ar_KW">
    </head></html>"""
    r = _by_key(readings_from_generic(html, locale="ar-KW"))
    assert r["title"].value == "OG Only"
    assert r["title"].source_path == "meta[og:title]"
    assert r["description"].value == "OG desc"
    assert r["brand"].value == "OGBrand"
    assert r["image_urls"].value == ["https://img.example/1.jpg", "https://img.example/2.jpg"]
    assert r["image_count"].value == 2
    assert r["has_video"].value is True
    assert r["price_minor"].value == 12500
    assert r["canonical_url"].value == "https://shop.example/ar/p/x"
    assert r["listing_id"].value == "/ar/p/x"
    assert r["page_language"].value == "ar_KW"
    assert r["language"].value == "ar"
    assert "structured_data" not in r
    assert "page_url" not in r
    facts = generic_facts(html)
    assert facts.availability == "instock"
    assert facts.price == "12.500"


def test_minor_units_respect_the_currency_exponent() -> None:
    def page(price: str, currency: str | None) -> str:
        cur = f', "priceCurrency": "{currency}"' if currency else ""
        return (
            '<script type="application/ld+json">{"@type": "Product", "name": "P", '
            f'"offers": {{"@type": "Offer", "price": "{price}"{cur}}}}}</script>'
        )

    assert (
        _by_key(readings_from_generic(page("12.500", "KWD"), locale="ar-KW"))["price_minor"].value
        == 12500
    )
    assert (
        _by_key(readings_from_generic(page("12.5", "AED"), locale="en-AE"))["price_minor"].value
        == 1250
    )
    assert (
        _by_key(readings_from_generic(page("1,299", "SAR"), locale="ar-SA"))["price_minor"].value
        == 129900
    )
    too_fine = _by_key(readings_from_generic(page("12.505", "AED"), locale="en-AE"))["price_minor"]
    assert too_fine.state == "parse_failed"
    assert too_fine.raw_text == "12.505 AED"
    assert too_fine.note == "more decimals than AED allows"
    no_cur = _by_key(readings_from_generic(page("12.50", None), locale="en-AE"))["price_minor"]
    assert no_cur.state == "parse_failed"
    assert no_cur.raw_text == "12.50"
    unknown = _by_key(readings_from_generic(page("12.50", "XXX"), locale="en-AE"))["price_minor"]
    assert unknown.state == "parse_failed"
    assert "unknown currency" in (unknown.note or "")
    nan = _by_key(readings_from_generic(page("free", "AED"), locale="en-AE"))["price_minor"]
    assert nan.state == "parse_failed"


def test_parse_failures_keep_raw_text() -> None:
    html = """<html lang="fr"><head>
    <script type="application/ld+json">{"@type": "Product", "name": "P", "gtin": "ABC-123",
      "aggregateRating": {"ratingValue": "four", "ratingCount": "many"},
      "offers": {"@type": "AggregateOffer", "lowPrice": "10", "priceCurrency": "AED",
                 "offerCount": "seven",
                 "offers": [{"@type": "Offer", "price": "11", "priceCurrency": "AED"}]}}
    </script>
    <script type="application/ld+json">{oops</script>
    <script type="application/ld+json">"just a string"</script>
    <script type="application/ld+json">{"@type": "BreadcrumbList",
      "itemListElement": [{"@type": "ListItem"}]}</script>
    </head></html>"""
    readings = readings_from_generic(html, locale="en-AE")
    r = _by_key(readings)
    assert r["gtin"].state == "parse_failed"
    assert r["gtin"].raw_text == "ABC-123"
    assert r["rating_value"].state == "parse_failed"
    assert r["rating_count"].state == "parse_failed"
    assert r["offer_count"].state == "parse_failed"
    assert r["price_minor"].value == 1100
    assert r["price_minor"].source_path == "jsonld[0].offers[0].price"
    assert r["language"].state == "parse_failed"
    assert r["language"].raw_text == "fr"
    assert r["page_language"].value == "fr"
    assert r["breadcrumb"].state == "parse_failed"
    failed = [x for x in readings if x.key == "structured_data" and x.state == "parse_failed"]
    assert [f.raw_text for f in failed] == ["{oops", '"just a string"']
    assert [f.source_path for f in failed] == ["jsonld.failed[0]", "jsonld.failed[1]"]
    blocks, failed_texts = parse_jsonld(html)
    assert len(blocks) == 2
    assert len(failed_texts) == 2


def test_graph_and_array_blocks_and_offer_count() -> None:
    html = """<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
      {"@type": "WebSite", "name": "Shop"},
      {"@type": ["Product", "Thing"], "name": "Graph Product", "brand": "Plain Brand",
       "image": "https://img.example/one.jpg", "video": {"@type": "VideoObject"},
       "offers": {"@type": "AggregateOffer", "lowPrice": "99", "priceCurrency": "AED",
                  "offerCount": 7}}
    ]}</script>
    <script type="application/ld+json">[{"@type": "Organization", "name": "X"}, 3]</script>"""
    r = _by_key(readings_from_generic(html, locale="en-AE"))
    assert r["title"].value == "Graph Product"
    assert r["title"].source_path == "jsonld[0].@graph[1].name"
    assert r["brand"].value == "Plain Brand"
    assert r["image_urls"].value == ["https://img.example/one.jpg"]
    assert r["has_video"].value is True
    assert r["price_minor"].value == 9900
    assert r["price_minor"].source_path == "jsonld[0].@graph[1].offers[0].lowPrice"
    assert r["offer_count"].value == 7
    assert len(jsonld_blocks(html)) == 2


def test_microdata_product_maps_when_no_jsonld() -> None:
    html = """<html lang="en"><body>
    <div itemscope itemtype="https://schema.org/Product">
      <h1 itemprop="name">Micro <b>Name</b></h1>
      <img itemprop="image" src="https://img.example/m1.jpg">
      <img itemprop="image" src="https://img.example/m2.jpg">
      <a itemprop="url" href="/p/m">link</a>
      <time itemprop="releaseDate" datetime="2026-01-01">Jan</time>
      <data itemprop="sku" value="M-1">M one</data>
      <div itemprop="brand" itemscope itemtype="https://schema.org/Brand">
        <span itemprop="name">MB</span></div>
      <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
        <meta itemprop="priceCurrency" content="BHD"><span itemprop="price">1.250</span>
        <link itemprop="availability" href="https://schema.org/OutOfStock">
      </div>
    </div>
    <div itemscope itemtype="https://schema.org/Organization"><span itemprop="name">Org</span></div>
    </body></html>"""
    items = microdata_items(html)
    assert len(items) == 2
    product = items[0]
    assert product["name"] == ["Micro Name"]
    assert product["image"] == ["https://img.example/m1.jpg", "https://img.example/m2.jpg"]
    assert product["url"] == ["/p/m"]
    assert product["releaseDate"] == ["2026-01-01"]
    assert product["sku"] == ["M-1"]
    assert product["brand"][0]["name"] == ["MB"]
    assert product["offers"][0]["price"] == ["1.250"]
    assert product["offers"][0]["availability"] == ["https://schema.org/OutOfStock"]
    r = _by_key(readings_from_generic(html, locale="en-BH"))
    assert r["title"].value == "Micro Name"
    assert r["title"].source_path == "microdata.name"
    assert r["brand"].value == "MB"
    assert r["retailer_sku"].value == "M-1"
    assert r["image_count"].value == 2
    assert r["price_minor"].value == 1250
    assert generic_facts(html).availability == "https://schema.org/OutOfStock"
    assert "priceCurrency" not in meta_tags(html)


def test_meta_tags_keys(product_html: str) -> None:
    tags = meta_tags(product_html)
    assert tags["canonical"] == "https://shop.example/en/p/foundation-240"
    assert tags["hreflang:ar-ae"] == "https://shop.example/ar/p/foundation-240"
    assert tags["html:lang"] == "en-AE"
    assert tags["title"] == "Radiant Foundation 240 | Example Shop"
    assert tags["og:image"] == "https://img.example/og1.jpg"
    assert tags["description"] == "Meta description"
    assert meta_tags_all(product_html)["og:image"] == [
        "https://img.example/og1.jpg",
        "https://img.example/og2.jpg",
    ]
    assert meta_tags("<html></html>") == {}
    assert meta_tags('<link rel="canonical"><meta name="x">') == {}


def test_next_data() -> None:
    assert next_data("<html></html>") is None
    html = '<script id="__NEXT_DATA__" type="application/json">{"props": {"p": 1.25}}</script>'
    assert next_data(html) == {"props": {"p": Decimal("1.25")}}
    with pytest.raises(ValueError, match="Expecting"):
        next_data('<script id="__NEXT_DATA__">{broken</script>')
    with pytest.raises(ValueError, match="not a JSON object"):
        next_data('<script id="__NEXT_DATA__">[1, 2]</script>')


def test_rsc_chunks_decode_js_string_literals() -> None:
    html = r"""<script>self.__next_f.push([0])</script>
    <script>self.__next_f.push([1,"a:{\"sku\":\"X1\",\"price\":12.5,\"t\":\"tab\\there\"}\n"])</script>
    <script>self.__next_f.push([1, "b:{\"sku\":\"X2\",\"name\":\"😀 café \x41 it\'s\"}"])</script>
    <script type="application/json">self.__next_f.push([1,"ignored"])</script>"""
    chunks = rsc_chunks(html)
    assert len(chunks) == 2
    text = rsc_text(html)
    assert text.startswith('a:{"sku":"X1"')
    assert "😀 café A it's" in text
    assert "\\t" in chunks[0]  # the JSON escape survives JS decoding; json loads it as a tab
    assert rsc_text("<html></html>") == ""
    objects = find_json_objects(text, "sku")
    assert objects == [
        {"sku": "X1", "price": Decimal("12.5"), "t": "tab\there"},
        {"sku": "X2", "name": "😀 café A it's"},
    ]


def test_find_json_objects_takes_the_innermost_object_and_skips_junk() -> None:
    text = 'x {"outer": {"sku": "A", "n": 1}, "sku": "B"} {"sku": broken} {"sku": "C"}'
    assert find_json_objects(text, "sku") == [
        {"sku": "A", "n": 1},
        {"outer": {"sku": "A", "n": 1}, "sku": "B"},
        {"sku": "C"},
    ]
    assert find_json_objects("no braces here", "sku") == []
    assert find_json_objects('"sku": 1', "sku") == []


def test_microdata_scope_without_type_is_ignored() -> None:
    """Faces pages carry ``itemscope`` elements with no ``itemtype``: skip them, do not crash."""
    html = (
        '<html><body><div itemscope><span itemprop="name">x</span></div>'
        '<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Lipstick</span>'
        '<span itemprop="brand">Brand</span></div></body></html>'
    )
    readings = readings_from_generic(html, locale="en-AE")
    assert any(r.key == "title" and r.value == "Lipstick" for r in readings)
