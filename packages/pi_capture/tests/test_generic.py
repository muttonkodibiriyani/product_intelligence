"""Generic extractors on synthetic HTML."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from pi_capture.generic import (
    LOOKED_FOR,
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
from pi_capture.registry import ATTRIBUTES


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
    assert r["price_minor"].note is None
    assert r["price_minor"].currency == "AED"
    assert r["regular_price_minor"].currency == "AED"
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
    ambiguous = _by_key(readings_from_generic(page("1,299", "SAR"), locale="ar-SA"))["price_minor"]
    assert ambiguous.state == "parse_failed"
    assert ambiguous.currency == "SAR"
    assert "ambiguous" in (ambiguous.note or "")
    unclear = _by_key(readings_from_generic(page("12.505", "AED"), locale="en-AE"))["price_minor"]
    assert unclear.state == "parse_failed"
    assert unclear.raw_text == "12.505 AED"
    assert "ambiguous" in (unclear.note or "")
    too_fine = _by_key(readings_from_generic(page("1.299,505", "AED"), locale="en-AE"))[
        "price_minor"
    ]
    assert too_fine.state == "parse_failed"
    assert too_fine.note == "more decimals than AED allows"
    no_cur = _by_key(readings_from_generic(page("12.50", None), locale="en-AE"))["price_minor"]
    assert no_cur.state == "parse_failed"
    assert no_cur.raw_text == "12.50"
    unknown = _by_key(readings_from_generic(page("12.50", "XXX"), locale="en-AE"))["price_minor"]
    assert unknown.state == "parse_failed"
    assert "unknown currency" in (unknown.note or "")
    nan = _by_key(readings_from_generic(page("free", "AED"), locale="en-AE"))["price_minor"]
    assert nan.state == "parse_failed"


def _price(amount: str, currency: str) -> Reading:
    html = (
        '<script type="application/ld+json">{"@type": "Product", "name": "P", "offers": '
        f'{{"@type": "Offer", "price": "{amount}", "priceCurrency": "{currency}"}}}}</script>'
    )
    return _by_key(readings_from_generic(html, locale="en-AE"))["price_minor"]


@pytest.mark.parametrize(
    ("amount", "currency", "minor"),
    [
        ("12,50", "AED", 1250),  # decimal comma: was recorded as 125000
        ("12,5", "AED", 1250),
        ("1.299,00", "SAR", 129900),  # European grouping
        ("1,299.00", "SAR", 129900),  # English grouping
        ("1 299,50", "SAR", 129950),  # space grouping with decimal comma
        ("1\u00a0299.50", "SAR", 129950),  # no-break space grouping
        ("1,299,000", "SAR", 129900000),  # repeated comma can only be grouping
        ("12.500", "KWD", 12500),  # three minor places: '.' + 3 digits is the decimal mark
        ("12.500", "BHD", 12500),
        ("1.250", "OMR", 1250),
        ("1299", "SAR", 129900),
        ("12.", "AED", 1200),
        (".5", "AED", 50),
        ("+12.50", "AED", 1250),
    ],
)
def test_decimal_comma_and_grouping_are_read_explicitly(
    amount: str, currency: str, minor: int
) -> None:
    r = _price(amount, currency)
    assert (r.state, r.value, r.currency) == ("observed", minor, currency), r.note


@pytest.mark.parametrize(
    ("amount", "currency", "reason"),
    [
        ("1,299", "SAR", "ambiguous"),  # 1299 or 1.299? refused
        ("1.299", "SAR", "ambiguous"),  # same with a dot in a two-place currency
        ("12,500", "KWD", "ambiguous"),  # comma + 3 digits is never read as KWD fils
        ("1,29,900", "SAR", "separators do not read"),  # lakh grouping is not three-digit
        ("1.299.5", "SAR", "separators do not read"),
        ("1,2.50", "SAR", "mixed separators"),
        ("1.299,5.0", "SAR", "mixed separators"),
        ("12.5000", "AED", "more decimals than any currency"),
        ("-5", "AED", "negative amount"),  # was recorded as -500
        ("\u22125.00", "AED", "negative amount"),  # unicode minus
        ("-12,50", "AED", "negative amount"),
        ("NaN", "AED", "not a number"),
        ("Infinity", "AED", "not a number"),
        ("-Infinity", "AED", "not a number"),
        ("1e3", "AED", "not a number"),  # no exponents on a price tag
        ("0x10", "AED", "not a number"),
        ("12.50 AED", "AED", "not a number"),
    ],
)
def test_ambiguous_negative_and_non_finite_amounts_are_refused(
    amount: str, currency: str, reason: str
) -> None:
    r = _price(amount, currency)
    assert r.state == "parse_failed"
    assert r.value is None
    assert r.currency == currency
    assert reason in (r.note or ""), r.note


def test_non_finite_json_literals_are_refused_everywhere() -> None:
    bad = (
        '<script type="application/ld+json">{"@type": "Product", "name": "P", "offers": '
        '{"@type": "Offer", "price": NaN, "priceCurrency": "AED"}, '
        '"aggregateRating": {"ratingValue": Infinity, "ratingCount": 3}}</script>'
        '<script type="application/ld+json">{"@type": "Product", "name": "Q"}</script>'
    )
    blocks, failed = parse_jsonld(bad)
    assert [b["name"] for b in blocks] == ["Q"]
    assert len(failed) == 1
    r = _by_key(readings_from_generic(bad, locale="en-AE"))
    assert "price_minor" not in r
    assert r["title"].value == "Q"
    assert find_json_objects('{"sku": 1, "p": NaN} {"sku": 2}', "sku") == [{"sku": 2}]
    with pytest.raises(ValueError, match="-Infinity is not accepted"):
        next_data('<script id="__NEXT_DATA__">{"a": -Infinity}</script>')


def test_rating_must_be_a_finite_number_between_0_and_10() -> None:
    def page(value: str) -> Reading:
        html = (
            '<script type="application/ld+json">{"@type": "Product", "name": "P", '
            f'"aggregateRating": {{"ratingValue": "{value}", "ratingCount": "3"}}}}</script>'
        )
        return _by_key(readings_from_generic(html, locale="en-AE"))["rating_value"]

    assert page("4,5").value == Decimal("4.5")
    assert page("0").value == Decimal("0")
    for bad in ("NaN", "Infinity", "-Infinity", "-1", "11", "sNaN", "four"):
        r = page(bad)
        assert r.state == "parse_failed", bad
        assert r.raw_text == bad


def test_aggregate_offer_range_is_not_recorded_as_the_price() -> None:
    def page(low: str, high: str | None) -> str:
        hi = f', "highPrice": "{high}"' if high is not None else ""
        return (
            '<script type="application/ld+json">{"@type": "Product", "name": "P", "offers": '
            f'{{"@type": "AggregateOffer", "lowPrice": "{low}"{hi}, "priceCurrency": "AED"}}}}'
            "</script>"
        )

    ranged = page("10", "25")
    assert "price_minor" not in _by_key(readings_from_generic(ranged, locale="en-AE"))
    facts = generic_facts(ranged)
    assert facts.price is None
    assert facts.price_range == "10-25"
    single = _by_key(readings_from_generic(page("10", "10"), locale="en-AE"))["price_minor"]
    assert (single.value, single.currency) == (1000, "AED")
    assert str(single.source_path).endswith("offers[0].lowPrice")
    assert "single price" in (single.note or "")
    assert generic_facts(page("10", "10")).price_range is None
    only_low = _by_key(readings_from_generic(page("10", None), locale="en-AE"))["price_minor"]
    assert only_low.value == 1000


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


def test_find_json_objects_skips_braces_inside_strings_and_unbalanced_text() -> None:
    text = (
        'var a = "{ not json"; {"sku": "A", "t": "} {\\" {"} if (x) { {"sku": "B", "n": {"k": 1}}'
    )
    assert find_json_objects(text, "sku") == [
        {"sku": "A", "t": '} {" {'},
        {"sku": "B", "n": {"k": 1}},
    ]
    # a needle inside a string literal is not an object member
    assert find_json_objects('{"name": "\\"sku\\": 1"}', "sku") == []
    # two needles in one object yield that object once; the second stops at the seen brace
    assert find_json_objects('{"sku": "D", "x": {"y": 1}, "sku": "E"}', "sku") == [
        {"sku": "E", "x": {"y": 1}}
    ]
    # the enclosing object is taken even when the key sits after a nested object
    assert find_json_objects('{"n": {"a": 1}, "sku": "C"}', "sku") == [{"n": {"a": 1}, "sku": "C"}]


def test_find_json_objects_is_linear_in_the_payload() -> None:
    items = [f'{{"sku": "S{i}", "p": {{"x": [1, 2, {{"y": "{{"}}]}}}}' for i in range(4000)]
    text = "garbage {" + " ".join(items) + " trailing { {"
    found = find_json_objects(text, "sku")
    assert len(found) == 4000
    assert found[0]["sku"] == "S0"
    assert found[-1]["sku"] == "S3999"
    # A quadratic walk over the preceding braces would decode millions of spans here; the
    # single-pass scanner decodes one span per needle, so a generous bound still catches it.
    t0 = time.perf_counter()
    find_json_objects(text, "sku")
    assert time.perf_counter() - t0 < 5.0


def test_looked_for_names_only_registry_keys_and_covers_what_the_page_yields(
    product_html: str,
) -> None:
    assert {a.key for a in ATTRIBUTES} >= LOOKED_FOR
    assert {r.key for r in readings_from_generic(product_html, locale="en-AE")} <= LOOKED_FOR
    assert {"price_minor", "regular_price_minor", "gtin", "title", "breadcrumb"} <= LOOKED_FOR


def test_microdata_scope_without_type_is_ignored() -> None:
    """Faces pages carry ``itemscope`` elements with no ``itemtype``: skip them, do not crash."""
    html = (
        '<html><body><div itemscope><span itemprop="name">x</span></div>'
        '<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Lipstick</span>'
        '<span itemprop="brand">Brand</span></div></body></html>'
    )
    readings = readings_from_generic(html, locale="en-AE")
    assert any(r.key == "title" and r.value == "Lipstick" for r in readings)
