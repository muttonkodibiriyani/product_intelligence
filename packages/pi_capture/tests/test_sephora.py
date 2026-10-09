"""Sephora extractor on a synthetic Next.js RSC payload. No real retailer page is used here."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from pi_capture.generic import LOOKED_FOR as GENERIC_LOOKED_FOR
from pi_capture.model import Reading
from pi_capture.registry import ATTRIBUTES
from pi_capture.sephora import (
    LOOKED_FOR,
    product_details,
    readings_from_sephora,
    readings_from_sephora_details,
)


def variant(
    pid: str, label: str, price: Any, sale: Any = "$undefined", **extra: Any
) -> dict[str, Any]:
    return {
        "product_id": pid,
        "c_price": price,
        "c_salesPrice": sale,
        "c_actualDiscount": 0,
        "c_variation_attribute_name": label,
        "c_variant_name": label,
        "swatchImage": None,
        "images": [
            {"link": f"https://img.example/{pid}/1.jpg"},
            {"link": f"https://img.example/{pid}/2.jpg"},
        ],
        "c_loyaltyPointPotentiallyGained": 150,
        **extra,
    }


def details(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "P100200",
        "name": "Hydra Serum",
        "currency": "SAR",
        "c_brand": {"id": "glow", "name": "Glow"},
        "c_productSlug": "glow-hydra-serum-P100200",
        "c_breadcrumbs": [
            {"id": "skincare", "name": "Skincare", "url": "/skincare"},
            {"id": "face", "name": "Face", "url": "/skincare/face"},
            {"id": "serums", "name": "Serums", "url": "/skincare/face/serums"},
        ],
        "c_bvAverageRating": 4.6,
        "c_bvReviewCount": 212,
        "c_bvRatingRange": 5,
        "longDescription": "<p>A <b>light</b> serum.<br>Daily use &amp; night.</p>",
        "c_ingredients": "Aqua, Glycerin, Niacinamide",
        "c_productFlags": [{"text1": "Exclusive"}, {"text1": "New"}],
        "c_product_promotions": [],
        "c_gifts_with_purchase": "$undefined",
        "c_productNature": "SERUM",
        "c_productMarche": "EXCLUSIVE",
        "c_productCible": "WOMEN",
        "c_default_variant_id": "V2",
        "c_variantsCount": 2,
        "c_variantsInfo": [variant("V1", "30 ml", 150), variant("V2", "50 ml", 240, 199.5)],
        "images": [{"link": "https://img.example/P100200/master.jpg"}],
        "recommendedProductIds": ["P300", "P301", ""],
        "c_youtubeVideos": [],
        "c_valuePrice": "$undefined",
        "c_price": 150,
        "c_salesPrice": "$undefined",
        "master": {"masterId": "P100200", "price": 150},
    }
    base.update(over)
    return base


def pdp_html(d: dict[str, Any] | None, lang: str = "en") -> str:
    """A page shaped like the storefront: JSON-LD in the head, productDetails in an RSC chunk."""
    chunks = ""
    if d is not None:
        payload = json.dumps(["$", "$L9", None, {"productDetails": d, "locale": lang}])
        chunk = json.dumps(f"9:{payload}\n")  # a JS string literal, as Next.js writes it
        chunks = f"<script>self.__next_f.push([1,{chunk}])</script>"
    return f"""<!doctype html><html lang="{lang}"><head><title>Hydra Serum | Shop</title>
<link rel="canonical" href="https://shop.example/{lang}/p/glow-hydra-serum-P100200">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Product",
 "name":"Hydra Serum JSON-LD","brand":{{"@type":"Brand","name":"Glow JSON-LD"}},
 "sku":"V1","gtin13":"3000000000017",
 "aggregateRating":{{"@type":"AggregateRating","ratingValue":"4.1","reviewCount":"9"}},
 "offers":{{"@type":"Offer","price":"150.00","priceCurrency":"SAR",
  "availability":"https://schema.org/InStock"}}}}</script>
</head><body><script>self.__next_f.push([0])</script>{chunks}
<h1>Hydra Serum</h1></body></html>"""


def _by_key(readings: list[Reading]) -> dict[str, Reading]:
    out = {r.key: r for r in readings}
    assert len(out) == len(readings), "one reading per key"
    return out


def test_looked_for_names_registry_keys_and_covers_every_reading() -> None:
    assert {a.key for a in ATTRIBUTES} >= LOOKED_FOR
    assert GENERIC_LOOKED_FOR <= LOOKED_FOR
    keys = {r.key for r in readings_from_sephora(pdp_html(details()), locale="en")}
    assert keys <= LOOKED_FOR


def test_product_details_is_the_inner_object_with_an_id() -> None:
    d = product_details(pdp_html(details()))
    assert d is not None
    assert d["id"] == "P100200"
    assert d["c_variantsInfo"][1]["c_salesPrice"] == Decimal("199.5")
    assert product_details(pdp_html(None)) is None
    assert product_details(pdp_html({"productDetails": {"name": "no id"}})) is None


def test_identity_brand_title_and_default_variant() -> None:
    r = _by_key(readings_from_sephora(pdp_html(details()), locale="en"))
    assert (r["style_id"].value, r["style_id_source"].value) == ("P100200", "captured")
    assert r["listing_id"].value == "glow-hydra-serum-P100200"
    assert r["retailer_sku"].value == "V2"
    assert r["retailer_sku"].source_path == "rsc.productDetails.c_variantsInfo[1].product_id"
    assert r["brand"].value == "Glow"
    assert r["title"].value == "Hydra Serum"
    assert r["gtin"].value == "03000000000017"  # the generic JSON-LD pass fills what RSC lacks
    assert (r["gtin"].source_path or "").startswith("jsonld")


def test_reduced_price_regular_price_points_and_the_variant_note() -> None:
    r = _by_key(readings_from_sephora(pdp_html(details()), locale="en"))
    assert (r["price_minor"].value, r["price_minor"].currency) == (19950, "SAR")
    assert r["price_minor"].raw_text == "199.5 SAR"
    assert r["price_minor"].note == "default variant of 2 on this page"
    assert (r["regular_price_minor"].value, r["regular_price_minor"].state) == (24000, "observed")
    assert r["loyalty_points"].value == 150


def test_no_reduced_price_means_the_regular_price_is_explicitly_not_shown() -> None:
    d = details(c_default_variant_id="V1")
    r = _by_key(readings_from_sephora_details(d))
    assert r["price_minor"].value == 15000
    assert r["price_minor"].source_path == "rsc.productDetails.c_variantsInfo[0].c_price"
    assert r["regular_price_minor"].state == "not_shown"
    assert "regular" in (r["regular_price_minor"].note or "")


def test_an_undefined_reduced_price_is_absent_so_the_price_is_the_regular_price() -> None:
    d = details(c_variantsInfo=[variant("V1", "30 ml", 150, "$undefined")])
    r = _by_key(readings_from_sephora(pdp_html(d), locale="en"))
    assert (r["price_minor"].value, r["price_minor"].state) == (15000, "observed")
    assert (r["price_minor"].source_path or "").endswith("c_variantsInfo[0].c_price")
    assert r["regular_price_minor"].state == "not_shown"


def test_a_reduced_price_left_as_a_reference_leaves_both_prices_unread() -> None:
    d = details(c_variantsInfo=[variant("V1", "30 ml", 150, "$83:props:offers")])
    r = _by_key(readings_from_sephora(pdp_html(d), locale="en"))
    # neither c_price nor the JSON-LD offer may stand in for a price the page did not inline
    assert "price_minor" not in r
    assert "regular_price_minor" not in r
    assert r["loyalty_points"].value == 150
    assert {"price_minor", "regular_price_minor"} <= LOOKED_FOR
    assert "price_minor" not in _by_key(readings_from_sephora_details(d))


def test_a_regular_price_not_above_the_reduced_price_is_a_parse_failure() -> None:
    d = details(c_variantsInfo=[variant("V2", "50 ml", 199.5, 199.5)])
    r = _by_key(readings_from_sephora_details(d))
    assert r["price_minor"].value == 19950
    assert r["regular_price_minor"].state == "parse_failed"
    assert r["regular_price_minor"].raw_text == "199.5 SAR"
    assert "19950" in (r["regular_price_minor"].note or "")


def test_an_unknown_default_variant_falls_back_to_the_first_and_says_so() -> None:
    d = details(c_default_variant_id="V9")
    r = _by_key(readings_from_sephora_details(d))
    assert r["retailer_sku"].value == "V1"
    assert r["price_minor"].note == "first variant of 2 on this page"
    single = details(c_variantsInfo=[variant("V1", "30 ml", 150)], c_default_variant_id="V1")
    assert _by_key(readings_from_sephora_details(single))["price_minor"].note is None


def test_a_shade_label_is_a_shade_and_a_size_label_is_a_size() -> None:
    r = _by_key(readings_from_sephora_details(details()))
    assert (r["size_label"].value, r["size_value"].value, r["size_unit"].value) == (
        "50 ml",
        Decimal(50),
        "ml",
    )
    assert "shade_name" not in r
    shade = details(c_variantsInfo=[variant("S1", "02 Rose Nude", 120)], c_default_variant_id="S1")
    r = _by_key(readings_from_sephora_details(shade))
    assert "size_label" not in r
    assert r["shade_name"].value == "02 Rose Nude"
    spelled = details(c_variantsInfo=[variant("S2", "Rose", 120)], c_default_variant_id="S2")
    assert _by_key(readings_from_sephora_details(spelled))["shade_name"].value == "Rose"
    odd = details(c_variantsInfo=[variant("S3", "3 oz", 120)], c_default_variant_id="S3")
    r = _by_key(readings_from_sephora_details(odd))
    assert r["size_label"].value == "3 oz"
    assert r["size_unit"].state == "parse_failed"


def test_the_pages_own_template_flag_decides_shade_or_size_before_the_label_shape() -> None:
    flagged_shade = variant("F1", "100 Ivory", 120, c_isShadeVariationTemplate=True)
    r = _by_key(readings_from_sephora_details(details(c_variantsInfo=[flagged_shade])))
    assert r["shade_name"].value == "100 Ivory"
    assert "size_label" not in r
    flagged_size = variant("F2", "Mini", 60, c_isSizeVariationTemplate=True)
    r = _by_key(readings_from_sephora_details(details(c_variantsInfo=[flagged_size])))
    assert r["size_label"].value == "Mini"
    assert r["size_value"].state == "parse_failed"
    assert "shade_name" not in r


def test_rsc_references_are_absent_not_text() -> None:
    d = details(
        c_productSlug="$83:props:slug",
        c_ingredients="$undefined",
        c_productNature="$undefined",
        c_variantsInfo=[variant("V1", "$undefined", "$undefined", "$undefined")],
        c_default_variant_id="V1",
    )
    r = _by_key(readings_from_sephora_details(d))
    for key in (
        "listing_id",
        "inci_list",
        "product_type",
        "price_minor",
        "size_label",
        "shade_name",
    ):
        assert key not in r, key
    assert "regular_price_minor" not in r  # no price at all: nothing to say about a regular one
    assert r["loyalty_points"].value == 150


def test_a_price_that_is_text_but_not_a_number_is_a_parse_failure() -> None:
    d = details(c_variantsInfo=[variant("V1", "30 ml", "one fifty")], c_default_variant_id="V1")
    r = _by_key(readings_from_sephora_details(d))
    assert (r["price_minor"].state, r["price_minor"].raw_text) == ("parse_failed", "one fifty")


def test_classification_breadcrumb_and_more_than_four_levels() -> None:
    r = _by_key(readings_from_sephora_details(details()))
    assert r["breadcrumb"].value == ["Skincare", "Face", "Serums"]
    assert r["category_l1..l4"].value == ["Skincare", "Face", "Serums"]
    assert r["category_l1..l4"].note is None
    assert r["product_type"].value == "serum"
    assert r["exclusivity"].value == "exclusive"
    deep = details(c_breadcrumbs=[{"name": n} for n in ("A", "B", "C", "D", "E")])
    r = _by_key(readings_from_sephora_details(deep))
    assert r["breadcrumb"].value == ["A", "B", "C", "D", "E"]
    assert r["category_l1..l4"].value == ["A", "B", "C", "D"]
    assert r["category_l1..l4"].note == "5 levels on the page; the first 4 kept"


def test_exclusivity_outside_the_enum_is_kept_as_a_parse_failure() -> None:
    r = _by_key(readings_from_sephora_details(details(c_productMarche="selective")))
    assert r["exclusivity"].value == "selective"
    r = _by_key(readings_from_sephora_details(details(c_productMarche="PRESTIGE")))
    assert (r["exclusivity"].state, r["exclusivity"].raw_text) == ("parse_failed", "PRESTIGE")
    assert "exclusivity" not in _by_key(
        readings_from_sephora_details(details(c_productMarche=None))
    )


def test_description_ingredients_images_and_video() -> None:
    r = _by_key(readings_from_sephora_details(details()))
    assert r["description"].value == "A light serum. Daily use & night."
    assert r["description"].raw_text == "<p>A <b>light</b> serum.<br>Daily use &amp; night.</p>"
    assert r["inci_list"].value == "Aqua, Glycerin, Niacinamide"
    assert r["image_urls"].value == ["https://img.example/V2/1.jpg", "https://img.example/V2/2.jpg"]
    assert r["image_count"].value == 2
    assert r["image_urls"].source_path == "rsc.productDetails.c_variantsInfo[1].images[].link"
    assert r["has_video"].value is False
    d = details(c_variantsInfo=[variant("V1", "30 ml", 150, images=[])], c_youtubeVideos=["abc"])
    r = _by_key(readings_from_sephora_details(d))
    assert r["image_urls"].value == ["https://img.example/P100200/master.jpg"]
    assert r["image_urls"].source_path == "rsc.productDetails.images[].link"
    assert r["has_video"].value is True
    bare = details(
        c_variantsInfo=[variant("V1", "30 ml", 150, images=[])], images=[], c_youtubeVideos=None
    )
    r = _by_key(readings_from_sephora_details(bare))
    assert "image_urls" not in r
    assert "has_video" not in r


def test_duplicate_image_links_are_counted_once() -> None:
    link = {"link": "https://img.example/same.jpg"}
    d = details(c_variantsInfo=[variant("V1", "30 ml", 150, images=[link, link, {"link": " "}])])
    r = _by_key(readings_from_sephora_details(d))
    assert r["image_count"].value == 1


def test_ratings_prefer_the_rsc_block_and_no_reviews_is_not_a_zero_rating() -> None:
    r = _by_key(readings_from_sephora(pdp_html(details()), locale="en"))
    assert (r["rating_value"].value, r["rating_count"].value) == (Decimal("4.6"), 212)
    assert r["rating_value"].source_path == "rsc.productDetails.c_bvAverageRating"
    r = _by_key(readings_from_sephora_details(details(c_bvAverageRating=0, c_bvReviewCount=0)))
    assert r["rating_count"].value == 0
    assert r["rating_value"].state == "not_shown"
    r = _by_key(readings_from_sephora_details(details(c_bvAverageRating=None, c_bvReviewCount=2.5)))
    assert r["rating_count"].state == "parse_failed"
    assert "rating_value" not in r


def test_badges_promotions_and_related_products() -> None:
    r = _by_key(readings_from_sephora_details(details()))
    assert r["badges"].value == ["Exclusive", "New"]
    assert (r["gift_with_purchase"].state, r["gift_with_purchase"].note) == (
        "not_shown",
        "promotion list present and empty",
    )
    assert r["related_products"].value == ["P300", "P301"]
    promos = [
        {
            "ID": "a",
            "showBannerPDP": True,
            "promotionTitle": "Free pouch",
            "promotionDescription": "Over 300 SAR",
        },
        {
            "ID": "b",
            "showBannerPDP": False,
            "promotionTitle": "Hidden",
            "promotionDescription": "x",
        },
        {"ID": "c", "promotionTitle": "Deluxe sample", "promotionDescription": "$undefined"},
    ]
    r = _by_key(
        readings_from_sephora_details(details(c_product_promotions=promos, c_productFlags=[]))
    )
    assert r["gift_with_purchase"].value == "Free pouch: Over 300 SAR\nDeluxe sample"
    assert "badges" not in r
    d = details(c_product_promotions="$undefined", recommendedProductIds="$undefined")
    r = _by_key(readings_from_sephora_details(d))
    assert "gift_with_purchase" not in r
    assert "related_products" not in r


def test_without_product_details_only_the_generic_readers_speak() -> None:
    r = _by_key(readings_from_sephora(pdp_html(None), locale="en"))
    assert r["title"].value == "Hydra Serum JSON-LD"
    assert r["price_minor"].value == 15000
    assert all(not (x.source_path or "").startswith("rsc.productDetails") for x in r.values())


def test_arabic_page_reads_the_same_block_and_the_generic_language() -> None:
    d = details(
        name="سيروم مرطب", c_brand={"name": "جلو"}, c_breadcrumbs=[{"name": "العناية بالبشرة"}]
    )
    r = _by_key(readings_from_sephora(pdp_html(d, lang="ar"), locale="ar"))
    assert r["title"].value == "سيروم مرطب"
    assert r["brand"].value == "جلو"
    assert r["breadcrumb"].value == ["العناية بالبشرة"]
    assert r["page_language"].value == "ar"


def test_details_path_accepts_floats_from_stored_json() -> None:
    d = json.loads(json.dumps(details()))  # floats, as a snapshot record stores them
    r = _by_key(readings_from_sephora_details(d))
    assert r["price_minor"].value == 19950
    assert r["rating_value"].value == Decimal("4.6")
    assert not any(isinstance(x.value, float) for x in r.values())


def test_without_variants_the_product_level_price_is_read() -> None:
    d = details(
        c_variantsInfo=[], c_price=150, c_salesPrice=120, c_loyaltyPointPotentiallyGained=99
    )
    r = _by_key(readings_from_sephora_details(d))
    assert "retailer_sku" not in r
    assert "size_label" not in r
    assert (r["price_minor"].value, r["price_minor"].source_path) == (
        12000,
        "rsc.productDetails.c_salesPrice",
    )
    assert r["regular_price_minor"].value == 15000
    assert r["loyalty_points"].value == 99
    assert r["image_urls"].value == ["https://img.example/P100200/master.jpg"]


def test_a_reduced_price_without_a_regular_price_beside_it_is_explicit() -> None:
    d = details(
        c_variantsInfo=[variant("V1", "30 ml", "$undefined", 120)], c_default_variant_id="V1"
    )
    r = _by_key(readings_from_sephora_details(d))
    assert r["price_minor"].value == 12000
    assert r["regular_price_minor"].state == "not_shown"
    assert r["regular_price_minor"].note == "reduced price shown without a regular price beside it"
    odd = details(c_variantsInfo=[variant("V1", "30 ml", [150])], c_default_variant_id="V1")
    r = _by_key(readings_from_sephora_details(odd))
    assert (r["price_minor"].state, r["price_minor"].note) == ("parse_failed", "not a number")


def _shade(swatch: Any) -> dict[str, Any]:
    v = variant("V9", "222 Confident Nude", 99, swatchImage=swatch)
    return details(c_default_variant_id="V9", c_variantsInfo=[v])


def test_a_swatch_counts_only_when_it_is_not_one_of_the_gallery_images() -> None:
    chip = "https://cdn.example/dw/images/782276_th.jpeg?sw=96"
    r = _by_key(readings_from_sephora_details(_shade(chip)))["has_swatch_image"]
    assert (r.state, r.value, r.raw_text) == ("observed", True, chip)
    assert r.source_path == "rsc.productDetails.c_variantsInfo[0].swatchImage"
    # the file name says "swatch", but it is the variant's own pack shot: not a swatch
    shot = variant("V9", "30 ml", 99, swatchImage="https://cdn.example/x/470969_swatch.jpg?sw=1248")
    shot["images"].append({"link": "https://img.example/a/470969_swatch.jpg"})
    d = details(c_default_variant_id="V9", c_variantsInfo=[shot])
    r = _by_key(readings_from_sephora_details(d))["has_swatch_image"]
    assert (r.state, r.value) == ("observed", False)
    assert "gallery" in (r.note or "")
    # the same comparison by file name, whatever the host and query
    same = _shade("https://other.example/V9/1.jpg?sw=50")
    assert _by_key(readings_from_sephora_details(same))["has_swatch_image"].value is False


def test_a_missing_or_referenced_swatch_is_explicitly_not_shown() -> None:
    for missing in (None, "", "$undefined", "https://cdn.example/dir/"):
        r = _by_key(readings_from_sephora_details(_shade(missing)))["has_swatch_image"]
        assert (r.state, r.value) == ("not_shown", None), missing
    no_variants = details(c_variantsInfo=[])
    assert "has_swatch_image" not in _by_key(readings_from_sephora_details(no_variants))


def _ld(*dates: Any) -> list[dict[str, Any]]:
    reviews = [{"@type": "Review", "datePublished": d, "reviewRating": 5} for d in dates]
    return [{"@type": "Organization"}, {"@type": "Product", "name": "X", "review": reviews}]


def test_review_recency_is_the_newest_listed_review_as_a_dubai_date() -> None:
    ld = _ld("2026-09-01T10:00:00.000+00:00", "2026-09-11T21:17:16.000+00:00", "2020-06-19T19:49Z")
    r = _by_key(readings_from_sephora_details(details(), jsonld=ld))["review_recency"]
    # 21:17 UTC on the 11th is already the 12th in Dubai (UTC+4)
    assert (r.state, r.value, r.raw_text) == (
        "observed",
        "2026-09-12",
        ld[1]["review"][1]["datePublished"],
    )
    assert r.source_path == "jsonld[1].review[].datePublished"
    assert r.note == "newest of 3 reviews the page lists; Asia/Dubai date"


def test_unreadable_review_dates_are_skipped_with_a_note_or_fail_when_none_is_readable() -> None:
    ld = _ld("2026-09-01T10:00:00+00:00", "yesterday", "2026-09-30T10:00:00")  # naive: no day
    r = _by_key(readings_from_sephora_details(details(), jsonld=ld))["review_recency"]
    assert (r.value, r.note) == (
        "2026-09-01",
        "newest of 3 reviews the page lists; Asia/Dubai date; 2 unreadable date(s) skipped",
    )
    bad = _ld("yesterday", "2026-09-30T10:00:00")
    r = _by_key(readings_from_sephora_details(details(), jsonld=bad))["review_recency"]
    assert (r.state, r.value, r.raw_text) == (
        "parse_failed",
        None,
        "yesterday\n2026-09-30T10:00:00",
    )


def test_no_review_list_is_not_shown_and_no_json_ld_is_not_read() -> None:
    for ld in ([{"@type": "Product", "name": "X"}], _ld(), [{"@type": "Product", "review": [{}]}]):
        r = _by_key(readings_from_sephora_details(details(), jsonld=ld))["review_recency"]
        assert (r.state, r.value) == ("not_shown", None)
    org = _by_key(readings_from_sephora_details(details(), jsonld=[{"@type": "Organization"}]))
    assert org["review_recency"].note == "no product in the structured data"
    assert "review_recency" not in _by_key(readings_from_sephora_details(details()))


def test_the_page_path_reads_reviews_from_its_own_json_ld() -> None:
    review = '"review":[{"@type":"Review","datePublished":"2026-10-01T03:00:00.000+00:00"}],'
    page = pdp_html(details()).replace('"sku":"V1",', '"sku":"V1",' + review)
    r = _by_key(readings_from_sephora(page, locale="en"))
    assert (r["review_recency"].value, r["review_recency"].source_path) == (
        "2026-10-01",
        "jsonld[0].review[].datePublished",
    )
    plain = _by_key(readings_from_sephora(pdp_html(details()), locale="en"))
    assert plain["review_recency"].state == "not_shown"
    assert {"review_recency", "has_swatch_image"} <= LOOKED_FOR
