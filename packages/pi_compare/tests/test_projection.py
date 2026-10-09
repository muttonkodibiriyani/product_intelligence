import json
from decimal import Decimal
from pathlib import Path

import pytest

from pi_compare import CaptureCompleteness, MatrixState, ValueState, build_projection
from pi_compare.models import (
    ComparisonProjection,
    ListingTokenState,
    ProductFamily,
    RetailerCell,
    VariantIdentityBasis,
)
from pi_core.enums import MatchClass, ReviewState
from pi_dataset import DatasetV3
from pi_match.matchfile import Edge, MatchFile
from pi_match.matchfile import ListingRef as MatchListingRef

FIXTURE = Path("packages/pi_api/tests/fixtures/v3-main-66bc083.json")


def dataset() -> DatasetV3:
    return DatasetV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def coverage() -> dict[str, CaptureCompleteness]:
    return {
        "shop_a": CaptureCompleteness(complete=True, basis="saved_complete_capture"),
        "shop_b": CaptureCompleteness(complete=True, basis="saved_complete_capture"),
        "shop_c": CaptureCompleteness(complete=False, basis="source_partial"),
        "shop_d": CaptureCompleteness(complete=False, basis="source_blocked"),
    }


def family_of(body: ComparisonProjection, product: str, retailer: str) -> ProductFamily:
    return next(
        family
        for family in body.families
        if any(
            listing.source_product_id == product and listing.retailer == retailer
            for listing in family.listings
        )
    )


def matrix(family: ProductFamily, retailer: str) -> RetailerCell:
    return next(cell for cell in family.matrix if cell.retailer == retailer)


def match_file(edge: Edge) -> MatchFile:
    return MatchFile(
        schema_id="pi.matches/v1",
        scope="fixture",
        vertical="beauty",
        algo_version="fixture/1",
        generated_at="2026-10-09T00:00:00Z",
        listings={"shop_a": {"p12": "fp-a"}, "shop_b": {"p14": "fp-b"}},
        unkeyed={},
        candidates=(),
        decisions=(),
        edges=(edge,),
        review=(),
    )


def external_edge(state: ReviewState = ReviewState.APPROVED) -> Edge:
    return Edge(
        a=MatchListingRef.model_validate({"retailer": "shop_a", "token": "p12"}),
        b=MatchListingRef.model_validate({"retailer": "shop_b", "token": "p14"}),
        match_class=MatchClass.FAMILY,
        review_state=state,
        decided_by="human" if state is not ReviewState.PROPOSED else None,
        confidence=Decimal("0.91"),
        method="fixture-family/1",
        reasons=("same_brand", "size_differs"),
    )


def test_accepted_edges_form_families_with_direct_evidence() -> None:
    body = build_projection(dataset(), generation="g1", completeness=coverage())
    family = family_of(body, "p01", "shop_a")

    assert {(listing.retailer, listing.source_product_id) for listing in family.listings} == {
        ("shop_a", "p01"),
        ("shop_b", "p01"),
    }
    assert len(family.evidence) == 1
    assert family.evidence[0].match_class is MatchClass.EXACT
    assert family.evidence[0].review_state is ReviewState.APPROVED
    assert family.evidence[0].left_listing_key != family.evidence[0].right_listing_key
    assert matrix(family, "shop_a").state is MatrixState.PRESENT
    assert matrix(family, "shop_b").state is MatrixState.PRESENT
    assert matrix(family, "shop_c").state is MatrixState.NOT_OBSERVED
    assert body.unkeyed_listings > 0


def test_proposed_and_rejected_edges_never_claim_presence_or_absence_wrongly() -> None:
    body = build_projection(dataset(), generation="g1", completeness=coverage())

    proposed_a = family_of(body, "p07", "shop_a")
    proposed_b = family_of(body, "p07", "shop_b")
    assert proposed_a.id != proposed_b.id
    assert matrix(proposed_a, "shop_b").state is MatrixState.AMBIGUOUS
    assert matrix(proposed_a, "shop_b").ambiguous_tokens
    assert len(proposed_a.suggestions) == 1
    assert proposed_a.suggestions[0].review_state is ReviewState.PROPOSED

    rejected_a = family_of(body, "p08", "shop_a")
    rejected_b = family_of(body, "p08", "shop_b")
    assert rejected_a.id != rejected_b.id
    assert matrix(rejected_a, "shop_b").state is MatrixState.ABSENT
    assert matrix(rejected_a, "shop_c").state is MatrixState.NOT_OBSERVED
    assert len(rejected_a.exclusions) == 1
    assert rejected_a.exclusions[0].review_state is ReviewState.REJECTED


def test_commercial_snapshot_uses_decimal_and_explicit_evidence_states() -> None:
    body = build_projection(dataset(), generation="g1", completeness=coverage())
    family = family_of(body, "p01", "shop_a")
    listing = next(item for item in family.listings if item.retailer == "shop_a")
    commercial = listing.commercial[0]

    assert commercial.current is not None
    assert commercial.current.amount == "90.00"
    assert commercial.regular is not None
    assert commercial.regular.amount == "100.00"
    assert commercial.discount.state is ValueState.OBSERVED
    assert commercial.discount.value is not None
    assert commercial.discount.value.amount.amount == "10.00"
    assert commercial.discount.value.percent == "10.0000"
    assert commercial.availability_state is ValueState.OBSERVED
    assert commercial.launch.observed_on == body.as_of.replace(day=28)
    assert commercial.captured_at.isoformat() == "2026-09-30T00:00:00+00:00"
    assert "availableVariants" not in commercial.model_dump(mode="json", by_alias=True)


def test_external_accepted_family_edge_uses_fingerprints_and_reasons() -> None:
    body = build_projection(
        dataset(),
        generation="g1",
        completeness=coverage(),
        match_file=match_file(external_edge()),
    )
    family = family_of(body, "p12", "shop_a")

    assert any(item.source_product_id == "p14" for item in family.listings)
    evidence = next(item for item in family.evidence if item.method == "fixture-family/1")
    assert evidence.left_fingerprint == "fp-a"
    assert evidence.right_fingerprint == "fp-b"
    assert evidence.reasons == ("same_brand", "size_differs")


def test_external_proposed_family_is_ambiguous_not_merged() -> None:
    body = build_projection(
        dataset(),
        generation="g1",
        completeness=coverage(),
        match_file=match_file(external_edge(ReviewState.PROPOSED)),
    )
    left = family_of(body, "p12", "shop_a")
    right = family_of(body, "p14", "shop_b")
    assert left.id != right.id
    assert matrix(left, "shop_b").state is MatrixState.AMBIGUOUS


def test_retailer_family_keeps_each_sku_and_raw_axes() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    product = next(item for item in raw["products"] if item["id"] == "p12")
    product["offers"]["shop_a"]["content"] = {
        "captured": ["shade"],
        "description": None,
        "ingredients": None,
        "images": [],
        "variants": [
            {"sku": "shade-rose", "shade": "Rosé Glow", "gtin": None},
            {"sku": "shade-plum", "shade": "Plum", "gtin": None},
        ],
        "family": "retailer-line-1",
    }
    sibling = json.loads(json.dumps(product))
    sibling["id"] = "p17"
    sibling["name"] = "Product p12 Large"
    sibling["offers"]["shop_a"]["size"] = {
        "value": "100",
        "unit": "ml",
        "label": None,
        "system": None,
    }
    sibling["offers"]["shop_a"]["content"]["variants"] = [
        {"sku": "large-rose", "shade": "Rosé Glow", "gtin": None}
    ]
    raw["products"].append(sibling)
    body = build_projection(DatasetV3.model_validate(raw), generation="g1", completeness=coverage())
    family = family_of(body, "p12", "shop_a")

    assert {item.source_product_id for item in family.listings} >= {"p12", "p17"}
    evidence = family.retailer_family_evidence[0]
    assert evidence.retailer_family_id == "retailer-line-1"
    p12 = next(item for item in family.listings if item.source_product_id == "p12")
    assert p12.token_state is ListingTokenState.KEYED
    assert len(p12.variants) == 2
    assert {variant.identity_basis for variant in p12.variants} == {
        VariantIdentityBasis.CONTENT_VARIANT
    }
    assert {variant.retailer_sku for variant in p12.variants} == {
        "shade-rose",
        "shade-plum",
    }
    rose = next(variant for variant in p12.variants if variant.retailer_sku == "shade-rose")
    assert any(axis.raw == "Rosé Glow" and axis.canonical == "rose glow" for axis in rose.axes)


def test_projection_is_byte_stable_and_requires_complete_capture_inputs() -> None:
    first = build_projection(dataset(), generation="g1", completeness=coverage())
    again = build_projection(dataset(), generation="g1", completeness=coverage())
    assert first.model_dump_json(by_alias=True) == again.model_dump_json(by_alias=True)

    incomplete = coverage()
    incomplete.pop("shop_d")
    with pytest.raises(ValueError, match="required for every retailer"):
        build_projection(dataset(), generation="g1", completeness=incomplete)


def test_match_file_scope_is_checked() -> None:
    file = match_file(external_edge()).model_copy(update={"scope": "other"})
    with pytest.raises(ValueError, match="is not for"):
        build_projection(dataset(), generation="g1", completeness=coverage(), match_file=file)
