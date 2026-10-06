"""Faces extractor on synthetic SFCC-shaped HTML. No real retailer page is used here."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from pi_capture.faces import LOOKED_FOR, FacesFacts, faces_facts, readings_from_faces
from pi_capture.feed import SHOPS, build_feed
from pi_capture.generic import LOOKED_FOR as GENERIC_LOOKED_FOR
from pi_capture.model import ProductCapture, Reading
from pi_capture.registry import ATTRIBUTES

CaptureFactory = Callable[..., ProductCapture]

_DATALAYER = """
<script>
window.dataLayer = window.dataLayer || [];
dataLayer.push({"event":"page_view","page":"pdp"});
dataLayer.push({"event":"view_item","ecommerce":{"currency":"AED","value":215,"items":[
 {"item_id":"PM_GLOW_Tinted_Balm","item_name":"Tinted Balm","affiliation":"Shop",
  "currency":"AED","item_brand":"Glow","item_variant":"2000000000015","quantity":1,
  "item_gender":"WOMEN","item_in_stock":true,"price":215,"item_category":"Makeup",
  "item_category2":"Lips","item_category3":"Lip Balm","item_category4":"","item_category5":"",
  "discount":0,"item_size":"3g","item_color":"754_tender_peach"}]}});
</script>
"""

FACES_HTML = f"""<!doctype html>
<html lang="en" data-locale="en_AE"><head><title>Tinted Balm | Shop</title>
<link rel="canonical" href="https://shop.example/en/p/tinted-balm-006617133769.html">
<meta property="og:image" content="https://img.example/og.jpg">
{_DATALAYER}
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Product",
 "name":"Tinted Balm JSON-LD","brand":{{"@type":"Brand","name":"Glow JSON-LD"}},
 "image":"https://img.example/jsonld.jpg","sku":"006617133769",
 "offers":{{"@type":"Offer","price":"215.00","priceCurrency":"AED"}}}}</script>
</head><body>
<input type="hidden" class="js-gtm-site-currencycode" value="AED" />
<ol class="breadcrumb container" itemscope itemtype="https://schema.org/BreadcrumbList">
 <li class="breadcrumb-item" itemprop="itemListElement" itemscope
  itemtype="https://schema.org/ListItem">
  <a itemprop="item" href="/en"><span itemprop="name">Home</span></a><meta itemprop="position"
  content="1" /></li>
 <li class="breadcrumb-item" itemprop="itemListElement" itemscope
  itemtype="https://schema.org/ListItem">
  <a itemprop="item" href="/en/brands/glow"><span itemprop="name">GLOW</span></a><meta
  itemprop="position" content="3" /></li>
 <li class="breadcrumb-item" itemprop="itemListElement" itemscope
  itemtype="https://schema.org/ListItem">
  <a itemprop="item" href="/en/makeup"><span itemprop="name">Makeup</span></a><meta
  itemprop="position" content="2" /></li>
</ol>
<div class="js-product-details product-detail" data-pid="006617133769"
  data-ready-to-order="true" data-ean="2000000000015">
 <div class="js-availability-container d-none" data-ready-to-order="true"
  data-available="true"></div>
 <div class="product-brand text-uppercase"> <a href="/en/brands/glow">Glow HTML</a> </div>
 <div class="product-name"><span class="js-name rtlfix">Tinted Balm HTML</span></div>
 <div class="product-secondary-name">Hydrating Eau de Parfum SPF 15</div>
 <ul class="combined-badges">
  <li class="text-uppercase" data-badge-value="new"> New</li>
  <li class="text-uppercase" data-badge-value="exclusive"> Exclusive</li>
 </ul>
 <div class="js-out-of-stock-message out-of-stock-message d-none"><span
  class="out-of-stock-message-text">Out of Stock</span></div>
 <h2 class="js-main-price prices"><span class="price"><span>
  <span class="strike-through list"><span class="value" content="260.00">AED 260</span></span>
  <span class="js-price-color"><span class="value" content="215.00"><span class="js-price"
  data-original-price="215 AED">AED 215</span></span></span>
 </span></span></h2>
 <span class="ff-caption-sm">(Incl. 5% VAT)</span>
 <div id="points" class="muse-points-container"><span
  class="muse-points-amount"> Earn 205 MUSE points - </span></div>
 <div class="tamara-tabby-promotions" data-decimal-places="2" data-num-of-installments="4.0">
  <span class="js-instalment-price">53.75 AED</span>
  <div id="tabbyWidget" data-lang="en" data-currency="AED"></div>
  <tamara-widget type="tamara-summary" amount="215.00"></tamara-widget>
 </div>
 <div class="swatches">
  <button class="js-dy-attribute swatch-btn" title="Dreamy White"
  data-attr-value="dreamy_white" data-pid="006617133769">
   <span data-attr-value="dreamy_white" class="swatch-value selectable"
  style="background-image: url(https://img.example/sw1.jpg)"></span></button>
  <button class="js-dy-attribute swatch-btn selected" title="754 Tender Peach"
  data-attr-value="754_tender_peach" data-pid="006617133769">
   <span data-attr-value="754_tender_peach"
  class="swatch-value selectable selected"></span></button>
 </div>
 <div class="product-image-holder" data-cmp="ImageZoom" itemprop="image">
  <img src="https://img.example/006617133769_1.jpg?sw=800" class="js-zoom-image img-fluid"
  itemprop="image" /></div>
 <div class="product-image-holder" itemprop="image">
  <img src="https://img.example/006617133769_2.jpg?sw=800" class="js-zoom-image"
  itemprop="image" /></div>
 <div class="product-image-holder" itemprop="image">
  <img src="https://img.example/006617133769_1.jpg?sw=800" class="js-zoom-image"
  itemprop="image" /></div>
 <img src="https://img.example/thumb.jpg" class="product-thumbnail-image" itemprop="image" />
 <div id="collapseDescription" class="accordion-body collapse show">
  <div><div> A tinted balm   with amplified shine. </div></div></div>
</div>
</body></html>
"""

FACES_AR_HTML = """<!doctype html>
<html dir="rtl" lang="ar" data-locale="ar_AE"><head><title>عطر</title></head><body>
<script>
dataLayer.push({"event":"view_item","ecommerce":{"currency":"AED","value":515,"items":[
 {"item_id":"002116421165","item_name":"Wanted","item_brand":"Azzaro",
  "item_variant":"002116421165","item_gender":null,"item_in_stock":false,"price":515,
  "item_category":"Perfume","item_category2":"Perfumes","item_category3":"Men Perfume",
  "item_category4":"","discount":0,"item_size":null,"item_color":null}]}});
</script>
<div class="js-product-details" data-pid="002116421165" data-ready-to-order="false" data-ean="">
 <div class="js-availability-container" data-ready-to-order="false" data-available="false"></div>
 <span class="rtlfix product-type">عطر رجالي أو دو تواليت</span>
 <span class="js-selected-value selected-value">(100 ML)</span>
 <div class="js-out-of-stock-message out-of-stock-message"><span>غير متوفر حالياً</span></div>
 <span class="value" content="515.00">515</span>
 <small>(شامل ضريبة القيمة المضافة بنسبة 5%)</small>
 <span class="muse-points-amount"> اكسب 490 نقطة من ميوز على طلبك - </span>
 <button class="js-free-gift-button" type="button"> هدايا مجانية </button>
</div></body></html>
"""


def _by_key(readings: list[Reading]) -> dict[str, Reading]:
    out: dict[str, Reading] = {}
    for r in readings:
        out.setdefault(r.key, r)
    return out


def test_looked_for_names_registry_keys_and_covers_every_reading() -> None:
    assert {a.key for a in ATTRIBUTES} >= LOOKED_FOR
    assert LOOKED_FOR > GENERIC_LOOKED_FOR  # the generic readers fill the gaps, so theirs count
    for html, locale in ((FACES_HTML, "en-AE"), (FACES_AR_HTML, "ar-AE"), ("", "en-AE")):
        assert {r.key for r in readings_from_faces(html, locale=locale)} <= LOOKED_FOR
    assert {"shade_name", "installment_amount_minor", "vat_statement", "price_minor"} <= LOOKED_FOR


def test_one_reading_per_key_except_the_datalayer_stock_block() -> None:
    readings = readings_from_faces(FACES_HTML, locale="en-AE", url="https://shop.example/x")
    keys = [r.key for r in readings if r.key != "structured_data"]
    assert len(keys) == len(set(keys))
    blocks = [r for r in readings if r.key == "structured_data"]
    assert [r.source_path for r in blocks] == [
        "jsonld",
        "dataLayer.view_item.items[0].item_in_stock",
    ]


def test_the_datalayer_stock_flag_is_its_own_structured_data_block() -> None:
    def stock(html: str) -> list[Reading]:
        return [
            r
            for r in readings_from_faces(html, locale="en-AE")
            if r.source_path == "dataLayer.view_item.items[0].item_in_stock"
        ]

    (in_stock,) = stock(FACES_HTML)
    assert (in_stock.state, in_stock.raw_text, in_stock.value) == (
        "observed",
        "true",
        {"item_in_stock": True},
    )
    (out,) = stock(FACES_AR_HTML)
    assert out.value == {"item_in_stock": False}
    # a flag that is not a boolean is kept as stated (the feed then reads the stock as unknown)
    (odd,) = stock(FACES_HTML.replace('"item_in_stock":true', '"item_in_stock":"yes"'))
    assert (odd.raw_text, odd.value) == ("yes", {"item_in_stock": "yes"})
    assert "not a boolean" in (odd.note or "")
    (null,) = stock(FACES_HTML.replace('"item_in_stock":true', '"item_in_stock":null'))
    assert (null.raw_text, null.value) == ("null", {"item_in_stock": None})
    # no flag, or no dataLayer at all, states nothing
    assert stock(FACES_HTML.replace('"item_in_stock":true,', "")) == []
    assert stock(FACES_HTML.replace(_DATALAYER, "")) == []


def test_identity_comes_from_the_datalayer_and_data_attributes() -> None:
    r = _by_key(readings_from_faces(FACES_HTML, locale="en-AE"))
    assert r["style_id"].value == "PM_GLOW_Tinted_Balm"
    assert r["style_id"].source_path == "dataLayer.view_item.items[0].item_id"
    assert r["style_id_source"].value == "captured"
    assert r["retailer_sku"].value == "006617133769"
    assert r["gtin"].value == "02000000000015"
    assert r["gtin"].raw_text == "2000000000015"
    assert r["gtin"].source_path == "div.js-product-details[data-ean]"
    # dataLayer wins over the JSON-LD and over the rendered brand/name
    assert r["brand"].value == "Glow"
    assert r["title"].value == "Tinted Balm"


def test_taxonomy_and_breadcrumb() -> None:
    r = _by_key(readings_from_faces(FACES_HTML, locale="en-AE"))
    assert r["department"].value == "women"
    assert r["department"].raw_text == "WOMEN"
    assert r["category_l1..l4"].value == ["Makeup", "Lips", "Lip Balm"]
    assert r["category_l1..l4"].raw_text == "Makeup > Lips > Lip Balm"
    assert r["product_type"].value == "Lip Balm"
    assert str(r["product_type"].source_path).endswith("item_category3")
    assert r["breadcrumb"].value == ["Home", "Makeup", "GLOW"]  # ordered by position
    assert r["breadcrumb"].source_path == "microdata.BreadcrumbList"
    assert r["colour_code"].value == "754_tender_peach"


def test_shade_size_and_swatches() -> None:
    r = _by_key(readings_from_faces(FACES_HTML, locale="en-AE"))
    assert r["shade_name"].value == "754 Tender Peach"
    assert r["shade_name"].source_path == "button.swatch-btn.selected[title]"
    assert r["has_swatch_image"].value is True
    assert r["has_swatch_image"].raw_text == "1 of 2 swatches carry an image"
    assert r["size_label"].value == "3g"
    assert r["size_value"].value == Decimal("3")
    assert r["size_unit"].value == "g"


def test_prices_instalments_points_badges_and_vat() -> None:
    r = _by_key(readings_from_faces(FACES_HTML, locale="en-AE"))
    assert r["price_minor"].value == 21500
    assert r["price_minor"].raw_text == "215.00 AED"
    assert r["regular_price_minor"].value == 26000
    assert r["regular_price_minor"].source_path == (
        ".js-main-price span.strike-through span.value[content]"
    )
    assert r["price_minor"].note is None  # read from the js-main-price block itself
    assert r["vat_statement"].value == "Incl. 5% VAT"
    assert r["vat_statement"].raw_text == "(Incl. 5% VAT)"
    assert r["vat_statement"].source_path == "span.ff-caption-sm"  # where the text really was
    assert r["installment_provider"].value == ["tabby", "tamara"]
    assert r["installment_amount_minor"].value == 5375
    assert r["installment_amount_minor"].note == "currency=AED; 4.0 instalments"
    assert r["loyalty_points"].value == 205
    assert r["loyalty_points"].raw_text == "Earn 205 MUSE points -"
    assert r["badges"].value == ["new", "exclusive"]
    assert "gift_with_purchase" not in r


def test_content_gallery_and_derived_beauty_fields() -> None:
    r = _by_key(readings_from_faces(FACES_HTML, locale="en-AE"))
    assert r["image_urls"].value == [
        "https://img.example/006617133769_1.jpg?sw=800",
        "https://img.example/006617133769_2.jpg?sw=800",
    ]
    assert r["image_count"].value == 2
    assert r["description"].value == "A tinted balm with amplified shine."
    assert r["concentration"].value == "edp"
    assert r["concentration"].raw_text == "Eau de Parfum"
    assert r["spf"].value == 15


def test_client_side_blocks_are_explicit_not_shown() -> None:
    r = _by_key(readings_from_faces(FACES_HTML, locale="en-AE"))
    for key in ("rating_value", "rating_count", "related_products"):
        assert r[key].state == "not_shown"
        assert r[key].raw_text is None
        assert r[key].value is None
        assert r[key].note


def test_generic_fills_the_gaps_only() -> None:
    r = _by_key(readings_from_faces(FACES_HTML, locale="en-AE", url="https://shop.example/x"))
    assert r["canonical_url"].value == "https://shop.example/en/p/tinted-balm-006617133769.html"
    assert r["page_url"].value == "https://shop.example/x"
    assert r["structured_data"].state == "observed"
    assert str(r["image_urls"].source_path).startswith("div.product-image-holder")


def test_arabic_page_without_swatches_or_datalayer_size() -> None:
    r = _by_key(readings_from_faces(FACES_AR_HTML, locale="ar-AE"))
    assert r["style_id"].value == "002116421165"
    assert "gtin" not in r  # data-ean empty and item_variant equals the pid
    assert "department" not in r  # item_gender null
    assert "colour_code" not in r
    assert "shade_name" not in r
    assert "has_swatch_image" not in r
    assert r["product_type"].value == "عطر رجالي أو دو تواليت"
    assert r["concentration"].value == "edt"
    assert r["size_label"].value == "100 ML"
    assert r["size_label"].source_path == "span.js-selected-value"
    assert r["size_value"].value == Decimal("100")
    assert r["size_unit"].value == "ml"
    assert r["price_minor"].value == 51500  # currency from the dataLayer
    assert r["price_minor"].note == "no js-main-price block; first priced value on the page"
    assert str(r["vat_statement"].value).startswith("شامل")
    assert r["vat_statement"].source_path == "small"
    assert r["loyalty_points"].value == 490
    assert r["gift_with_purchase"].value == "هدايا مجانية"
    assert "installment_provider" not in r
    assert "badges" not in r


def test_size_edge_cases() -> None:
    def size(label: str) -> dict[str, Reading]:
        html = FACES_AR_HTML.replace("(100 ML)", f"({label})")
        return _by_key(readings_from_faces(html, locale="ar-AE"))

    oz = size("3.4 fl oz")
    assert oz["size_label"].value == "3.4 fl oz"
    assert oz["size_unit"].state == "parse_failed"
    assert "fl oz" in str(oz["size_unit"].note)
    assert oz["size_value"].state == "parse_failed"
    no_number = size("One Size")
    assert no_number["size_value"].state == "parse_failed"
    assert no_number["size_unit"].raw_text == "One Size"
    arabic = size("50 مل")
    assert arabic["size_unit"].value == "ml"
    assert arabic["size_value"].value == Decimal("50")
    pieces = size("2 pcs")
    assert pieces["size_unit"].value == "count"


def test_faces_pages_feed_their_own_availability_and_a_contradiction_is_unknown(
    make_capture: CaptureFactory,
) -> None:
    def row(html: str, locale: str, jsonld: str) -> dict[str, str]:
        html = html.replace(
            "</head>", f'<script type="application/ld+json">{jsonld}</script></head>'
        )
        capture = make_capture(readings=tuple(readings_from_faces(html, locale=locale)))
        (out,) = build_feed([capture], SHOPS["faces_ae"]).rows
        return out

    out_of_stock = '{"@type":"Product","offers":{"availability":"https://schema.org/OutOfStock"}}'
    in_stock = '{"@type":"Product","offers":{"availability":"https://schema.org/InStock"}}'
    assert row(FACES_HTML, "en-AE", "{}")["availability"] == "instock"  # the flag alone
    assert row(FACES_AR_HTML, "ar-AE", out_of_stock)["availability"] == "outofstock"
    assert "availability" not in row(FACES_AR_HTML, "ar-AE", in_stock)  # flag false: unknown


def test_template_leftovers_around_a_size_are_read_and_noted() -> None:
    def size(label: str) -> dict[str, Reading]:
        html = FACES_AR_HTML.replace("(100 ML)", f"({label})")
        return _by_key(readings_from_faces(html, locale="ar-AE"))

    for label, value, unit, note in (
        ("100_ml", "100", "ml", "underscore read as a space"),
        ("2500_ml", "2500", "ml", "underscore read as a space"),
        ("60_piece", "60", "count", "underscore read as a space"),
        ("90_pieces", "90", "count", "underscore read as a space"),
        ("'180g", "180", "g", "leading apostrophe dropped"),
    ):
        r = size(label)
        assert r["size_label"].value == label, label
        assert r["size_value"].value == Decimal(value), label
        assert r["size_value"].raw_text == label, label
        assert r["size_value"].note == note, label
        assert (r["size_unit"].value, r["size_unit"].note) == (unit, note), label
    # a thousand behind an underscore keeps both notes
    both = size("1,000_ml")
    assert both["size_value"].value == Decimal("1000")
    assert both["size_value"].note == (
        "underscore read as a space; comma read as a thousands separator"
    )
    # multipacks, sets, two numbers and shade names in the size slot are still not a size
    for label in ("3_20ml", "3__20", "100ml+30ml", "5x20ml", "13g_refill", "N1", "03 Medium"):
        assert size(label)["size_value"].state == "parse_failed", label


def test_thousands_separator_in_a_size_is_not_a_decimal_point() -> None:
    def size(label: str) -> dict[str, Reading]:
        html = FACES_AR_HTML.replace("(100 ML)", f"({label})")
        return _by_key(readings_from_faces(html, locale="ar-AE"))

    thousand = size("1,000 ml")
    assert thousand["size_value"].value == Decimal("1000")
    assert thousand["size_value"].note == "comma read as a thousands separator"
    assert thousand["size_unit"].value == "ml"
    assert size("10,000 pcs")["size_value"].value == Decimal("10000")
    # a comma followed by anything but exactly three digits is still a decimal comma
    assert size("1,5 ml")["size_value"].value == Decimal("1.5")
    assert size("1,5 ml")["size_value"].note is None
    assert size("2,25 l")["size_value"].value == Decimal("2.25")
    assert size("0.5 kg")["size_value"].value == Decimal("0.5")


def test_a_leading_zero_group_is_a_decimal_comma_not_a_thousand() -> None:
    def size(label: str) -> dict[str, Reading]:
        html = FACES_AR_HTML.replace("(100 ML)", f"({label})")
        return _by_key(readings_from_faces(html, locale="ar-AE"))

    for label, expected, unit in (("0,750 l", "0.75", "l"), ("0,500 kg", "0.5", "kg")):
        r = size(label)
        assert r["size_value"].value == Decimal(expected), label
        assert r["size_value"].note is None, label
        assert r["size_unit"].value == unit, label
    # ...and a thousands group still needs a non-zero lead
    assert size("1,750 ml")["size_value"].value == Decimal("1750")


def test_a_thousands_shaped_comma_with_litres_or_kilograms_is_ambiguous() -> None:
    def size(label: str) -> dict[str, Reading]:
        html = FACES_AR_HTML.replace("(100 ML)", f"({label})")
        return _by_key(readings_from_faces(html, locale="ar-AE"))

    for label, unit in (("1,500 l", "l"), ("1,500 kg", "kg"), ("2,000 L", "l")):
        r = size(label)
        assert r["size_value"].state == "parse_failed", label
        assert r["size_value"].value is None, label
        assert r["size_value"].raw_text == label
        assert "ambiguous" in str(r["size_value"].note), label
        assert r["size_unit"].state == "observed", label
        assert r["size_unit"].value == unit, label
    # millilitres, grams and counts are never sold in fractions this way: a thousand stands
    assert size("1,500 ml")["size_value"].value == Decimal("1500")
    assert size("1,500 g")["size_value"].value == Decimal("1500")
    assert size("1,000 pcs")["size_value"].value == Decimal("1000")


_MAIN_STRIKE = (
    '<span class="strike-through list"><span class="value" content="260.00">AED 260</span></span>'
)
_UPSELL_TILE = (
    '<div class="product-tile"><span class="price"><span class="strike-through list">'
    '<span class="value" content="999.00">AED 999</span></span>'
    '<span class="sales"><span class="value" content="750.00">AED 750</span></span></span></div>'
)


def test_a_struck_price_outside_the_main_price_block_is_not_this_products_regular_price() -> None:
    # the product itself has no strike-through; an upsell tile elsewhere on the page does
    html = FACES_HTML.replace(_MAIN_STRIKE, "").replace("</body>", _UPSELL_TILE + "</body>")
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    assert r["price_minor"].value == 21500
    assert "regular_price_minor" not in r
    # and when the product does have one, the tile does not override it
    html = FACES_HTML.replace("</body>", _UPSELL_TILE + "</body>")
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    assert r["regular_price_minor"].value == 26000


def test_a_struck_price_not_above_the_sale_price_is_parse_failed() -> None:
    for struck in ("200.00", "215.00"):
        html = FACES_HTML.replace('content="260.00">AED 260', f'content="{struck}">AED {struck}')
        r = _by_key(readings_from_faces(html, locale="en-AE"))
        assert r["price_minor"].value == 21500
        assert r["regular_price_minor"].state == "parse_failed"
        assert r["regular_price_minor"].value is None
        assert r["regular_price_minor"].raw_text == f"{struck} AED"
        assert r["regular_price_minor"].currency == "AED"
        assert "not above the sale price (21500 minor units)" in str(r["regular_price_minor"].note)
    # one minor unit above the sale price is a regular price again
    html = FACES_HTML.replace('content="260.00">AED 260', 'content="215.01">AED 215.01')
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    assert r["regular_price_minor"].value == 21501


def test_a_struck_price_with_no_sale_price_beside_it_is_parse_failed() -> None:
    html = FACES_HTML.replace('<span class="value" content="215.00">', '<span class="value">')
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    assert "price_minor" not in r or r["price_minor"].source_path != "span.value[content]"
    assert r["regular_price_minor"].state == "parse_failed"
    assert r["regular_price_minor"].raw_text == "260.00 AED"
    assert r["regular_price_minor"].note == "struck price with no readable sale price beside it"


def test_when_the_main_price_block_exists_there_is_no_page_wide_sale_fallback() -> None:
    # the product's own block has an unreadable sale price; a priced tile sits elsewhere
    html = FACES_HTML.replace('<span class="value" content="215.00">', '<span class="value">')
    html = html.replace("</body>", _UPSELL_TILE + "</body>")
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    values = [x.value for x in r.values()]
    assert 75000 not in values
    assert 99900 not in values
    if "price_minor" in r:
        assert r["price_minor"].source_path != "span.value[content]"
        assert r["price_minor"].note is None
    assert r["regular_price_minor"].state == "parse_failed"


_RATING = '"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.5","reviewCount":"12"},'


def test_a_rating_the_page_does_carry_is_read_and_not_marked_not_shown() -> None:
    # the page's own Product JSON-LD carries a rating this time
    html = FACES_HTML.replace('"offers":{"@type":"Offer"', _RATING + '"offers":{"@type":"Offer"')
    assert html != FACES_HTML
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    assert r["rating_value"].state == "observed"
    assert r["rating_value"].value == Decimal("4.5")
    assert r["rating_count"].state == "observed"
    assert r["rating_count"].value == 12
    assert r["related_products"].state == "not_shown"  # still nothing on the page for this one
    # exactly one reading per key, so the not_shown marker was never emitted for the two read
    assert [x.key for x in readings_from_faces(html, locale="en-AE")].count("rating_value") == 1


def test_unknown_gender_is_parse_failed_and_variant_barcode_is_used() -> None:
    html = FACES_AR_HTML.replace('"item_gender":null', '"item_gender":"PETS"').replace(
        '"item_variant":"002116421165"', '"item_variant":"3346470615458"'
    )
    r = _by_key(readings_from_faces(html, locale="ar-AE"))
    assert r["department"].state == "parse_failed"
    assert r["department"].raw_text == "PETS"
    assert r["gtin"].value == "03346470615458"
    assert r["gtin"].source_path == "dataLayer.view_item.items[0].item_variant"


def test_loyalty_text_without_a_number_is_parse_failed() -> None:
    html = FACES_HTML.replace("Earn 205 MUSE points -", "Earn MUSE points")
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    assert r["loyalty_points"].state == "parse_failed"
    assert r["loyalty_points"].raw_text == "Earn MUSE points"


def test_instalment_price_without_currency_is_parse_failed() -> None:
    html = FACES_AR_HTML.replace('"currency":"AED",', "").replace(
        '<button class="js-free-gift-button"',
        '<span class="js-instalment-price">12.50</span><button class="js-free-gift-button"',
    )
    r = _by_key(readings_from_faces(html, locale="ar-AE"))
    assert r["installment_amount_minor"].state == "parse_failed"
    assert r["price_minor"].state == "parse_failed"
    assert r["price_minor"].note == "no currency given beside the price"


def test_empty_page_yields_only_the_explicit_gaps() -> None:
    readings = readings_from_faces("<html><body><p>Nothing here</p></body></html>", locale="en-AE")
    states = {r.key: r.state for r in readings}
    assert states == {
        "rating_value": "not_shown",
        "rating_count": "not_shown",
        "related_products": "not_shown",
    }


def test_facts() -> None:
    assert faces_facts(FACES_HTML) == FacesFacts(
        available=True, ready_to_order=True, in_stock_flag=True, out_of_stock_shown=False
    )
    assert faces_facts(FACES_AR_HTML) == FacesFacts(
        available=False, ready_to_order=False, in_stock_flag=False, out_of_stock_shown=True
    )
    assert faces_facts("<html></html>") == FacesFacts(None, None, None, None)
    odd = FACES_HTML.replace('data-available="true"', 'data-available="maybe"')
    assert faces_facts(odd).available is None


def test_rendered_fallbacks_when_the_datalayer_is_missing() -> None:
    html = FACES_HTML.replace('"event":"view_item"', '"event":"something_else"')
    r = _by_key(readings_from_faces(html, locale="en-AE"))
    assert r["brand"].value == "Glow HTML"
    assert r["brand"].source_path == "div.product-brand"
    assert r["title"].value == "Tinted Balm HTML"
    assert r["title"].source_path == "span.js-name"
    assert "style_id" not in r
    assert r["gtin"].value == "02000000000015"
    assert "category_l1..l4" not in r
    assert r["shade_name"].value == "754 Tender Peach"
    assert "size_label" not in r
