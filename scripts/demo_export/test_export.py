from __future__ import annotations

# ruff: noqa: S101, PLR0913
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.demo_export.export import (
    ULTA_BLOCKED_NOTE,
    ULTA_BLOCKED_NOTE_AR,
    ListingRow,
    MatchRow,
    UltaContext,
    build_dataset,
    choose_representative,
    contains_secret,
    group_rows,
    json_money,
    matched_products,
    offer_for,
    parse_size_label,
    parse_ulta_early_fixture,
    parser,
    psycopg_database_url,
)

NOW = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)


def row(
    *,
    source: str = "sephora_me",
    family: int = 10,
    variant: int = 100,
    price: str = "100",
    regular: str | None = "125",
    availability: str = "unknown",
    shade: str | None = "Rose",
    size: str | None = "30",
    unit: str | None = "ml",
) -> ListingRow:
    return ListingRow(
        source_name=source,
        family_id=str(family),
        variant_id=variant,
        source_listing_key=f"key-{variant}",
        source_sku=f"sku-{variant}",
        url=f"https://example.invalid/{variant}",
        name="Example Product",
        brand="Example Brand",
        category="foundation",
        category_path="Makeup/Foundation",
        shade=shade,
        shade_family="Medium" if shade else None,
        shade_hex="#AABBCC" if shade else None,
        size_value=Decimal(size) if size else None,
        size_unit=unit,
        size_label=None,
        price=Decimal(price),
        regular=Decimal(regular) if regular else None,
        price_type="promotional" if regular else "full",
        availability=availability,
        rating=Decimal("4.4"),
        rating_scale=Decimal("5"),
        rating_count=42,
        observed_at=NOW,
        evidence_retrieved_at=NOW,
        run_id=7,
        run_status="succeeded",
        coverage_status="supported",
    )


def match(
    variant_a: int,
    variant_b: int,
    score: str,
    *,
    match_class: str = "exact",
    review_state: str = "proposed",
) -> MatchRow:
    return MatchRow(
        variant_a=variant_a,
        variant_b=variant_b,
        match_class=match_class,
        score=Decimal(score),
        algo_version="m2",
        review_state=review_state,
    )


def test_representative_prefers_in_stock_before_lower_unknown_price() -> None:
    unknown = row(variant=101, price="80", availability="unknown")
    available = row(variant=102, price="90", availability="in_stock")
    assert choose_representative([unknown, available]) == available


def test_grouping_separates_pack_sizes_and_collapses_shades() -> None:
    groups = group_rows(
        [
            row(variant=101, shade="Rose"),
            row(variant=102, shade="Berry"),
            row(variant=103, size="50"),
        ]
    )
    assert sorted(len(rows) for rows in groups.values()) == [1, 2]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("50 ml", ("ml", Decimal("50"))),
        ("250 ML", ("ml", Decimal("250"))),
        ("2 x 50 ml", (None, None)),
        ("1.7 oz", (None, None)),
        (None, (None, None)),
    ],
)
def test_size_label_parser_never_guesses_sets_or_conversions(
    label: str | None, expected: tuple[str | None, Decimal | None]
) -> None:
    assert parse_size_label(label) == expected


def test_known_and_unknown_sizes_sort_deterministically() -> None:
    rows = [row(variant=101), row(variant=102, size=None, unit=None)]
    first = matched_products(group_rows(rows), [])
    second = matched_products(group_rows(reversed(rows)), [])
    assert [product["id"] for product in first] == [product["id"] for product in second]


def test_many_to_one_matches_keep_highest_confidence() -> None:
    rows = [
        row(source="ulta_ae", family=1, variant=1),
        row(source="ulta_ae", family=2, variant=2),
        row(source="sephora_me", family=3, variant=3),
    ]
    products = matched_products(
        group_rows(rows),
        [
            match(1, 3, "0.8"),
            match(2, 3, "0.9"),
        ],
    )
    assert len(products) == 2
    matched = next(product for product in products if product["match"])
    assert matched["match"]["confidence"] == 0.9
    assert matched["match"]["matchClass"] == "exact"
    assert matched["match"]["reviewState"] == "proposed"
    assert "early" not in matched["offers"]["u"]


@pytest.mark.parametrize(
    ("ulta", "sephora", "match_class"),
    [
        (row(source="ulta_ae", variant=1, size="30"), row(variant=2, size="50"), "exact"),
        (row(source="ulta_ae", variant=1, unit="g"), row(variant=2, unit="ml"), "exact"),
        (row(source="ulta_ae", variant=1, size=None, unit=None), row(variant=2), "exact"),
        (row(source="ulta_ae", variant=1), row(variant=2), "substitute"),
    ],
)
def test_unsafe_match_does_not_merge(
    ulta: ListingRow, sephora: ListingRow, match_class: str
) -> None:
    products = matched_products(
        group_rows([ulta, sephora]),
        [match(ulta.variant_id, sephora.variant_id, "0.99", match_class=match_class)],
    )
    assert len(products) == 2
    assert all(product["match"] is None for product in products)


def test_null_size_is_preserved_and_marked_not_published() -> None:
    dataset = build_dataset(
        [row(size=None, unit=None)],
        [],
        generated_at=NOW,
        ulta=UltaContext(blocked_since=NOW),
    )
    product = dataset["products"][0]
    assert product["unit"] is None
    assert product["offers"]["s"]["size"] is None
    assert dataset["meta"]["fields"]["size"] == "not_published"


def test_secret_detector_checks_embedded_request_material() -> None:
    assert contains_secret({"request": {"headers": {"x-algolia-api-key": "secret"}}})
    assert contains_secret({"algoliaConfig": "secret"})
    assert contains_secret({"url": "https://example.invalid/search?api_key=secret"})
    assert not contains_secret({"source": "sephora_me"})


def test_parse_committed_redacted_ulta_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.html"
    fixture.write_text(
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Blush","sku":"U1","brand":{"name":"Morphe"},'
        '"offers":[{"sku":"U1","price":81,"url":"https://example.invalid/u1"}],'
        '"aggregateRating":{"ratingValue":4.6,"reviewCount":10}}'
        "</script>"
        '<script type="application/ld+json">'
        '{"@type":"BreadcrumbList","itemListElement":['
        '{"item":{"name":"Makeup"}},{"item":{"name":"Blush"}}]}'
        "</script>",
        encoding="utf-8",
    )
    product = parse_ulta_early_fixture(fixture, NOW, "abc123")
    assert product["offers"]["u"]["early"] is True
    assert product["offers"]["u"]["series"]["price"] == [81]
    assert product["category"] == "cheek"
    assert "fixture.html @ abc123" in product["offers"]["u"]["evidence"]["source"]


def test_empty_dataset_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_dataset([], [], generated_at=NOW, ulta=UltaContext(blocked_since=NOW))


def test_missing_price_stays_null_instead_of_becoming_zero() -> None:
    missing = row()
    missing = ListingRow(**(missing.__dict__ | {"price": None, "regular": None}))
    dataset = build_dataset([missing], [], generated_at=NOW, ulta=UltaContext(blocked_since=NOW))
    offer = dataset["products"][0]["offers"]["s"]
    assert offer["series"] == {"price": [None]}
    assert "rawPrice" not in offer["evidence"]
    assert dataset["meta"]["fields"]["price"] == "not_collected"


def test_unpublished_regular_price_is_not_invented_from_current_price() -> None:
    dataset = build_dataset(
        [row(regular=None)], [], generated_at=NOW, ulta=UltaContext(blocked_since=NOW)
    )
    series = dataset["products"][0]["offers"]["s"]["series"]
    assert series == {"price": [100]}
    assert dataset["meta"]["fields"]["regular"] == "not_collected"


def test_workspace_sqlalchemy_database_url_is_accepted() -> None:
    value = "postgresql+psycopg://pi:password@127.0.0.1:55432/pi"
    assert psycopg_database_url(value) == "postgresql://pi:password@127.0.0.1:55432/pi"


def test_aed_json_money_is_limited_to_two_decimal_places() -> None:
    assert json_money(Decimal("12.50")) == 12.5
    with pytest.raises(ValueError, match="more than two"):
        json_money(Decimal("12.501"))


def test_missing_rating_count_does_not_become_zero() -> None:
    missing_count = row()
    missing_count = ListingRow(**(missing_count.__dict__ | {"rating_count": None}))
    dataset = build_dataset(
        [missing_count], [], generated_at=NOW, ulta=UltaContext(blocked_since=NOW)
    )
    assert dataset["products"][0]["offers"]["s"]["rating"] is None


def test_recon_count_requires_a_source_and_is_cited() -> None:
    with pytest.raises(ValueError, match="count and source"):
        build_dataset(
            [row()],
            [],
            generated_at=NOW,
            ulta=UltaContext(blocked_since=NOW, recon_observed_count=3),
        )
    dataset = build_dataset(
        [row()],
        [],
        generated_at=NOW,
        ulta=UltaContext(
            blocked_since=NOW,
            recon_observed_count=3,
            recon_source="docs/recon/gulf_probe_results.md @ abc123",
        ),
    )
    note = dataset["meta"]["retailers"][0]["note"]["en"]
    assert "3 products" in note
    assert "gulf_probe_results.md @ abc123" in note

    assert note.endswith(ULTA_BLOCKED_NOTE)


def test_blocked_ulta_without_recon_is_the_owner_status_line_only() -> None:
    dataset = build_dataset([row()], [], generated_at=NOW, ulta=UltaContext(blocked_since=NOW))
    ulta = dataset["meta"]["retailers"][0]
    assert ulta["status"] == "blocked"
    assert ulta["note"] == {"en": ULTA_BLOCKED_NOTE, "ar": ULTA_BLOCKED_NOTE_AR}
    assert ULTA_BLOCKED_NOTE == (
        "ulta.ae: blocked by site security (Cloudflare) via Gulf datacenter and UAE residential; "
        "0 products"
    )
    assert not [p for p in dataset["products"] if "u" in p["offers"] and p["offers"]["u"]]


def test_blocked_note_is_data_from_the_cli() -> None:
    args = parser().parse_args(
        ["--database-url", "x", "--output", "o.json", "--ulta-blocked-note", "custom"]
    )
    assert args.ulta_blocked_note == "custom"
    assert args.ulta_blocked_note_ar == ULTA_BLOCKED_NOTE_AR
    dataset = build_dataset(
        [row()],
        [],
        generated_at=NOW,
        ulta=UltaContext(blocked_since=NOW, blocked_note="custom", blocked_note_ar="مخصص"),
    )
    assert dataset["meta"]["retailers"][0]["note"] == {"en": "custom", "ar": "مخصص"}


def test_real_ulta_rows_are_partial_not_early() -> None:
    ulta = row(source="ulta_ae")
    ulta = ListingRow(**(ulta.__dict__ | {"run_status": "running", "coverage_status": "partial"}))
    dataset = build_dataset([ulta], [], generated_at=NOW, ulta=UltaContext(blocked_since=NOW))
    assert dataset["meta"]["retailers"][0]["status"] == "partial"
    assert "early" not in dataset["products"][0]["offers"]["u"]
    assert "notObserved" not in dataset


def test_offer_evidence_dates_the_price_not_a_newer_stock_read() -> None:
    page_time = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    listing = row(availability="in_stock")
    price_row = {"price_observed_at": page_time, "price_run_id": 5}
    listing = ListingRow(**(listing.__dict__ | price_row))
    evidence = offer_for([listing])["evidence"]
    assert (evidence["capturedAt"], evidence["runId"]) == ("2026-09-30T18:00:00Z", "5")
    assert offer_for([row()])["evidence"]["runId"] == "7"  # no price row: the newest row
