import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image

from image_fixtures import as_bytes, packshot, transparent, with_margin
from pi_image.candidates import PHASH_NEAR
from pi_image.hashing import (
    UnreadableImageError,
    decode,
    dhash,
    from_hex,
    hamming,
    is_blank,
    normalise,
    phash,
    to_hex,
)
from pi_image.placeholder import near_known, neighbours, shared_hashes, url_marker

hashes = st.integers(min_value=0, max_value=2**64 - 1)


def hashed(image: Image.Image, fmt: str = "PNG", **kw: object) -> tuple[int, int]:
    square = normalise(decode(as_bytes(image, fmt, **kw)))
    assert square is not None
    return phash(square), dhash(square)


@pytest.mark.parametrize("seed", range(6))
def test_same_packshot_survives_retailer_differences(seed: int) -> None:
    base = hashed(packshot(seed))
    variants = [
        hashed(packshot(seed), "JPEG", quality=70),  # re-encoded
        hashed(with_margin(packshot(seed), 90)),  # more margin, other crop
        hashed(packshot(seed).resize((640, 640))),  # other size
        hashed(transparent(packshot(seed))),  # cut-out PNG on transparent background
    ]
    for p, d in variants:
        assert hamming(base[0], p) <= PHASH_NEAR
        assert hamming(base[1], d) <= PHASH_NEAR


def test_different_products_are_far_apart() -> None:
    values = [hashed(packshot(seed))[0] for seed in range(12)]
    close = [
        (a, b)
        for a in range(12)
        for b in range(a + 1, 12)
        if hamming(values[a], values[b]) <= PHASH_NEAR
    ]
    assert close == []


def test_blank_and_flat_pictures() -> None:
    assert normalise(Image.new("RGB", (100, 100), "white")) is None
    flat = Image.new("RGB", (100, 100), (200, 30, 30))
    assert normalise(flat) is None  # all background, whatever its colour
    speck = Image.new("RGB", (200, 200), "white")
    speck.putpixel((100, 100), (0, 0, 0))
    square = normalise(speck)
    assert square is not None
    assert is_blank(Image.new("RGB", (64, 64), (128, 128, 128)))
    assert not is_blank(packshot(1))


def test_decode_refuses_garbage_and_huge_images() -> None:
    with pytest.raises(UnreadableImageError):
        decode(b"<html>blocked</html>")
    huge = as_bytes(Image.new("1", (8000, 6000)))
    with pytest.raises(UnreadableImageError, match="too large"):
        decode(huge)


@given(hashes)
def test_hex_round_trip(value: int) -> None:
    assert from_hex(to_hex(value)) == value
    assert len(to_hex(value)) == 16


def test_from_hex_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="16 hex digits"):
        from_hex("abc")


@given(hashes, hashes, hashes)
def test_hamming_is_a_metric(a: int, b: int, c: int) -> None:
    assert hamming(a, a) == 0
    assert hamming(a, b) == hamming(b, a)
    assert 0 <= hamming(a, b) <= 64
    assert hamming(a, c) <= hamming(a, b) + hamming(b, c)


# ---------------------------------------------------------------- placeholders


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.faces.ae/images/placeholder.png", True),
        ("https://media.alshaya.com/x/No-Image_1.jpg", True),
        ("https://img-product.sephora.me/a/coming_soon.jpg?sw=1", True),
        ("https://img-product.sephora.me/a/image%20not%20available.jpg", True),
        ("https://img-product.sephora.me/a/315984_swatch.jpg?sw=1248", False),
        ("https://www.faces.ae/p/default.jpg?placeholder=1", False),  # the query is not the file
    ],
)
def test_url_marker(url: str, expected: bool) -> None:
    assert url_marker(url) is expected


def test_shared_counts_brands_within_one_source_only() -> None:
    logo, packshot_hash, sizes = 0xAAAA_0000_FFFF_0000, 0x1234_5678_9ABC_DEF0, 0x0F0F_0F0F_0F0F_0F0F
    listings = [
        # one retailer shows the same "coming soon" picture for three brands
        ("sephora_me", "dior", logo),
        ("sephora_me", "chanel", logo ^ 0b11),  # within the radius
        ("sephora_me", "ysl", logo),
        ("sephora_me", None, logo),  # an unknown brand never counts
        # one packshot shared across retailers under three brand spellings: not a placeholder
        ("ulta_ae", "yves saint laurent", packshot_hash),
        ("sephora_me", "ysl beauty", packshot_hash),
        ("faces_ae", "ysl", packshot_hash),
        # one product in many sizes: not a placeholder
        ("faces_ae", "dior", sizes),
        ("faces_ae", "dior", sizes),
        ("faces_ae", "dior", sizes),
    ]
    found = shared_hashes(listings)
    assert found == {logo: 3, logo ^ 0b11: 3}
    assert shared_hashes(listings, min_brands=4) == {}


def test_neighbours_and_known() -> None:
    values = [0, 1, 0b111, 2**64 - 1]
    assert neighbours(values, 1) == [[0, 1], [0, 1], [2], [3]]
    assert near_known(0b11, {0: "sephora coming soon"}) == "sephora coming soon"
    assert near_known(2**64 - 1, {0: "sephora coming soon"}) is None


@given(
    st.lists(
        st.tuples(st.sampled_from(["a", "b"]), st.sampled_from(["x", "y", "z", None]), hashes),
        max_size=30,
    )
)
def test_shared_needs_min_brands_in_one_source(listings: list[tuple[str, str | None, int]]) -> None:
    for value, widest in shared_hashes(listings).items():
        assert widest >= 3
        brands_near = {(s, b) for s, b, v in listings if b is not None and hamming(v, value) <= 4}
        assert any(len({b for s2, b in brands_near if s2 == s}) >= 3 for s, _ in brands_near)
