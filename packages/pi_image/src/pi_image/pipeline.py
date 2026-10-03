"""Listing images end to end: fetch (or read the cache), decode, hash, flag placeholders, embed."""

import hashlib
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from PIL import Image

from pi_image.embed import Embedder, EmbeddingCache, FloatArray, embed_all
from pi_image.fetch import Fetched, ImageFetcher
from pi_image.hashing import UnreadableImageError, decode, dhash, is_blank, normalise, phash, to_hex
from pi_image.hashing import from_hex as _from_hex
from pi_image.model import FetchStatus, ImageRef, ImageStatus, ListingImage
from pi_image.placeholder import (
    MIN_BRANDS,
    SHARED_RADIUS,
    near_known,
    shared_hashes,
    url_marker,
)


@dataclass(frozen=True, slots=True)
class _Hashed:
    status: ImageStatus
    detail: str | None = None
    phash: int | None = None
    dhash: int | None = None
    sha: str | None = None


@dataclass(slots=True)
class Analysis:
    """Per-listing outcomes, the placeholder hashes found, and fetch counts."""

    listings: tuple[ListingImage, ...]
    placeholders: dict[str, int] = field(default_factory=dict)  # pHash hex -> widest brand count
    fetch_counts: dict[str, int] = field(default_factory=dict)


def _hash_bytes(fetched: Fetched) -> _Hashed:
    if fetched.status is not FetchStatus.OK or fetched.body is None:
        detail = fetched.status.value + (f": {fetched.detail}" if fetched.detail else "")
        return _Hashed(ImageStatus.FETCH_FAILED, detail)
    try:
        image = decode(fetched.body)
    except UnreadableImageError as exc:
        return _Hashed(ImageStatus.UNREADABLE, str(exc))
    square = normalise(image)
    if square is None:
        return _Hashed(ImageStatus.PLACEHOLDER, "blank")
    p, d = phash(square), dhash(square)
    sha = hashlib.sha256(fetched.body).hexdigest()
    if is_blank(square):
        return _Hashed(ImageStatus.PLACEHOLDER, "blank", p, d, sha)
    return _Hashed(ImageStatus.OK, None, p, d, sha)


def analyse(  # noqa: PLR0913 -- the tuning knobs are keyword-only
    refs: Sequence[ImageRef],
    fetcher: ImageFetcher,
    *,
    known: Mapping[int, str] | None = None,
    radius: int = SHARED_RADIUS,
    min_brands: int = MIN_BRANDS,
    progress: Callable[[int, int], None] | None = None,
) -> Analysis:
    """Every ref's image outcome. Placeholders keep their hashes (for audit) but are excluded."""
    hashed: dict[str, _Hashed] = {}
    counts: dict[str, int] = {}
    first: list[ListingImage] = []
    for index, ref in enumerate(refs, start=1):
        url = ref.image_url
        if url is None or not url.strip():
            outcome = _Hashed(ImageStatus.MISSING_IMAGE)
        elif url_marker(url):
            outcome = _Hashed(ImageStatus.PLACEHOLDER, "url_marker")
        else:
            if url not in hashed:
                fetched = fetcher.fetch(url)
                counts[fetched.status.value] = counts.get(fetched.status.value, 0) + 1
                hashed[url] = _hash_bytes(fetched)
            outcome = hashed[url]
        if outcome.status is ImageStatus.OK and known and outcome.phash is not None:
            label = near_known(outcome.phash, known, radius)
            if label is not None:
                outcome = _Hashed(
                    ImageStatus.PLACEHOLDER,
                    f"known: {label}",
                    outcome.phash,
                    outcome.dhash,
                    outcome.sha,
                )
        first.append(_listing(ref, outcome))
        if progress is not None:
            progress(index, len(refs))
    shared = shared_hashes(
        (
            (li.source, li.brand_key, _from_hex(li.phash))
            for li in first
            if li.status is ImageStatus.OK and li.phash is not None
        ),
        radius=radius,
        min_brands=min_brands,
    )
    final = tuple(
        li.model_copy(
            update={"status": ImageStatus.PLACEHOLDER, "detail": f"shared: {shared[h]} brands"}
        )
        if li.status is ImageStatus.OK and (h := _from_hex(li.phash or "0" * 16)) in shared
        else li
        for li in first
    )
    return Analysis(
        listings=final,
        placeholders={to_hex(h): n for h, n in sorted(shared.items())},
        fetch_counts=dict(sorted(counts.items())),
    )


def _listing(ref: ImageRef, outcome: _Hashed) -> ListingImage:
    return ListingImage(
        source=ref.source,
        source_key=ref.source_key,
        brand_key=ref.brand_key,
        image_url=ref.image_url,
        status=outcome.status,
        detail=outcome.detail,
        phash=None if outcome.phash is None else to_hex(outcome.phash),
        dhash=None if outcome.dhash is None else to_hex(outcome.dhash),
        image_sha=outcome.sha,
    )


def embeddings(
    listings: Sequence[ListingImage],
    fetcher: ImageFetcher,
    embedder: Embedder,
    cache: EmbeddingCache,
    batch: int = 16,
) -> dict[str, FloatArray]:
    """Unit embeddings by image URL for every ``ok`` listing (cache first, lazily decoded)."""

    def items() -> Iterator[tuple[str, Callable[[], Image.Image]]]:
        for li in listings:
            if li.status is ImageStatus.OK and li.image_url is not None:
                yield li.image_url, _loader(fetcher, li.image_url)

    return embed_all(items(), embedder, cache, batch)


def _loader(fetcher: ImageFetcher, url: str) -> Callable[[], Image.Image]:
    def load() -> Image.Image:
        fetched = fetcher.fetch(url)
        if fetched.body is None:  # pragma: no cover - analyse() only marks fetched images ok
            msg = f"{url}: {fetched.status}"
            raise UnreadableImageError(msg)
        square = normalise(decode(fetched.body))
        if square is None:  # pragma: no cover - analyse() marks these placeholders
            msg = f"{url}: blank"
            raise UnreadableImageError(msg)
        return square

    return load


def interleaved(urls: Iterable[str]) -> list[str]:
    """Unique URLs ordered round-robin across hosts, so each host keeps its own 1 req/s pace
    while the run as a whole does not wait on one host at a time."""
    by_host: dict[str, list[str]] = {}
    for url in sorted(set(urls)):
        by_host.setdefault(urlsplit(url).hostname or "", []).append(url)
    queues = [by_host[h] for h in sorted(by_host)]
    return [q[i] for i in range(max(map(len, queues), default=0)) for q in queues if i < len(q)]


def prefetch(
    refs: Sequence[ImageRef],
    fetcher: ImageFetcher,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Fetch every distinct image URL once (host-interleaved); counts by fetch status."""
    urls = interleaved(r.image_url for r in refs if r.image_url and not url_marker(r.image_url))
    counts: dict[str, int] = {}
    for index, url in enumerate(urls, start=1):
        status = fetcher.fetch(url).status.value
        counts[status] = counts.get(status, 0) + 1
        if progress is not None:
            progress(index, len(urls))
    return dict(sorted(counts.items()))
