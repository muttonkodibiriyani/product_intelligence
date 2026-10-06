"""Cross-retailer candidate pairs from images: pHash near-duplicates plus top-k by cosine.

For every pair of sources (sorted, so ``left_source < right_source``), a pair is proposed when
its pHash distance is at most ``phash_max`` AND its dHash distance is at most ``dhash_max``
(``via=phash``), or when either listing is among the other's ``k`` nearest by embedding cosine
(``via=ann``); both gives ``via=both``. Only listings whose image status is ``ok`` take part:
placeholders, missing and failed images never do.

Deterministic: listings are ordered by key and ties in cosine are broken by that order, so the
same inputs give the same rows. Cosines are rounded to 4 dp.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

import numpy as np
from numpy.typing import NDArray

from pi_image.embed import FloatArray
from pi_image.hashing import from_hex
from pi_image.model import ImageSignal, ImageStatus, ListingImage, Via

DEFAULT_K = 10
#: pHash bits that may differ for a near-duplicate (same packshot, re-encoded or re-cropped).
PHASH_NEAR = 6
#: dHash bits that may differ for a near-duplicate.  The two hash gates are conjunctive.
DHASH_NEAR = 8
#: Minimum embedding cosine for an ANN-only cross-brand alias suggestion.
ALIAS_COSINE_MIN = 0.95
_CHUNK = 1024
_Q = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class _Side:
    keys: list[str]
    brands: list[str | None]
    phash: NDArray[np.uint64]
    dhash: NDArray[np.uint64]
    shas: list[str]
    vectors: FloatArray | None  # unit rows; None when not every listing has one
    has_vector: NDArray[np.bool_]


def _side(listings: Sequence[ListingImage], vectors: Mapping[str, FloatArray]) -> _Side:
    ordered = sorted(listings, key=lambda li: li.source_key)
    urls = [li.image_url or "" for li in ordered]
    has = np.array([u in vectors for u in urls], dtype=np.bool_)
    matrix: FloatArray | None = None
    if has.any():
        dim = len(next(iter(vectors.values())))
        rows = [vectors[u] if u in vectors else np.zeros(dim, np.float32) for u in urls]
        matrix = np.stack(rows).astype(np.float32)
    return _Side(
        keys=[li.source_key for li in ordered],
        brands=[li.brand_key for li in ordered],
        phash=np.array([from_hex(li.phash or "") for li in ordered], dtype=np.uint64),
        dhash=np.array([from_hex(li.dhash or "") for li in ordered], dtype=np.uint64),
        shas=[li.image_sha or "" for li in ordered],
        vectors=matrix,
        has_vector=has,
    )


def _near(left: _Side, right: _Side, phash_limit: int, dhash_limit: int) -> set[tuple[int, int]]:
    found: set[tuple[int, int]] = set()
    for start in range(0, len(left.phash), _CHUNK):
        phash = left.phash[start : start + _CHUNK]
        dhash = left.dhash[start : start + _CHUNK]
        close = np.bitwise_count(phash[:, None] ^ right.phash[None, :]) <= phash_limit
        close &= np.bitwise_count(dhash[:, None] ^ right.dhash[None, :]) <= dhash_limit
        rows, cols = np.nonzero(close)
        found.update(zip((rows + start).tolist(), cols.tolist(), strict=True))
    return found


def _top_k(
    query: FloatArray,
    query_ok: NDArray[np.bool_],
    base: FloatArray,
    base_ok: NDArray[np.bool_],
    k: int,
) -> dict[tuple[int, int], int]:
    """(query index, base index) -> rank (1 = nearest) for each query's top ``k``."""
    ranks: dict[tuple[int, int], int] = {}
    if k <= 0 or not base_ok.any():
        return ranks
    order = np.arange(len(base))
    for start in range(0, len(query), _CHUNK):
        sims = query[start : start + _CHUNK] @ base.T
        sims[:, ~base_ok] = -np.inf
        for offset, row in enumerate(sims):
            q = start + offset
            if not query_ok[q]:
                continue
            # Sort by cosine (rounded, so float noise never reorders ties), then base order.
            rounded = np.round(row.astype(np.float64), 6)
            best = np.lexsort((order, -rounded))[: min(k, int(base_ok.sum()))]
            for rank, b in enumerate(best.tolist(), start=1):
                ranks[(q, b)] = rank
    return ranks


def _cosine(left: _Side, right: _Side, i: int, j: int) -> Decimal | None:
    if left.vectors is None or right.vectors is None:
        return None
    if not (left.has_vector[i] and right.has_vector[j]):
        return None
    value = float(np.clip(left.vectors[i] @ right.vectors[j], -1.0, 1.0))
    return Decimal(f"{value:.4f}").quantize(_Q)


def generate(  # noqa: PLR0913 - explicit CLI-tunable evidence gates
    listings: Sequence[ListingImage],
    vectors: Mapping[str, FloatArray],
    *,
    k: int = DEFAULT_K,
    phash_max: int = PHASH_NEAR,
    dhash_max: int = DHASH_NEAR,
    alias_cosine_min: float = ALIAS_COSINE_MIN,
) -> tuple[tuple[ImageSignal, ...], tuple[ImageSignal, ...]]:
    """``(candidates, alias_suggestions)`` across sources; ``vectors`` are unit rows by image URL.

    A pair whose brand keys are both known and differ is an alias suggestion (for human review of
    the brand alias table), never a candidate: a brand difference is a hard rule.
    """
    by_source: dict[str, list[ListingImage]] = defaultdict(list)
    for listing in listings:
        if listing.status is ImageStatus.OK:
            by_source[listing.source].append(listing)
    sides = {source: _side(items, vectors) for source, items in by_source.items()}
    out: list[ImageSignal] = []
    aliases: list[ImageSignal] = []
    for a, b in combinations(sorted(sides), 2):
        left, right = sides[a], sides[b]
        near = _near(left, right, phash_max, dhash_max)
        ann: dict[tuple[int, int], int] = {}
        if left.vectors is not None and right.vectors is not None:
            ann = _top_k(left.vectors, left.has_vector, right.vectors, right.has_vector, k)
            back = _top_k(right.vectors, right.has_vector, left.vectors, left.has_vector, k)
            for (j, i), rank in back.items():
                ann[(i, j)] = min(rank, ann.get((i, j), rank))
        for i, j in sorted(near | ann.keys()):
            lb, rb = left.brands[i], right.brands[j]
            in_near = (i, j) in near
            found = ann.get((i, j))
            via = Via.BOTH if in_near and found is not None else Via.PHASH if in_near else Via.ANN
            signal = ImageSignal(
                left_source=a,
                left_key=left.keys[i],
                right_source=b,
                right_key=right.keys[j],
                left_brand=lb,
                right_brand=rb,
                phash_distance=int(left.phash[i] ^ right.phash[j]).bit_count(),
                dhash_distance=int(left.dhash[i] ^ right.dhash[j]).bit_count(),
                cosine=_cosine(left, right, i, j),
                rank=found,
                via=via,
                left_image_sha=left.shas[i],
                right_image_sha=right.shas[j],
            )
            differ = lb is not None and rb is not None and lb != rb
            alias_evidence = in_near or (
                signal.cosine is not None and float(signal.cosine) >= alias_cosine_min
            )
            if differ:
                if alias_evidence:
                    aliases.append(signal)
            else:
                out.append(signal)
    return tuple(out), tuple(aliases)
