from __future__ import annotations

# ruff: noqa: S101, PLR0913
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.demo_export.export import (
    ListingRow,
    MatchRow,
    build_dataset,
    choose_representative,
    contains_secret,
    group_rows,
    matched_products,
    parse_ulta_early_fixture,
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
        family_id=family,
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
            MatchRow(variant_a=1, variant_b=3, score=Decimal("0.8"), algo_version="m2"),
            MatchRow(variant_a=2, variant_b=3, score=Decimal("0.9"), algo_version="m2"),
        ],
    )
    assert len(products) == 2
    matched = next(product for product in products if product["match"])
    assert matched["match"]["confidence"] == 0.9
    assert matched["offers"]["u"]["early"] is True


def test_null_size_is_preserved_and_marked_not_published() -> None:
    dataset = build_dataset(
        [row(size=None, unit=None)],
        [],
        generated_at=NOW,
        ulta_blocked_since=NOW,
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
        "</script>",
        encoding="utf-8",
    )
    product = parse_ulta_early_fixture(fixture, NOW)
    assert product["offers"]["u"]["early"] is True
    assert product["offers"]["u"]["series"]["price"] == [81]


def test_empty_dataset_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_dataset([], [], generated_at=NOW, ulta_blocked_since=NOW)


def test_missing_price_stays_null_instead_of_becoming_zero() -> None:
    missing = row()
    missing = ListingRow(**(missing.__dict__ | {"price": None, "regular": None}))
    dataset = build_dataset([missing], [], generated_at=NOW, ulta_blocked_since=NOW)
    offer = dataset["products"][0]["offers"]["s"]
    assert offer["series"] == {"price": [None]}
    assert "rawPrice" not in offer["evidence"]
    assert dataset["meta"]["fields"]["price"] == "not_collected"


def test_unpublished_regular_price_is_not_invented_from_current_price() -> None:
    dataset = build_dataset([row(regular=None)], [], generated_at=NOW, ulta_blocked_since=NOW)
    series = dataset["products"][0]["offers"]["s"]["series"]
    assert series == {"price": [100]}
    assert dataset["meta"]["fields"]["regular"] == "not_collected"


def test_workspace_sqlalchemy_database_url_is_accepted() -> None:
    value = "postgresql+psycopg://pi:password@127.0.0.1:55432/pi"
    assert psycopg_database_url(value) == "postgresql://pi:password@127.0.0.1:55432/pi"
