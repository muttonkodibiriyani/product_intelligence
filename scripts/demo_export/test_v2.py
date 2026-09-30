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
from scripts.demo_export.v2 import build_dataset_v2, product_id

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
