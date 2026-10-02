"""``--output-v3``: the v2 snapshot upgraded under ``beauty@1`` with offer ``listingCount``."""

from __future__ import annotations

# ruff: noqa: S101
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pi_dataset import DatasetV3, dump_dataset, load_any
from scripts.demo_export.export import ListingRow, MatchRow, UltaContext
from scripts.demo_export.test_export import row
from scripts.demo_export.test_v2 import NOTE, NOW
from scripts.demo_export.v2 import build_dataset_v2, listing_counts, to_v3

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


def build(early: bool = False) -> DatasetV3:
    v2 = build_dataset_v2(
        rows(),
        MATCHES,
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
        ulta_note=NOTE,
        ulta_early=[EARLY] if early else [],
    )
    v3 = load_any(dump_dataset(to_v3(v2, rows(), MATCHES)))  # what main() checks before writing
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
