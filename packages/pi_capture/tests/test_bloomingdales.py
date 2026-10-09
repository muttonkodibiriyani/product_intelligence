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
    assert "rating_value" not in got  # no c_ratings on this page: unread, not "not shown"
    assert "rating_count" not in got
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


# The page-attribute fields, shaped like the storefront's (values synthetic). The record also
# carries the fields that must never be read: the retailer's unit cost, merchandising scores and a
# payment widget's key.
_UNIT_COST = "77.123"
_WIDGET_KEY = "SYNTHETIC-NOT-A-KEY"
_ATTRIBUTES: dict[str, Any] = {
    "c_vpn": "VPN-0001",
    "c_ingredients": (
        "Water\\Aqua\\Eau, Glycerin, Propanediol, Xanthan Gum, Phenoxyethanol, Citric Acid"
    ),
    "longDescription": "<li>Fragrance-Free</li>\n<li>Vegan </li>\n<li>Vegan</li>",
    "c_howToUse": "<li>Massage onto damp skin.</li>",
    "c_skintype": "All Skin Types",
    "c_skinConcern": ["Dry Skin", "Dullness"],
    "c_scent": "Citrus",
    "c_collection": "Velvet Oud",
    "c_npm_finish": ["matte"],
    "c_npm_formulation": ["gel___cream"],
    "c_colors": [
        {"text": "Clear", "id": "900000101", "value": "clear"},
        {"text": "Rose", "id": "900000102", "value": "rose"},
    ],
    "c_badges": ["Online Only", " ", "Online Only"],
    "c_product_promotions": [
        {"promotionId": "PLPOOSItems", "calloutMsgText": "Not a gift"},
        {
            "promotionId": "GWP-PDPMessage-V4-Synthetic",
            "calloutMsgText": "<b>Beauty Treats</b>, Complimentary gift over AED 500.",
            "calloutMsgImage": "https://img.example/gift.jpg",
        },
    ],
    "c_ratings": "4.38",
    "c_amberPointsAmount": 129,
    "c_tabbyPromo": {
        "currency": "AED",
        "apiKey": _WIDGET_KEY,
        "monthlyPrice": "35",
        "tabbyPromoApplicable": True,
    },
    "c_tamaraPromo": {"currency": "AED", "monthlyPrice": 35, "tamaraPromoApplicable": True},
    "c_unitcost": _UNIT_COST,
    "c_fe_score": 0.91,
    "c_fe_rank_hint": "secret-rank",
}


def test_page_attributes_are_read_from_the_named_fields() -> None:
    got = _by_key(readings_from_bloomingdales(_page(_product(**_ATTRIBUTES)), locale="en-AE"))
    assert got["mpn"].value == "VPN-0001"
    assert str(got["inci_list"].value).startswith("Water\\Aqua\\Eau, Glycerin")
    assert got["bullets"].value == ["Fragrance-Free", "Vegan"]
    assert got["skin_type"].value == ["All Skin Types"]
    assert got["concern"].value == ["Dry Skin", "Dullness"]
    assert (got["fragrance_family"].value, got["collection"].value) == ("Citrus", "Velvet Oud")
    assert got["finish"].value == "matte"
    assert got["shade_name"].value == "Clear"  # the entry whose id is this product's
    assert got["badges"].value == ["Online Only"]
    assert got["gift_with_purchase"].value == "Beauty Treats, Complimentary gift over AED 500."
    assert got["rating_value"].value == Decimal("4.38")
    assert got["loyalty_points"].value == 129
    assert got["installment_provider"].value == ["tabby", "tamara"]
    assert (got["installment_amount_minor"].value, got["installment_amount_minor"].currency) == (
        3500,
        "AED",
    )


def test_attribute_values_outside_the_spec_are_parse_failed_not_stretched() -> None:
    product = _product(
        **_ATTRIBUTES
        | {
            "c_npm_finish": ["matte", "natural"],
            "c_ingredients": "The list of ingredients is on all of our product packaging.",
            "c_ratings": "9.5",
        }
    )
    got = _by_key(readings_from_bloomingdales(_page(product), locale="en-AE"))
    assert got["finish"].state == "parse_failed"
    assert got["formulation"].state == "parse_failed"  # "gel___cream" is no single formulation
    assert got["inci_list"].state == "parse_failed"
    assert got["rating_value"].state == "parse_failed"


def test_fragrance_notes_are_not_an_ingredient_list() -> None:
    notes = "Ingredients: Top: Pink Pepper, Rose Petals, Heart: Raspberry, Rose, Base: Amber, Musk"
    got = _by_key(readings_from_bloomingdales(_page(_product(c_ingredients=notes)), locale="en-AE"))
    assert got["inci_list"].state == "parse_failed"


def test_the_nocolor_entry_and_unequal_instalments_are_not_read_as_values() -> None:
    product = _product(
        **_ATTRIBUTES
        | {
            "c_colors": [{"text": "No Color", "id": "900000101", "value": "nocolor"}],
            "c_tamaraPromo": {"currency": "AED", "monthlyPrice": 36, "tamaraPromoApplicable": True},
        }
    )
    got = _by_key(readings_from_bloomingdales(_page(product), locale="en-AE"))
    assert "shade_name" not in got
    assert got["installment_amount_minor"].state == "parse_failed"


def test_unit_cost_merchandising_scores_and_keys_never_reach_readings_or_the_feed(
    make_capture: CaptureFactory,
) -> None:
    readings = readings_from_bloomingdales(_page(_product(**_ATTRIBUTES)), locale="en-AE")
    capture = make_capture(readings=tuple(readings), url="https://bloomingdales.ae/p/x")
    feed = build_feed([capture], SHOPS["bloomingdales_ae"])
    rows_text = json.dumps(feed.rows, default=str)
    readings_text = json.dumps(
        [
            (r.key, r.raw_text, r.value, r.source_path, r.note)
            for r in readings
            if r.key != "structured_data"  # the JSON-LD block, which carries no productData
        ],
        default=str,
    )
    for forbidden in (_UNIT_COST, _WIDGET_KEY, "c_unitcost", "c_fe_", "secret-rank", "apiKey"):
        assert forbidden not in rows_text
        assert forbidden not in readings_text
    assert not any("cost" in key for key in feed.rows[0])


def test_the_published_live_date_is_read_as_published() -> None:
    got = _by_key(
        readings_from_bloomingdales(_page(_product(c_prd_live_date="2025-05-25")), locale="en-AE")
    )
    live = got["listing_live_date"]
    assert (live.state, live.raw_text, live.value) == ("observed", "2025-05-25", "2025-05-25")
    assert live.source_path == "productData.c_prd_live_date"
    assert "launch_date" not in got
    assert "first_seen" not in got


@pytest.mark.parametrize(
    ("value", "state"),
    [
        (None, "not_shown"),
        (" ", "not_shown"),
        ("2025-13-01", "parse_failed"),
        ("May 25", "parse_failed"),
    ],
)
def test_a_missing_or_unreadable_live_date_is_explicit(value: object, state: str) -> None:
    got = _by_key(
        readings_from_bloomingdales(_page(_product(c_prd_live_date=value)), locale="en-AE")
    )
    assert (got["listing_live_date"].state, got["listing_live_date"].value) == (state, None)


_PICKUP_NOTE = "retailer payload flag; whether the page displays it is unverified"


def _store(name: Any = "Bloomingdale's - Dubai Mall", **over: Any) -> dict[str, Any]:
    store: dict[str, Any] = {
        "ID": "country_store_pickup",
        "name": name,
        "available": False,
        "clickAndCollectEnabled": True,
        "inventoryListId": "uae-storepickup",
        "stockLevel": 7,
    }
    return store | over


def _variant(pickup: Any, pid: str = "900000101") -> dict[str, Any]:
    va = {"pid": pid, "availableForInStorePickup": pickup, "availability": {"availableQuantity": 9}}
    return {"variantId": pid, "c_variant_availability": [va]}


def _pickup(**over: Any) -> Reading:
    got = _by_key(readings_from_bloomingdales(_page(_product(**over)), locale="en-AE"))
    return got["store_availability"]


def test_store_pickup_is_read_per_click_and_collect_store_and_agrees_with_the_product() -> None:
    off = _pickup(c_stores=[_store()], c_availableForInStorePickup=False, c_sizes=[_variant(False)])
    assert (off.state, off.value) == (
        "observed",
        [{"store": "Bloomingdale's - Dubai Mall", "pickup_available": False}],
    )
    assert (off.raw_text, off.source_path, off.note) == (
        "Bloomingdale's - Dubai Mall: False",
        "productData.c_stores[]",
        _PICKUP_NOTE,
    )
    stores = [_store(available=True), _store("Closed Store", clickAndCollectEnabled=False)]
    on = _pickup(c_stores=stores, c_availableForInStorePickup=True, c_sizes=[_variant(True)])
    assert on.value == [{"store": "Bloomingdale's - Dubai Mall", "pickup_available": True}]
    # another variant's flag is not this page's
    other = _pickup(c_stores=[_store()], c_sizes=[_variant(True, pid="900000999")])
    assert (other.state, other.value) == (
        "observed",
        [{"store": "Bloomingdale's - Dubai Mall", "pickup_available": False}],
    )


def test_a_product_or_variant_pickup_flag_that_disagrees_with_the_stores_is_parse_failed() -> None:
    for over in (
        {"c_availableForInStorePickup": True},
        {"c_sizes": [_variant(True)]},
        {"c_availableForInStorePickup": False, "c_sizes": [_variant(True)]},
    ):
        r = _pickup(c_stores=[_store()], **over)
        assert (r.state, r.value, r.raw_text) == (
            "parse_failed",
            None,
            "Bloomingdale's - Dubai Mall: False",
        ), over
        assert "but the stores' available flags say False" in (r.note or "")
    bad = _pickup(c_stores=[_store(available="yes")])
    assert (bad.state, bad.value) == ("parse_failed", None)
    nameless = _pickup(c_stores=[_store(name=" ")])
    assert (nameless.state, nameless.value) == ("parse_failed", None)
    odd = _pickup(c_stores={"name": "x", "stockLevel": 7})
    assert (odd.state, odd.raw_text, odd.note) == ("parse_failed", "dict", "c_stores is not a list")


def test_a_malformed_store_entry_makes_the_whole_value_parse_failed() -> None:
    valid = _store(available=True)
    cases: list[tuple[list[Any], str, str]] = [
        (["Dubai Mall"], "str", "a c_stores entry that is not a store"),
        ([7], "int", "a c_stores entry that is not a store"),
        ([valid, None], "NoneType", "a c_stores entry that is not a store"),
    ]
    for enabled in ("true", 1, None):
        raw = f'"Bloomingdale\'s - Dubai Mall": clickAndCollectEnabled={enabled!r}'
        cases.append(([_store(clickAndCollectEnabled=enabled)], raw, ""))
    missing = {k: v for k, v in _store().items() if k != "clickAndCollectEnabled"}
    cases.append(([missing], '"Bloomingdale\'s - Dubai Mall": clickAndCollectEnabled=None', ""))
    # one malformed entry beside a valid one: no partial value
    cases.append(
        (
            [valid, _store("Other", clickAndCollectEnabled="yes")],
            "'Other': clickAndCollectEnabled='yes'",
            "",
        )
    )
    for stores, raw, note in cases:
        r = _pickup(c_stores=stores, c_availableForInStorePickup=True)
        assert (r.state, r.value, r.raw_text) == ("parse_failed", None, raw), stores
        assert r.note == (note or "a store without a true/false clickAndCollectEnabled")


def test_no_store_list_is_not_shown_and_never_a_pickup_false() -> None:
    cases: list[dict[str, Any]] = [{}, {"c_stores": []}, {"c_stores": None}]
    for over in cases:
        r = _pickup(**over)
        assert (r.state, r.value, r.note) == ("not_shown", None, "no c_stores list"), over
    closed = [
        _store(clickAndCollectEnabled=False, available=True),
        _store("B", clickAndCollectEnabled=False),
    ]
    r = _pickup(c_stores=closed)
    assert (r.state, r.value, r.note) == ("not_shown", None, "no click-and-collect store listed")


def test_pickup_is_not_offer_stock_and_store_counts_are_never_read(
    make_capture: CaptureFactory,
) -> None:
    product = _product(c_stores=[_store()], c_sizes=[_variant(False)])
    readings = readings_from_bloomingdales(_page(product, "InStock"), locale="en-AE")
    capture = make_capture(readings=tuple(readings), url="https://bloomingdales.ae/p/x")
    feed = build_feed([capture], SHOPS["bloomingdales_ae"])
    assert feed.rows[0]["availability"] == "instock"  # pickup False never reads as out of stock
    pickup = _by_key(readings)["store_availability"]
    text = json.dumps([pickup.raw_text, pickup.value, pickup.note, pickup.source_path])
    for hidden in ("stockLevel", "availableQuantity", "ats", "7", "9"):
        assert hidden not in text
