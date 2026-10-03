"""Image decoding, packshot normalisation and perceptual hashes (pHash, dHash).

Normalisation handles the usual cross-retailer differences in one packshot: transparent vs
white backgrounds (alpha is flattened onto white), extra margin or a different crop (the uniform
border is trimmed) and aspect ratio (the product is padded to a square). What is left is hashed.
"""

import io
from functools import cache

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageChops, UnidentifiedImageError

HASH_BITS = 64
#: A pixel within this many grey levels of the corner colour counts as background when trimming.
BORDER_TOLERANCE = 24
#: Below this standard deviation (grey levels, at 32x32) a picture is blank.
BLANK_STD = 2.0
#: Decoding refuses anything larger (decompression-bomb guard).
MAX_PIXELS = 40_000_000
_WHITE = (255, 255, 255)


class UnreadableImageError(ValueError):
    """The bytes are not an image Pillow can decode."""


def decode(data: bytes) -> Image.Image:
    """Decode to RGB with any transparency flattened onto white."""
    try:
        with Image.open(io.BytesIO(data)) as raw:
            if raw.width * raw.height > MAX_PIXELS:
                msg = f"image too large: {raw.width}x{raw.height}"
                raise UnreadableImageError(msg)
            raw.load()
            image = raw.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        msg = f"not a decodable image: {type(exc).__name__}"
        raise UnreadableImageError(msg) from exc
    canvas = Image.new("RGBA", image.size, (*_WHITE, 255))
    canvas.alpha_composite(image)
    return canvas.convert("RGB")


def normalise(image: Image.Image) -> Image.Image | None:
    """Trim the uniform border and pad to a white square; None for a picture with no content."""
    grey = image.convert("L")
    corner = grey.getpixel((0, 0))
    background = Image.new("L", grey.size, corner if isinstance(corner, int) else 255)
    diff = ImageChops.difference(grey, background).point(
        lambda v: 255 if v > BORDER_TOLERANCE else 0
    )
    box = diff.getbbox()
    if box is None:
        return None
    cropped = image.crop(box)
    side = max(cropped.size)
    square = Image.new("RGB", (side, side), _WHITE)
    square.paste(cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2))
    return square


def is_blank(image: Image.Image) -> bool:
    """A flat picture (one colour, or near enough) carries no product evidence."""
    small = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.BILINEAR), np.float64)
    return float(small.std()) < BLANK_STD


@cache
def _dct_matrix(n: int) -> NDArray[np.float64]:
    """Orthonormal DCT-II basis, rows are frequencies."""
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    m[0, :] = np.sqrt(1.0 / n)
    basis: NDArray[np.float64] = m.astype(np.float64)
    return basis


def _bits_to_int(bits: NDArray[np.bool_]) -> int:
    value = 0
    for bit in bits.ravel():
        value = (value << 1) | int(bit)
    return value


def phash(image: Image.Image) -> int:
    """64-bit DCT perceptual hash: low 8x8 frequencies of a 32x32 grey image vs their AC mean.

    The mean of the 63 AC terms, not the median: a symmetric packshot (most bottles) has many
    near-zero terms, so a median near zero flips bits on JPEG noise. On 180 real packshots
    re-encoded and re-cropped, the median variant moved up to 28 bits; this one at most 8.
    """
    grey = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), np.float64)
    m = _dct_matrix(32)
    low = (m @ grey @ m.T)[:8, :8]
    threshold = (low.sum() - low[0, 0]) / (low.size - 1)
    return _bits_to_int(low > threshold)


def dhash(image: Image.Image) -> int:
    """64-bit difference hash: is each pixel brighter than its right neighbour (9x8 grey)."""
    grey = np.asarray(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS), np.int16)
    return _bits_to_int(grey[:, 1:] > grey[:, :-1])


def hamming(a: int, b: int) -> int:
    """Differing bits between two 64-bit hashes."""
    return (a ^ b).bit_count()


def to_hex(value: int) -> str:
    """A hash as 16 lower-case hex digits."""
    return f"{value:016x}"


def from_hex(text: str) -> int:
    """Inverse of ``to_hex``."""
    if len(text) != HASH_BITS // 4:
        msg = f"a hash has {HASH_BITS // 4} hex digits, got {text!r}"
        raise ValueError(msg)
    return int(text, 16)
