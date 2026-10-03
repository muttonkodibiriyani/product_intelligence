import random
from decimal import Decimal

import numpy as np
import pytest
from pydantic import ValidationError

from pi_image.candidates import generate
from pi_image.embed import FloatArray
from pi_image.hashing import to_hex
from pi_image.model import ImageSignal, ImageStatus, ListingImage, Via

SHA = "0" * 64


def listing(
    source: str,
    key: str,
    phash: int,
    brand: str | None = "dior",
    status: ImageStatus = ImageStatus.OK,
) -> ListingImage:
    hashed = status in {ImageStatus.OK, ImageStatus.PLACEHOLDER}
    return ListingImage(
        source=source,
        source_key=key,
        brand_key=brand,
        image_url=f"https://img/{source}/{key}.jpg",
        status=status,
        phash=to_hex(phash) if hashed else None,
        dhash=to_hex(phash) if hashed else None,
        image_sha=SHA if hashed else None,
    )


def unit(*values: float) -> FloatArray:
    v = np.array(values, dtype=np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def key(s: ImageSignal) -> tuple[str, str, str, str]:
    return (s.left_source, s.left_key, s.right_source, s.right_key)


def test_phash_near_duplicates_without_embeddings() -> None:
    rows = [
        listing("sephora_me", "s1", 0),
        listing("ulta_ae", "u1", 0b111),  # 3 bits away
        listing("ulta_ae", "u2", 2**64 - 1),  # far
        listing("faces_ae", "f1", 0b1),
    ]
    pairs, aliases = generate(rows, {})
    assert aliases == ()
    assert [key(p) for p in pairs] == [
        ("faces_ae", "f1", "sephora_me", "s1"),
        ("faces_ae", "f1", "ulta_ae", "u1"),
        ("sephora_me", "s1", "ulta_ae", "u1"),
    ]
    first = pairs[0]
    assert first.via is Via.PHASH
    assert first.phash_distance == 1
    assert first.dhash_distance == 1
    assert first.cosine is None
    assert first.rank is None


def test_ann_top_k_and_both() -> None:
    rows = [
        listing("sephora_me", "s1", 0),
        listing("ulta_ae", "u1", 0),  # same picture: phash and ann
        listing("ulta_ae", "u2", 2**64 - 1),  # different picture, similar embedding
        listing("ulta_ae", "u3", 0x00FF_00FF_00FF_00FF),  # far in both
    ]
    vectors = {
        rows[0].image_url or "": unit(1, 0, 0),
        rows[1].image_url or "": unit(1, 0.05, 0),
        rows[2].image_url or "": unit(1, 0.3, 0),
        rows[3].image_url or "": unit(0, 0, 1),
    }
    pairs, _ = generate(rows, vectors, k=1)
    by_key = {p.right_key: p for p in pairs}
    assert by_key["u1"].via is Via.BOTH
    assert by_key["u1"].rank == 1
    assert by_key["u1"].cosine == Decimal("0.9988")
    # u2's nearest on the other side is s1, so it is proposed from the right-hand side
    assert by_key["u2"].via is Via.ANN
    assert by_key["u2"].rank == 1
    assert by_key["u3"].via is Via.ANN  # each right listing gets its top 1
    two, _ = generate(rows, vectors, k=0)
    assert [p.right_key for p in two] == ["u1"]


def test_cross_brand_hits_are_alias_suggestions_only() -> None:
    rows = [
        listing("sephora_me", "s1", 0, brand="ysl beauty"),
        listing("ulta_ae", "u1", 0, brand="yves saint laurent"),
        listing("ulta_ae", "u2", 0, brand=None),  # an unknown brand is no conflict
    ]
    pairs, aliases = generate(rows, {})
    assert [p.right_key for p in pairs] == ["u2"]
    assert [(a.left_brand, a.right_brand) for a in aliases] == [
        ("ysl beauty", "yves saint laurent")
    ]


@pytest.mark.parametrize(
    "status", [ImageStatus.PLACEHOLDER, ImageStatus.MISSING_IMAGE, ImageStatus.FETCH_FAILED]
)
def test_only_ok_images_take_part(status: ImageStatus) -> None:
    rows = [listing("sephora_me", "s1", 0), listing("ulta_ae", "u1", 0, status=status)]
    vectors = {r.image_url or "": unit(1, 0) for r in rows}
    assert generate(rows, vectors) == ((), ())


def test_listings_without_a_vector_only_pair_by_phash() -> None:
    rows = [
        listing("sephora_me", "s1", 0),
        listing("ulta_ae", "u1", 2**64 - 1),
        listing("ulta_ae", "u2", 0),
    ]
    vectors = {rows[0].image_url or "": unit(1, 0), rows[1].image_url or "": unit(1, 0)}
    pairs, _ = generate(rows, vectors)
    by_key = {p.right_key: p for p in pairs}
    assert by_key["u1"].via is Via.ANN
    assert by_key["u1"].cosine == Decimal("1.0000")
    assert by_key["u2"].via is Via.PHASH
    assert by_key["u2"].cosine is None


def test_deterministic_under_shuffle_and_ties() -> None:
    rng = random.Random(7)  # noqa: S311 -- seeded test data
    rows = [listing("sephora_me", f"s{i}", rng.getrandbits(64)) for i in range(20)]
    rows += [listing("ulta_ae", f"u{i}", rng.getrandbits(64)) for i in range(20)]
    # many exact ties in cosine: rank must follow key order, not input order
    vectors = {r.image_url or "": unit(1, float(i % 3)) for i, r in enumerate(rows)}
    expected = generate(rows, vectors, k=3)
    for _ in range(5):
        shuffled = rows[:]
        rng.shuffle(shuffled)
        assert generate(shuffled, vectors, k=3) == expected


def test_signal_must_be_ordered_and_bounded() -> None:
    base = {
        "left_source": "ulta_ae",
        "left_key": "a",
        "right_source": "sephora_me",
        "right_key": "b",
        "phash_distance": 0,
        "dhash_distance": 0,
        "cosine": None,
        "via": Via.PHASH,
        "left_image_sha": SHA,
        "right_image_sha": SHA,
    }
    with pytest.raises(ValidationError, match="sort before"):
        ImageSignal.model_validate(base)
    with pytest.raises(ValidationError):
        ImageSignal.model_validate({**base, "left_source": "a", "phash_distance": 65})


def test_listing_validator() -> None:
    with pytest.raises(ValidationError, match="both hashes"):
        ListingImage(
            source="a", source_key="k", brand_key=None, image_url=None, status=ImageStatus.OK
        )
    with pytest.raises(ValidationError, match="carries no hashes"):
        ListingImage(
            source="a",
            source_key="k",
            brand_key=None,
            image_url=None,
            status=ImageStatus.MISSING_IMAGE,
            phash="0" * 16,
        )
