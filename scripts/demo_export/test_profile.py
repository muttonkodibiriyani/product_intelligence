"""``--profile``: beauty@1 by default, byte for byte as before; beauty@2 publishes each offer's
gift titles with page evidence and every key without stored evidence as not collected."""

from __future__ import annotations

# ruff: noqa: S101
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from pi_dataset import AttributeSource, DatasetV3, committed_profile, dump_dataset, load_any
from pi_dataset.v3 import EXCERPT_MAX
from scripts.demo_export.export import ListingRow, UltaContext, check_args, parser
from scripts.demo_export.test_export import row
from scripts.demo_export.test_v2 import NOTE, NOW
from scripts.demo_export.test_v3 import MATCHES, REQUIRED, rows
from scripts.demo_export.v2 import (
    EVIDENCED_KEYS,
    build_dataset_v2,
    evidence_profile,
    gift_attributes,
    to_v3,
)

GIFTS = ("Pouch + Mini Gloss", "Free travel size")


def gifted() -> list[ListingRow]:
    """``rows()``, Sephora variant 101 (the 30 ml offer's representative) with two gift titles."""
    return [replace(r, gift_with_purchase=GIFTS) if r.variant_id == 101 else r for r in rows()]


def body(listing: list[ListingRow], **kwargs: Any) -> bytes:
    v2 = build_dataset_v2(
        listing,
        MATCHES,
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
        ulta_note=NOTE,
    )
    text = dump_dataset(to_v3(v2, listing, MATCHES, **kwargs), compact=True)
    assert isinstance(load_any(text), DatasetV3)  # what main() checks before writing
    return text


def offer_attributes(text: bytes) -> dict[tuple[str, str], dict[str, Any]]:
    doc = json.loads(text)
    return {
        (p["id"], cid): {"attributes": o["attributes"], "evidence": o.get("attributeEvidence")}
        for p in doc["products"]
        for cid, o in p["offers"].items()
        if o is not None and o["attributes"]
    }


def test_beauty_1_is_the_default_byte_for_byte_and_publishes_no_gift() -> None:
    plain = body(rows())
    assert body(rows(), beauty=1) == plain
    with_gift = body(gifted())
    print(f"beauty@1 body {len(with_gift)} bytes; gift-free body {len(plain)} bytes")
    assert with_gift == plain  # the stored titles reach no beauty@1 body
    assert json.loads(plain)["meta"]["profile"]["version"] == 1
    shade = [p["attributes"] for p in json.loads(plain)["products"] if p["attributes"]]
    print(f"beauty@1 product attributes: {shade}")
    assert shade  # control: beauty@1 still publishes the shade families it always did


def test_beauty_2_publishes_the_gift_titles_with_page_evidence() -> None:
    text = body(gifted(), beauty=2)
    got = offer_attributes(text)
    print(f"beauty@2 offer attributes: {got}")
    assert len(got) == 1
    (only,) = got.values()
    assert only["attributes"] == {"giftWithPurchase": list(GIFTS)}
    assert only["evidence"] == {
        "giftWithPurchase": {
            "source": "page",
            "field": "gift_with_purchase",
            "excerpt": "Pouch + Mini Gloss | Free travel size",
            "rule": None,
        }
    }


def test_beauty_2_declares_every_key_without_evidence_not_collected() -> None:
    doc = json.loads(body(gifted(), beauty=2))
    assert doc["meta"]["profile"]["version"] == 2
    capability = {a["key"]: a["capability"] for a in doc["meta"]["attributeSet"]}
    print(f"beauty@2 capabilities: {capability}")
    assert len(capability) == 10
    assert {k for k, on in capability.items() if on} == EVIDENCED_KEYS == {"giftWithPurchase"}
    # the rows' shade family (published under beauty@1) has no stored source text: left out
    assert [p["attributes"] for p in doc["products"] if p["attributes"]] == []


def test_beauty_2_without_gift_titles_publishes_no_attribute() -> None:
    got = offer_attributes(body(rows(), beauty=2))
    print(f"beauty@2 offer attributes without titles: {got}")
    assert got == {}


def test_a_long_gift_title_is_kept_whole_and_its_excerpt_is_cut() -> None:
    title = "A free gift " * 20
    got = gift_attributes([replace(row(), gift_with_purchase=(title,))])
    excerpt = got["attribute_evidence"]["giftWithPurchase"].excerpt
    print(f"title {len(title)} chars, excerpt {len(excerpt)} chars")
    assert got["attributes"] == {"giftWithPurchase": [title]}
    assert excerpt == title[:EXCERPT_MAX]
    assert got["attribute_evidence"]["giftWithPurchase"].source is AttributeSource.PAGE


def test_a_gift_without_its_evidence_fails_the_strict_load() -> None:
    """Must-fire control: the evidence is what lets a beauty@2 body load."""
    doc = json.loads(body(gifted(), beauty=2))
    stripped = 0
    for p in doc["products"]:
        for o in p["offers"].values():
            if o is not None and o["attributes"]:
                o["attributeEvidence"] = {}
                stripped += 1
    print(f"evidence stripped from {stripped} offer(s)")
    assert stripped == 1
    with pytest.raises(ValueError, match="no attributeEvidence"):
        load_any(json.dumps(doc))


def test_a_beauty_1_value_left_in_a_beauty_2_body_fails_the_strict_load() -> None:
    """Must-fire control: a not-collected key's value is refused, so none can slip through."""
    doc = json.loads(body(gifted(), beauty=2))
    doc["products"][0]["attributes"] = {"shadeFamilies": ["Medium"]}
    with pytest.raises(ValueError, match="not collected"):
        load_any(json.dumps(doc))


def test_only_the_committed_versions_are_written() -> None:
    assert evidence_profile(1) == committed_profile("beauty", 1)  # unchanged, capabilities on
    with pytest.raises(ValueError, match="beauty@3"):
        evidence_profile(3)


def test_the_profile_flag_defaults_to_beauty_1_and_needs_a_v3_output() -> None:
    assert parser().parse_args(REQUIRED).profile == "beauty@1"
    with pytest.raises(SystemExit, match="needs --output-v3"):
        check_args(parser().parse_args([*REQUIRED, "--profile", "beauty@2"]))
    args = parser().parse_args([*REQUIRED, "--profile", "beauty@2", "--output-v3", "v3.json"])
    check_args(args)
    with pytest.raises(SystemExit):
        parser().parse_args([*REQUIRED, "--profile", "beauty@3"])
