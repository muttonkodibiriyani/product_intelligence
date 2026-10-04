"""Placeholder detection: images that say nothing about the product they are shown for.

A placeholder is excluded from every image signal, never treated as evidence for or against a
match. Three rules, each named in ``ListingImage.detail``:

- ``url_marker``: the file name says so ("placeholder", "no-image", "coming-soon", ...).
- ``blank``: a flat picture, or one with nothing but background.
- ``shared``: within ONE retailer, the same picture (pHash within ``SHARED_RADIUS``) is shown for
  at least ``MIN_BRANDS`` different brands. Counting inside one retailer keeps brand spellings
  consistent, so a real packshot shared across retailers under "YSL" and "Yves Saint Laurent"
  is never mistaken for a placeholder; the same photo on sizes of one product never is either.
- ``known``: within ``SHARED_RADIUS`` of a reference placeholder hash given by the caller.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

import numpy as np

SHARED_RADIUS = 4
MIN_BRANDS = 3
_URL_MARKER = re.compile(
    r"placeholder|no[-_ ]?image|no[-_ ]?photo|coming[-_ ]?soon|image[-_ ]?not[-_ ]?available"
    r"|image[-_ ]?unavailable|default[-_ ]?(?:image|product)|missing[-_ ]?image",
    re.IGNORECASE,
)
_CHUNK = 2048


def url_marker(url: str) -> bool:
    """The URL's path names a placeholder."""
    return _URL_MARKER.search(unquote(urlsplit(url).path)) is not None


def neighbours(hashes: Sequence[int], radius: int) -> list[list[int]]:
    """For each hash, the indices of all hashes (itself included) within ``radius`` bits."""
    values = np.array(hashes, dtype=np.uint64)
    found: list[list[int]] = [[] for _ in hashes]
    for start in range(0, len(values), _CHUNK):
        block = values[start : start + _CHUNK]
        close = np.bitwise_count(block[:, None] ^ values[None, :]) <= radius
        for offset, row in enumerate(close):
            found[start + offset] = np.flatnonzero(row).tolist()
    return found


def shared_hashes(
    listings: Iterable[tuple[str, str | None, int]],
    *,
    radius: int = SHARED_RADIUS,
    min_brands: int = MIN_BRANDS,
) -> dict[int, int]:
    """Hashes shown for ``min_brands`` or more brands within one source.

    ``listings`` are ``(source, brand_key, phash)``; a listing without a brand never counts.
    Returns each placeholder hash with the most brands any one source shows it for.
    """
    brands: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for source, brand, value in listings:
        keys = brands[value][source]  # registers the hash even when the brand is unknown
        if brand is not None:
            keys.add(brand)
    unique = sorted(brands)
    out: dict[int, int] = {}
    for index, close in enumerate(neighbours(unique, radius)):
        merged: dict[str, set[str]] = defaultdict(set)
        for other in close:
            for source, keys in brands[unique[other]].items():
                merged[source] |= keys
        widest = max((len(keys) for keys in merged.values()), default=0)
        if widest >= min_brands:
            out[unique[index]] = widest
    return out


def near_known(value: int, known: Mapping[int, str], radius: int = SHARED_RADIUS) -> str | None:
    """The label of a reference placeholder within ``radius`` bits, if any."""
    for reference, label in sorted(known.items()):
        if (value ^ reference).bit_count() <= radius:
            return label
    return None
