from pathlib import Path

import numpy as np
from PIL import Image

from image_fixtures import GridEmbedder, as_bytes, packshot
from pi_image.embed import EmbeddingCache
from pi_image.fetch import Fetched, ImageCache, ImageFetcher
from pi_image.hashing import dhash, from_hex, normalise, phash
from pi_image.model import FetchStatus, ImageRef, ImageStatus
from pi_image.pipeline import analyse, by_host, embeddings, prefetch

S = "https://img-product.sephora.me/"
F = "https://www.faces.ae/"
A = "https://media.alshaya.com/"


def seed_cache(root: Path, images: dict[str, bytes]) -> ImageFetcher:
    cache = ImageCache(root)
    for url, body in images.items():
        cache.put(Fetched(url, FetchStatus.OK, "image/png", body))
    return ImageFetcher(cache, None)  # offline: the cache is all there is


def ref(source: str, key: str, url: str | None, brand: str | None = "dior") -> ImageRef:
    return ImageRef(source=source, source_key=key, brand_key=brand, image_url=url)


def test_analyse_statuses_and_dedupe(tmp_path: Path) -> None:
    good, blank = f"{S}good.png", f"{S}blank.png"
    fetcher = seed_cache(
        tmp_path,
        {
            good: as_bytes(packshot(1)),
            blank: as_bytes(Image.new("RGB", (64, 64), "white")),
            f"{S}junk.png": b"<html>",
        },
    )
    refs = [
        ref("sephora_me", "a", good),
        ref("sephora_me", "b", good),  # same URL: fetched once
        ref("sephora_me", "c", blank),
        ref("sephora_me", "d", f"{S}junk.png"),
        ref("sephora_me", "e", f"{S}missing.png"),
        ref("sephora_me", "f", None),
        ref("sephora_me", "g", "  "),
        ref("sephora_me", "h", f"{S}coming-soon.png"),
    ]
    seen: list[int] = []
    result = analyse(refs, fetcher, progress=lambda done, _: seen.append(done))
    got = {li.source_key: (li.status, li.detail) for li in result.listings}
    assert got == {
        "a": (ImageStatus.OK, None),
        "b": (ImageStatus.OK, None),
        "c": (ImageStatus.PLACEHOLDER, "blank"),
        "d": (ImageStatus.UNREADABLE, "not a decodable image: UnidentifiedImageError"),
        "e": (ImageStatus.FETCH_FAILED, "not_fetched: offline: not in cache"),
        "f": (ImageStatus.MISSING_IMAGE, None),
        "g": (ImageStatus.MISSING_IMAGE, None),
        "h": (ImageStatus.PLACEHOLDER, "url_marker"),
    }
    assert result.fetch_counts == {"not_fetched": 1, "ok": 3}
    assert seen == list(range(1, 9))
    square = normalise(packshot(1))
    assert square is not None
    first = result.listings[0]
    assert from_hex(first.phash or "") == phash(square)
    assert from_hex(first.dhash or "") == dhash(square)
    assert first.image_sha is not None


def test_low_contrast_picture_is_a_blank_placeholder_with_hashes(tmp_path: Path) -> None:
    faint = Image.new("RGB", (100, 100), "white")
    faint.paste((200, 200, 200), (40, 40, 60, 60))  # content after trimming, but flat
    fetcher = seed_cache(tmp_path, {f"{S}faint.png": as_bytes(faint)})
    (li,) = analyse([ref("sephora_me", "a", f"{S}faint.png")], fetcher).listings
    assert li.status is ImageStatus.PLACEHOLDER
    assert li.detail == "blank"
    assert li.phash is not None


def test_shared_and_known_placeholders(tmp_path: Path) -> None:
    logo, other = f"{S}logo.png", f"{F}p.png"
    fetcher = seed_cache(tmp_path, {logo: as_bytes(packshot(9)), other: as_bytes(packshot(2))})
    refs = [ref("sephora_me", k, logo, brand=b) for k, b in [("a", "x"), ("b", "y"), ("c", "z")]]
    refs.append(ref("faces_ae", "d", other))
    result = analyse(refs, fetcher)
    statuses = [(li.status, li.detail) for li in result.listings]
    assert statuses[:3] == [(ImageStatus.PLACEHOLDER, "shared: 3 brands")] * 3
    assert statuses[3] == (ImageStatus.OK, None)
    assert list(result.placeholders.values()) == [3]
    known = {from_hex(result.listings[3].phash or ""): "faces default"}
    again = analyse(refs[3:], fetcher, known=known)
    assert again.listings[0].status is ImageStatus.PLACEHOLDER
    assert again.listings[0].detail == "known: faces default"


def test_embeddings_cover_ok_listings_only_and_are_cached(tmp_path: Path) -> None:
    urls = [f"{S}{i}.png" for i in range(3)]
    fetcher = seed_cache(tmp_path / "img", {u: as_bytes(packshot(i)) for i, u in enumerate(urls)})
    refs = [ref("sephora_me", str(i), u) for i, u in enumerate(urls)]
    refs.append(ref("sephora_me", "x", None))
    listings = analyse(refs, fetcher).listings
    model = GridEmbedder()
    cache = EmbeddingCache(tmp_path / "emb", model.model_id)
    vectors = embeddings(listings, fetcher, model, cache, batch=2)
    assert sorted(vectors) == sorted(urls)
    assert model.calls == [2, 1]
    for v in vectors.values():
        assert np.isclose(np.linalg.norm(v), 1.0)
    again = embeddings(listings, fetcher, model, cache, batch=2)
    assert model.calls == [2, 1]  # all from the cache
    assert all(np.array_equal(again[u], vectors[u]) for u in urls)


def test_grouped_by_host() -> None:
    urls = [f"{S}2", f"{S}1", f"{F}1", f"{A}1", f"{S}1"]
    assert by_host(urls) == {
        "img-product.sephora.me": [f"{S}1", f"{S}2"],
        "media.alshaya.com": [f"{A}1"],
        "www.faces.ae": [f"{F}1"],
    }
    assert by_host([]) == {}


def test_prefetch_counts_and_skips_markers(tmp_path: Path) -> None:
    fetcher = seed_cache(tmp_path, {f"{S}a.png": as_bytes(packshot(1))})
    refs = [
        ref("sephora_me", "a", f"{S}a.png"),
        ref("sephora_me", "b", f"{S}a.png"),
        ref("sephora_me", "c", f"{S}b.png"),
        ref("sephora_me", "d", f"{S}placeholder.png"),
        ref("sephora_me", "e", None),
    ]
    seen: list[tuple[int, int]] = []
    assert prefetch(refs, fetcher, lambda d, t: seen.append((d, t))) == {
        "not_fetched": 1,
        "ok": 1,
    }
    assert sorted(seen) == [(1, 2), (2, 2)]


def test_prefetch_runs_hosts_side_by_side(tmp_path: Path) -> None:
    fetcher = seed_cache(tmp_path, {})
    refs = [ref("s", str(i), f"{h}{i}.png") for h in (S, F, A) for i in range(5)]
    assert prefetch(refs, fetcher) == {"not_fetched": 15}
    assert prefetch([], fetcher) == {}
