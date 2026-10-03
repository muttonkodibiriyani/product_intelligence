"""``--output-v3``: the v2 snapshot upgraded under ``beauty@1`` with offer ``listingCount``."""

from __future__ import annotations

# ruff: noqa: S101
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pi_dataset import ContentField, DatasetV3, dump_dataset, load_any
from scripts.demo_export.export import (
    V3_MAX_BYTES,
    ListingRow,
    MatchRow,
    UltaContext,
    check_v3_size,
    v3_bytes_by_group,
)
from scripts.demo_export.test_export import row
from scripts.demo_export.test_v2 import NOTE, NOW
from scripts.demo_export.v2 import build_dataset_v2, captured_fields, listing_counts, to_v3

SEPHORA, ULTA = "sephora_me", "ulta_ae"
#: A v1 early example, as ``parse_ulta_early_fixture`` builds it (invented values).
EARLY: dict[str, Any] = {
    "id": "u-early-sku-900",
    "brand": "Example Brand",
    "name": "Example Recon Sample",
    "category": "lips",
    "offers": {
        "u": {
            "sku": "sku-900",
            "url": "https://example.invalid/900",
            "rating": None,
            "series": {"price": [99.5]},
            "evidence": {
                "capturedAt": "2026-09-30T12:00:00Z",
                "source": "ulta_ae · recon fixture example.json @ abc123",
                "runId": "gulf-probe-early",
            },
        },
        "s": None,
    },
}


def rows() -> list[ListingRow]:
    """Sephora family 10: three shades at 30 ml and one 50 ml listing; Ulta family 20: one 30 ml
    listing matched to a Sephora 30 ml shade, and one unmatched 75 ml listing."""
    return [
        row(variant=101, shade="Rose"),
        row(variant=102, shade="Berry"),
        row(variant=103, shade="Nude"),
        row(variant=104, size="50"),
        row(source=ULTA, family=20, variant=200),
        row(source=ULTA, family=20, variant=201, size="75"),
    ]


MATCHES = [MatchRow(101, 200, "exact", Decimal("0.97"), "gtin-v1", "approved")]


def build(early: bool = False, listing: list[ListingRow] | None = None) -> DatasetV3:
    listing = rows() if listing is None else listing
    v2 = build_dataset_v2(
        listing,
        MATCHES,
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
        ulta_note=NOTE,
        ulta_early=[EARLY] if early else [],
    )
    v3 = load_any(dump_dataset(to_v3(v2, listing, MATCHES)))  # what main() checks before writing
    assert isinstance(v3, DatasetV3)
    return v3


def counts(ds: DatasetV3) -> dict[tuple[str, str], int | None]:
    return {(p.id, cid): o.listing_count for p in ds.products for cid, o in p.offers.items()}


def test_each_offer_states_the_listings_grouped_into_it() -> None:
    found = counts(build())
    assert sorted(found.values(), key=str) == [1, 1, 1, 3]
    pair = next(p for p, _ in found if p.startswith("m-"))
    assert (found[pair, SEPHORA], found[pair, ULTA]) == (3, 1)  # the three 30 ml shades
    assert sum(n or 0 for n in found.values()) == len(rows())  # every listing counted once


def test_counts_cover_exactly_the_collected_offers() -> None:
    assert listing_counts(rows(), MATCHES) == counts(build())


def test_an_early_recon_offer_states_no_count() -> None:
    ds = build(early=True)
    (early,) = [o for p in ds.products for o in p.offers.values() if o.early]
    assert early.listing_count is None
    assert sum(o.listing_count is not None for p in ds.products for o in p.offers.values()) == 4


def test_the_v3_document_is_the_v2_snapshot_plus_the_count() -> None:
    v3 = json.loads(dump_dataset(build()))
    assert v3["schema"] == "pi.dataset/v3"
    assert v3["meta"]["profile"]["name"] == "beauty"
    offer = v3["products"][0]["offers"][SEPHORA]
    assert offer["listingCount"] == 3
    assert offer["shadeCount"] == 3


# ---------------------------------------------------------------- Offer.content (API 1.12.0)

IMG = "https://img-product.sephora.me/{}.jpg"
GOOD_GTIN, BAD_GTIN = "4006381333931", "4006381333932"


def content_rows() -> list[ListingRow]:
    """rows() with page content on the paired Sephora 30 ml group: 101 (the representative, the
    lowest variant at the tied price) has description, gallery and a valid GTIN; 102 only
    ingredients and an invalid GTIN; 103 nothing. Ulta rows carry none."""
    base = rows()
    base[0] = replace(
        base[0],
        gtin=GOOD_GTIN,
        description="  A long-wear foundation.  ",
        images=(IMG.format(1), "https://evil.example/x.jpg", IMG.format(2), IMG.format(1)),
    )
    base[1] = replace(base[1], gtin=BAD_GTIN, ingredients="Aqua, Glycerin", description="  ")
    return base


def contents(ds: DatasetV3) -> dict[tuple[str, str], Any]:
    return {(p.id, cid): o.content for p in ds.products for cid, o in p.offers.items()}


def test_captured_fields_are_per_source() -> None:
    captured = captured_fields(content_rows())
    assert captured[SEPHORA] == tuple(ContentField)
    # Ulta rows have a shade and nothing else: the rest is not captured from Ulta.
    assert captured[ULTA] == (ContentField.SHADE,)
    assert captured_fields(rows())[SEPHORA] == (ContentField.SHADE,)


def test_an_offer_carries_its_page_content_and_its_variants() -> None:
    found = contents(build(listing=content_rows()))
    pair = next(p for p, _ in found if p.startswith("m-"))
    sephora = found[pair, SEPHORA]
    assert sephora.description == "A long-wear foundation."
    assert sephora.ingredients == "Aqua, Glycerin"  # from the next row, by sku
    # Allowlisted hosts only, page order, each URL once.
    assert [str(u) for u in sephora.images] == [IMG.format(1), IMG.format(2)]
    assert [(v.sku, v.shade, v.gtin) for v in sephora.variants] == [
        ("sku-101", "Rose", GOOD_GTIN),
        ("sku-102", "Berry", None),  # the invalid GTIN is dropped, as offline_import does
        ("sku-103", "Nude", None),
    ]
    assert sephora.family == "10"
    assert sephora.captured == tuple(ContentField)


def test_a_listing_without_content_states_what_its_source_captures() -> None:
    found = contents(build(listing=content_rows()))
    fifty = next(c for (p, cid), c in found.items() if cid == SEPHORA and not p.startswith("m-"))
    assert (fifty.description, fifty.ingredients, fifty.images) == (None, None, ())
    assert fifty.captured == tuple(ContentField)  # so the API serves not_published
    ulta = [c for (_, cid), c in found.items() if cid == ULTA]
    assert len(ulta) == 2
    assert all(c.captured == (ContentField.SHADE,) and c.description is None for c in ulta)


def test_every_collected_offer_has_content_and_early_has_none() -> None:
    ds = build(early=True, listing=content_rows())
    for p in ds.products:
        for o in p.offers.values():
            assert (o.content is None) == o.early


def test_the_byte_groups_split_the_written_body_exactly() -> None:
    ds = build(listing=content_rows())
    body = dump_dataset(ds)
    groups = v3_bytes_by_group(ds, len(body))
    assert list(groups) == ["prices", "attributes", "description+ingredients"]
    assert sum(groups.values()) == len(body)
    assert all(n > 0 for n in groups.values())
    assert v3_bytes_by_group(build(), len(dump_dataset(build())))["description+ingredients"] == 0


def test_a_body_over_the_budget_is_refused() -> None:
    groups = {"prices": V3_MAX_BYTES, "attributes": 1, "description+ingredients": 0}
    check_v3_size(V3_MAX_BYTES, groups)
    with pytest.raises(SystemExit, match="nothing was written") as refused:
        check_v3_size(V3_MAX_BYTES + 1, groups)
    assert "prices=50000000 attributes=1" in str(refused.value)
