from __future__ import annotations

# ruff: noqa: S101
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pi_dataset import DatasetError, RetailerStatus, dump_dataset, load_dataset
from scripts.demo_export.export import (
    ULTA_BLOCKED_NOTE,
    ULTA_BLOCKED_NOTE_AR,
    ListingRow,
    MatchRow,
    UltaContext,
    build_dataset,
)
from scripts.demo_export.test_export import row
from scripts.demo_export.v2 import build_dataset_v2, category_notes, price_review, product_id

NOW = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
NOTE = {"en": ULTA_BLOCKED_NOTE, "ar": ULTA_BLOCKED_NOTE_AR}


def build(rows: list[ListingRow], matches: list[MatchRow] | None = None, **kw: Any) -> bytes:
    ds = build_dataset_v2(
        rows,
        matches or [],
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
        ulta_note=NOTE,
        **kw,
    )
    body = dump_dataset(ds)
    load_dataset(body)  # exactly what the publisher and the API do
    return body


def doc(rows: list[ListingRow], matches: list[MatchRow] | None = None) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(build(rows, matches))
    return loaded


def only_offer(d: dict[str, Any]) -> dict[str, Any]:
    (product,) = d["products"]
    (offer,) = product["offers"].values()
    found: dict[str, Any] = offer
    return found


def test_the_v2_document_passes_the_strict_load_and_names_retailers_by_register_key() -> None:
    d = doc([row()])
    assert d["schema"] == "pi.dataset/v2"
    meta = d["meta"]
    assert [r["id"] for r in meta["retailers"]] == ["ulta_ae", "sephora_me"]
    assert meta["markets"] == [
        {"country": "AE", "currency": "AED", "timeZone": "Asia/Dubai", "locales": ["en", "ar"]}
    ]
    assert meta["test"] is False
    assert list(d["products"][0]["offers"]) == ["sephora_me"]


def test_money_is_exact_text_and_there_is_no_promo_series() -> None:
    series = only_offer(doc([row(price="99.5", regular="125")]))["series"]
    assert series["price"] == [{"amount": "99.50", "minor": 9950, "currency": "AED"}]
    assert series["regular"] == [{"amount": "125.00", "minor": 12500, "currency": "AED"}]
    assert "promo" not in series


def test_no_json_floats_anywhere() -> None:
    rated = ListingRow(
        **(
            row().__dict__
            | {"rating": Decimal("4.35"), "rating_scale": Decimal(5), "rating_count": 7}
        )
    )
    body = build([rated]).decode()
    json.loads(body, parse_float=lambda text: pytest.fail(f"float {text}"))


def test_ratings_keep_their_own_scale() -> None:
    rated = ListingRow(
        **(
            row().__dict__
            | {"rating": Decimal(87), "rating_scale": Decimal(100), "rating_count": 3}
        )
    )
    assert only_offer(doc([rated]))["rating"] == {"average": "87", "scale": "100", "count": 3}


@pytest.mark.parametrize(("state", "published"), [("not_observed", None), ("in_stock", "in_stock")])
def test_availability_uses_null_for_not_observed(state: str, published: str | None) -> None:
    d = doc([row(availability=state)])
    assert only_offer(d)["series"]["availability"] == [published]
    assert d["meta"]["capabilities"]["stock"] is (published is not None)


def test_a_zero_price_is_not_observed_and_reported_as_a_parse_failure() -> None:
    d = doc([row(price="0", regular=None)])
    assert only_offer(d)["series"]["price"] == [None]
    assert d["meta"]["fields"]["price"] == "parse_failure"


def test_blocked_ulta_is_blocked_with_the_owner_note_and_a_local_window() -> None:
    meta = doc([row()])["meta"]
    ulta = meta["retailers"][0]
    assert ulta["status"] == RetailerStatus.BLOCKED
    assert ulta["note"] == NOTE
    assert ulta["since"] == "2026-10-01"  # 20:55Z on the 30th is past midnight in Dubai
    assert meta["dates"] == ["2026-10-01"]


def test_dates_are_the_cutoffs_calendar_day_in_dubai() -> None:
    noon = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    early = ListingRow(**(row().__dict__ | {"observed_at": noon, "evidence_retrieved_at": noon}))
    d = json.loads(build([early]))
    assert d["meta"]["dates"] == ["2026-09-30"]
    assert d["meta"]["cutoff"] == "2026-09-30T12:00:00Z"


def matched(state: str, *, human: bool) -> dict[str, Any]:
    sephora = row(variant=100)
    ulta = row(source="ulta_ae", family=20, variant=200)
    match = MatchRow(100, 200, "exact", Decimal("0.97"), "gtin-v1", state, human=human)
    (product,) = doc([sephora, ulta], [match])["products"]
    found: dict[str, Any] = product
    return found


@pytest.mark.parametrize(
    ("state", "human", "decided"),
    [
        ("proposed", False, None),
        ("approved", False, "auto"),
        ("approved", True, "human"),
        ("locked", True, "human"),
    ],
)
def test_match_edges_carry_the_db_state_verbatim_and_who_decided(
    state: str, human: bool, decided: str | None
) -> None:
    product = matched(state, human=human)
    assert sorted(product["offers"]) == ["sephora_me", "ulta_ae"]
    (edge,) = product["matches"]
    assert edge == {
        "a": "sephora_me",
        "b": "ulta_ae",
        "matchClass": "exact",
        "reviewState": state,
        "decidedBy": decided,
        "confidence": "0.97",
        "method": "gtin-v1",
        "stage": "first-pass",
    }


def test_a_locked_edge_without_a_recorded_reviewer_is_refused() -> None:
    with pytest.raises(ValueError, match="locked edge is decided by a human"):
        matched("locked", human=False)


def test_v1_and_v2_have_the_same_products() -> None:
    rows = [
        row(variant=100),
        row(source="ulta_ae", family=20, variant=200),
        row(family=11, variant=101),
    ]
    matches = [MatchRow(100, 200, "exact", Decimal("0.9"), "gtin-v1", "approved")]
    v1 = build_dataset(rows, matches, generated_at=NOW, ulta=UltaContext(blocked_since=NOW))
    v2 = json.loads(build(rows, matches))
    assert [p["id"] for p in v2["products"]] == [p["id"] for p in v1["products"]]


def test_ids_that_are_not_valid_v2_ids_are_hashed_stably() -> None:
    assert product_id("s-10-30-ml") == "s-10-30-ml"
    odd = product_id("s-fam ily/é-30-ml")
    assert odd.startswith("p-")
    assert odd == product_id("s-fam ily/é-30-ml")


def test_credential_like_scraped_text_blocks_the_export() -> None:
    leaky = ListingRow(**(row().__dict__ | {"name": "Serum x-algolia-api-key"}))
    with pytest.raises(DatasetError, match="credential-like"):
        build([leaky])


def at(when: datetime, **changes: Any) -> ListingRow:
    base = row(**changes)
    return ListingRow(**(base.__dict__ | {"observed_at": when, "evidence_retrieved_at": when}))


def test_a_value_captured_on_another_day_is_null_never_carried_forward() -> None:
    """Contract rule 6: Sephora on 30 Sep, Ulta on 28 Sep -> only Sephora has values on 30 Sep."""
    fresh = at(datetime(2026, 9, 30, 10, 0, tzinfo=UTC), availability="in_stock")
    old = at(
        datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
        source="ulta_ae",
        family=20,
        variant=200,
        availability="in_stock",
    )
    d = doc([fresh, old])
    assert d["meta"]["dates"] == ["2026-09-30"]
    offers = {rid: o for p in d["products"] for rid, o in p["offers"].items()}
    assert offers["sephora_me"]["series"]["price"] == [
        {"amount": "100.00", "minor": 10000, "currency": "AED"}
    ]
    assert offers["sephora_me"]["series"]["availability"] == ["in_stock"]
    assert offers["ulta_ae"]["series"]["price"] == [None]
    assert "regular" not in offers["ulta_ae"]["series"] or offers["ulta_ae"]["series"][
        "regular"
    ] in (None, [None])
    assert offers["ulta_ae"]["series"]["availability"] == [None]
    assert offers["ulta_ae"]["evidence"]["capturedAt"] == "2026-09-28T12:00:00Z"
    fields = d["meta"]["fields"]
    assert (fields["price"], fields["regular"], fields["stock"]) == ("partial",) * 3


def test_stock_has_its_own_capture_time() -> None:
    """A fresh stock observation keeps its value; an old price does not ride along with it."""
    today = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    base = at(today, availability="in_stock")
    mixed = ListingRow(
        **(
            base.__dict__
            | {
                "price_observed_at": datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
                "price_evidence_retrieved_at": datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
                "price_run_id": 3,
            }
        )
    )
    d = doc([mixed])
    offer = only_offer(d)
    assert offer["series"]["price"] == [None]
    assert offer["series"]["availability"] == ["in_stock"]
    # The evidence is the observation that was published: the stock one, not the old price.
    assert offer["evidence"]["capturedAt"] == "2026-09-30T10:00:00Z"
    assert offer["evidence"]["runId"] == "7"
    assert d["meta"]["fields"]["price"] == "partial"
    assert d["meta"]["fields"]["stock"] == "ok"


def test_ulta_stays_blocked_even_when_older_ulta_rows_exist() -> None:
    d = doc([row(), row(source="ulta_ae", family=20, variant=200)])
    ulta = d["meta"]["retailers"][0]
    assert ulta["status"] == RetailerStatus.BLOCKED
    assert ulta["note"] == NOTE
    assert [w["retailer"] for w in d["notObserved"]] == ["ulta_ae"]


def test_size_is_partial_when_only_some_products_have_one() -> None:
    fields = doc([row(), row(family=11, variant=101, size=None, unit=None)])["meta"]["fields"]
    assert fields["size"] == "partial"


def test_an_old_stock_state_behind_a_fresh_page_read_is_null() -> None:
    """The reviewer's case: a 28 Sep stock read plus today's not_observed page read."""
    today = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    old = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    base = at(today, availability="in_stock")
    stale_stock = ListingRow(
        **(
            base.__dict__
            | {"stock_observed_at": old, "stock_evidence_retrieved_at": old, "stock_run_id": 2}
        )
    )
    d = doc([stale_stock])
    offer = only_offer(d)
    assert offer["series"]["availability"] == [None]
    assert offer["series"]["price"][0] is not None
    assert offer["evidence"]["capturedAt"] == "2026-09-30T10:00:00Z"
    assert d["meta"]["fields"]["stock"] == "partial"


def test_regular_is_partial_when_every_regular_was_stale() -> None:
    old = at(datetime(2026, 9, 28, 12, 0, tzinfo=UTC), family=11, variant=101)
    fresh = at(datetime(2026, 9, 30, 10, 0, tzinfo=UTC), regular=None)
    fields = doc([fresh, old])["meta"]["fields"]
    assert fields["regular"] == "partial"


def test_ulta_status_follows_its_rows_once_the_owner_says_unblocked() -> None:
    ds = build_dataset_v2(
        [row(), row(source="ulta_ae", family=20, variant=200)],
        [],
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC), blocked=False),
        ulta_note=NOTE,
    )
    d = json.loads(dump_dataset(ds))
    assert d["meta"]["retailers"][0]["status"] == RetailerStatus.SUPPORTED
    assert d["meta"]["retailers"][0]["since"] is None
    assert d["notObserved"] == []


SEPHORA_IMG = "https://img-product.sephora.me/dw/image/v2/BKWK_PRD/p1.jpg?sw=1248&sh=1248"


def with_image(url: str | None, **kw: Any) -> ListingRow:
    return ListingRow(**(row(**kw).__dict__ | {"image": url}))


def test_the_main_image_is_the_offer_and_product_thumbnail() -> None:
    d = doc([with_image(SEPHORA_IMG)])
    assert only_offer(d)["image"] == SEPHORA_IMG
    assert d["products"][0]["image"] == SEPHORA_IMG
    assert d["meta"]["capabilities"]["images"] is True
    assert d["meta"]["fields"]["image"] == "ok"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "?sw=1248&sh=1248&sm=fit&q=85",  # the relative swatch junk seen in pi_db
        "http://img-product.sephora.me/p1.jpg",
        "https://img-product.sephora.me.evil.test/p1.jpg",
        "https://cdn.example.test/p1.jpg",
        "https://user@img-product.sephora.me/p1.jpg",
        "https://img-product.sephora.me:8443/p1.jpg",
        "https://img-product.sephora.me/p1.jpg#x",
        "https://img-product.sephora.me/p1.jpg#",
        # the retailer's "no image" placeholder is not a product image
        "https://img-product.sephora.me/dw/image/v2/BKWK_PRD/images/noimagemedium.png",
        "https://img-product.sephora.me/images/NoImageLarge.png?sw=1248",
    ],
)
def test_an_image_off_the_allowlist_is_null_never_guessed(url: str | None) -> None:
    d = doc([with_image(url)])
    assert only_offer(d)["image"] is None
    assert d["products"][0]["image"] is None
    assert d["meta"]["capabilities"]["images"] is False
    assert d["meta"]["fields"]["image"] == "not_collected"


ULTA_IMG = "https://media.alshaya.com/adobe/assets/urn:aaid:aem:0000/as/p1.jpg?width=450"


def test_an_ulta_image_on_its_own_cdn_is_published_for_ulta() -> None:
    d = doc([with_image(ULTA_IMG, source="ulta_ae", family=20, variant=200)])
    assert only_offer(d)["image"] == ULTA_IMG
    assert d["products"][0]["image"] == ULTA_IMG
    assert d["meta"]["capabilities"]["images"] is True
    assert d["meta"]["fields"]["image"] == "ok"


@pytest.mark.parametrize("source", ["ulta_ae", "ulta_ae_owner_import", "ulta"])
def test_the_image_host_follows_the_retailer_not_the_raw_source_name(source: str) -> None:
    """An Ulta source named other than exactly ulta_ae still gets the Ulta host (never a silent
    null); the allowlist is keyed by the retailer's register key."""
    d = doc([with_image(ULTA_IMG, source=source, family=20, variant=200)])
    assert only_offer(d)["image"] == ULTA_IMG


@pytest.mark.parametrize(
    ("url", "source"),
    [
        (SEPHORA_IMG, "ulta_ae"),  # a Sephora URL on an Ulta offer
        (ULTA_IMG, "sephora_me"),  # an Ulta URL on a Sephora offer
        ("http://media.alshaya.com/p1.jpg", "ulta_ae"),
        ("https://user@media.alshaya.com/p1.jpg", "ulta_ae"),
        ("https://media.alshaya.com.evil.test/p1.jpg", "ulta_ae"),
    ],
)
def test_an_image_on_another_retailers_host_is_null(url: str, source: str) -> None:
    d = doc([with_image(url, source=source, family=20, variant=200)])
    assert only_offer(d)["image"] is None
    assert d["products"][0]["image"] is None
    assert d["meta"]["capabilities"]["images"] is False
    assert d["meta"]["fields"]["image"] == "not_collected"


def test_image_is_partial_when_only_some_products_have_one() -> None:
    d = doc([with_image(SEPHORA_IMG), with_image(None, family=11, variant=101)])
    assert d["meta"]["fields"]["image"] == "partial"
    assert d["meta"]["capabilities"]["images"] is True


def with_path(path: str | None, **kw: Any) -> ListingRow:
    return ListingRow(**(row(**kw).__dict__ | {"category_path": path}))


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("Makeup > Face > Foundation", ["foundation", "Makeup", "Face", "Foundation"]),
        ("Fragrance > Unisex Fragrances", ["foundation", "Fragrance", "Unisex Fragrances"]),
        ("A > B > C > D > E", ["foundation", "A", "B", "C"]),  # cut after three levels
        (
            "BRANDS > Brands > Chanel > MAKEUP > Lips > Lipsticks",
            ["foundation", "MAKEUP", "Lips", "Lipsticks"],
        ),
        ("BRANDS > Brands > Chanel", ["foundation"]),  # nothing left after the brand prefix
        ("brands > Brands > Chanel > Lips", ["foundation", "brands", "Brands", "Chanel"]),
        ("Makeup > BRANDS > Brands > X", ["foundation", "Makeup", "BRANDS", "Brands"]),
        ("Fragrance > For Him > ", ["foundation", "Fragrance", "For Him"]),
        (" > ", ["foundation"]),
        ("PID Unicity", ["foundation"]),
        ("without_pid", ["foundation"]),
        # a mid-path pseudo-crumb is spliced out, not turned into (code,)
        ("Makeup > PID Unicity > Lips", ["foundation", "Makeup", "Lips"]),
        (None, ["foundation"]),
    ],
)
def test_category_is_the_code_then_the_retailers_breadcrumb(
    path: str | None, category: list[str]
) -> None:
    assert doc([with_path(path)])["products"][0]["category"] == category


def test_a_matched_pair_takes_the_naming_offers_breadcrumb() -> None:
    sephora = with_path("Makeup > Lips > Lipstick")
    ulta = with_path("Lips > Other", source="ulta_ae", family=20, variant=200)
    pair = MatchRow(100, 200, "exact", Decimal("0.97"), "gtin-v1", "approved", human=True)
    d = doc([sephora, ulta], [pair])
    assert [p["category"] for p in d["products"]] == [["foundation", "Makeup", "Lips", "Lipstick"]]


def test_the_run_log_counts_cut_and_cleaned_breadcrumbs() -> None:
    paths = ["A > B > C > D", "BRANDS > Brands > Chanel > MAKEUP > Lips", "PID Unicity", "A > B"]
    rows = [with_path(path, variant=100 + i) for i, path in enumerate(paths)]
    assert category_notes(rows) == {"internal": 1, "brand_nav": 1, "truncated": 1}


def test_an_image_whose_name_merely_contains_swatch_is_a_product_image() -> None:
    # Sephora's per-SKU packshot is ``.../hi-res/SKU/<sku>_swatch.jpg`` (the page's own
    # schema.org image); the colour chip is a separate ``swatchImage``, never the main role.
    url = "https://img-product.sephora.me/dw/image/v2/BKWK_PRD/images/hi-res/SKU/100_swatch.jpg"
    assert only_offer(doc([with_image(url)]))["image"] == url


def named(name: str, brand: str, **kw: Any) -> ListingRow:
    return ListingRow(**(row(**kw).__dict__ | {"name": name, "brand": brand}))


def test_names_and_brands_are_tidied_for_display_only() -> None:
    rows = [
        named("Shu Uemura  Ultime8\u00a0Cleansing Oil ", "Shu Uemura", family=1, variant=1),
        named("Shu Uemura Ultime8 Cleansing Oil", "Shu Uemura", family=1, variant=2),
        named("Art Of Brow", "SHU UEMURA", family=2, variant=3),
    ]
    d = doc(rows)
    assert [(p["brand"], p["name"]) for p in d["products"]] == [
        ("Shu Uemura", "Ultime8 Cleansing Oil"),
        ("Shu Uemura", "Art Of Brow"),
    ]
    assert rows[0].name == "Shu Uemura  Ultime8\u00a0Cleansing Oil "  # the rows are untouched


def test_v1_shows_the_same_tidied_names_as_v2() -> None:
    rows = [named("Brand - Lip Oil", "BRAND", family=1, variant=1)]
    v1 = build_dataset(
        rows,
        [],
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
    )
    assert [(p["brand"], p["name"]) for p in v1["products"]] == [("BRAND", "Lip Oil")]
    assert [(p["brand"], p["name"]) for p in doc(rows)["products"]] == [("BRAND", "Lip Oil")]


def test_prices_outside_the_review_band_are_listed_never_changed() -> None:
    rows = [
        row(family=1, variant=1, price="0.50", regular=None),
        row(family=2, variant=2, price="1", regular=None),
        row(family=3, variant=3, price="3000", regular=None),
        row(family=4, variant=4, price="8943", regular=None),
    ]
    ds = build_dataset_v2(
        rows,
        [],
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
        ulta_note=NOTE,
    )
    assert price_review(ds) == {"below": ["sku-1"], "above": ["sku-4"]}
    prices = sorted(
        price.amount
        for p in ds.products
        if (price := p.offers["sephora_me"].series.price[0]) is not None
    )
    assert prices == ["0.50", "1.00", "3000.00", "8943.00"]
