"""taxonomy@1: breadcrumb levels to a common category and a bucket."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pi_metrics import taxonomy
from pi_metrics.taxonomy import BUCKETS, COMMON, Level, Placement, Unmapped, classify, label


@pytest.mark.parametrize(
    ("category", "common", "bucket"),
    [
        (("lips", "Makeup", "Lips", "Lipstick"), "lipstick", "lips"),
        (("lips", "Makeup", "Lips", "Lip Liner"), "lip_liner", "lips"),
        (("lips", "Lips", "Lip Mask"), "lip_care", "lips"),
        (("foundation", "Face", "Tinted Moisturiser"), "foundation", "foundation"),
        (("concealer", "Face", "Colour Correctors"), "concealer", "concealer"),
        (("cheek", "Cheek", "Blush"), "blush", "cheek"),
        (("eyes", "Eyes", "Mascara"), "mascara", "eyes"),
        (("eyes", "Eyes", "Lash Serum"), "lashes", "eyes"),
        (("skincare", "Skincare", "Cleansing Balm"), "cleanser", "skincare"),
        (("skincare", "Skincare", "Sheet Masks"), "mask", "skincare"),
        (("skincare", "Skincare", "Sunscreen SPF 50"), "sunscreen", "skincare"),
        (("fragrance", "Fragrance", "Eau de Parfum"), "fragrance", "fragrance"),
        (("body", "Bath & Body", "Body Lotion"), "body_care", "body"),
        # No bucket of their own: the exporter's code stays the bucket.
        (("other", "Hair", "Hair Mask"), "hair_care", "other"),
        (("cheek", "Tools", "Powder Brush"), "tools", "cheek"),
        (("foundation", "Face", "Setting Powder"), "powder", "foundation"),
    ],
)
def test_the_deciding_level_places_the_product(
    category: tuple[str, ...], common: str, bucket: str
) -> None:
    placed = classify(category)
    assert (placed.common, placed.bucket, placed.unmapped) == (common, bucket, None)
    assert placed.matched == category[-1]


def test_an_eye_cream_is_skincare_whatever_the_exporter_coded() -> None:
    """The exporter matches "eye" before "skin"; taxonomy@1 follows the breadcrumb."""
    placed = classify(("eyes", "Skincare", "Eye Cream"))
    assert (placed.common, placed.bucket) == ("eye_care", "skincare")


def test_the_head_noun_wins_within_a_level_then_the_longest_match() -> None:
    assert classify(("other", "Powder Brush")).common == "tools"  # not powder
    assert classify(("other", "Tinted Moisturizer")).common == "foundation"  # not moisturizer


def test_the_deepest_matching_level_decides() -> None:
    placed = classify(("lips", "Lips", "Lip Gloss", "Mystery Edition"))
    assert (placed.common, placed.matched) == ("lip_gloss", "Lip Gloss")


def test_no_rule_and_no_breadcrumb_are_unmapped_with_the_code_as_bucket() -> None:
    assert classify(("lips", "Lips", "Other")) == Placement(
        bucket="lips", common=None, unmapped=Unmapped.NO_RULE, matched=None
    )
    assert classify(("fragrance",)) == Placement(
        bucket="fragrance", common=None, unmapped=Unmapped.NO_BREADCRUMB, matched=None
    )
    assert classify(()).unmapped is Unmapped.NO_BREADCRUMB
    assert classify(("makeup", "Mystery")).bucket == "other"  # not an exporter code


def test_a_tie_between_categories_is_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    doubled = dict(taxonomy._COMPILED) | {"twin": (re.compile(r"\blipsticks?"),)}
    monkeypatch.setattr(taxonomy, "_COMPILED", doubled)
    placed = classify(("lips", "Lipstick"))
    assert (placed.common, placed.unmapped, placed.matched) == (
        None,
        Unmapped.AMBIGUOUS,
        "Lipstick",
    )


def test_every_category_has_both_labels_and_a_known_bucket() -> None:
    for key, common in COMMON.items():
        assert common.bucket is None or common.bucket in BUCKETS, key
        assert common.label.en
        assert common.label.ar
        assert label(Level.COMMON, key) == common.label
    assert {label(Level.BUCKET, k).en for k in BUCKETS} == {b.en for b in BUCKETS.values()}


@given(st.lists(st.text(max_size=30), max_size=4))
def test_classify_is_total_and_exactly_one_of_common_or_unmapped(levels: list[str]) -> None:
    placed = classify(tuple(levels))
    assert placed.bucket in BUCKETS
    assert (placed.common is None) != (placed.unmapped is None)
    assert placed == classify(tuple(levels))
