from collections.abc import Mapping
from pathlib import Path

import pytest

from .image_fixtures import as_bytes, packshot
from pi_fetch.pacing import HostPacer
from pi_fetch.transports.base import RawResponse, TransportError
from pi_fetch.types import FetchRequest
from pi_image.fetch import ImageCache, ImageFetcher, allowed, url_key
from pi_image.model import FetchStatus

SEPHORA = "https://img-product.sephora.me/dw/image/v2/a/1_swatch.jpg?sw=1248"
FACES = "https://www.faces.ae/dw/image/v2/b/2.jpg?sw=800"
PNG = as_bytes(packshot(3))


class FakeTransport:
    """Answers from a table; records every request and its headers."""

    def __init__(self, answers: Mapping[str, RawResponse | Exception]) -> None:
        self.answers = answers
        self.sent: list[tuple[str, dict[str, str]]] = []

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        url = str(request.url)
        self.sent.append((url, dict(headers)))
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self) -> None:
        pass


def raw(
    url: str,
    status: int = 200,
    body: bytes = PNG,
    content_type: str | None = "image/png",
    headers: tuple[tuple[str, str], ...] = (),
    final_url: str | None = None,
) -> RawResponse:
    return RawResponse(
        final_url=final_url or url,
        status=status,
        headers=headers,
        body=body,
        content_type=content_type,
        elapsed_ms=1,
    )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def fetcher(
    tmp_path: Path, transport: FakeTransport | None, clock: Clock | None = None
) -> ImageFetcher:
    clock = clock or Clock()
    pacer = HostPacer(min_interval_s=1.0, jitter_s=0.0, clock=clock, sleep=clock.sleep)
    return ImageFetcher(ImageCache(tmp_path), transport, pacer=pacer)


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (SEPHORA, True),
        (FACES, True),
        ("https://media.alshaya.com/adobe/assets/x.jpg", True),
        ("http://img-product.sephora.me/a.jpg", False),  # not HTTPS
        ("https://evil.example/a.jpg", False),
        ("https://img-product.sephora.me.evil.example/a.jpg", False),
        ("https://img-product.sephora.me:8443/a.jpg", False),
        ("https://user@img-product.sephora.me/a.jpg", False),
        ("https://www.sephora.me/a.jpg", False),  # the site, not its image CDN
    ],
)
def test_allowed_hosts(url: str, ok: bool) -> None:
    assert allowed(url) is ok


def test_ok_is_cached_and_never_refetched(tmp_path: Path) -> None:
    transport = FakeTransport({SEPHORA: raw(SEPHORA)})
    first = fetcher(tmp_path, transport).fetch(SEPHORA)
    assert first.status is FetchStatus.OK
    assert first.body == PNG
    assert not first.from_cache
    assert transport.sent[0][1]["Accept"].startswith("image/")
    assert "Mozilla/5.0" in transport.sent[0][1]["User-Agent"]
    again = fetcher(tmp_path, transport).fetch(SEPHORA)
    assert again.from_cache
    assert again.body == PNG
    assert len(transport.sent) == 1
    offline = fetcher(tmp_path, None).fetch(SEPHORA)
    assert offline.status is FetchStatus.OK
    assert offline.from_cache
    key = url_key(SEPHORA)
    assert (tmp_path / key[:2] / f"{key}.img").read_bytes() == PNG


def test_paced_one_request_per_second_per_host(tmp_path: Path) -> None:
    urls = [f"https://img-product.sephora.me/{i}.png" for i in range(3)]
    clock = Clock()
    transport = FakeTransport({u: raw(u) for u in urls})
    f = fetcher(tmp_path, transport, clock)
    for u in urls:
        f.fetch(u)
    assert clock.slept == [1.0, 1.0]
    assert f.requests == 3


def test_not_allowed_host_is_never_requested(tmp_path: Path) -> None:
    transport = FakeTransport({})
    out = fetcher(tmp_path, transport).fetch("https://evil.example/a.png")
    assert out.status is FetchStatus.NOT_ALLOWED_HOST
    assert transport.sent == []


def test_redirect_off_the_cdn_is_refused(tmp_path: Path) -> None:
    transport = FakeTransport({SEPHORA: raw(SEPHORA, final_url="https://evil.example/x.png")})
    out = fetcher(tmp_path, transport).fetch(SEPHORA)
    assert out.status is FetchStatus.NOT_ALLOWED_HOST
    assert out.body is None


@pytest.mark.parametrize(
    "answer",
    [
        raw(SEPHORA, status=429, body=b"", content_type=None),
        raw(SEPHORA, status=403, body=b"Access Denied", content_type="text/html"),
        raw(
            SEPHORA,
            status=200,
            body=b"<html><title>Just a moment...</title>challenge-platform</html>",
            content_type="text/html",
            headers=(("server", "cloudflare"), ("cf-mitigated", "challenge")),
        ),
    ],
)
def test_a_block_stops_the_host_and_is_not_cached(tmp_path: Path, answer: RawResponse) -> None:
    other = "https://img-product.sephora.me/other.png"
    transport = FakeTransport({SEPHORA: answer, other: raw(other), FACES: raw(FACES)})
    f = fetcher(tmp_path, transport)
    blocked = f.fetch(SEPHORA)
    assert blocked.status is FetchStatus.BLOCKED
    assert "img-product.sephora.me" in f.stopped
    skipped = f.fetch(other)
    assert skipped.status is FetchStatus.NOT_FETCHED
    assert "host stopped" in (skipped.detail or "")
    assert f.fetch(FACES).status is FetchStatus.OK  # other hosts carry on
    assert [u for u, _ in transport.sent] == [SEPHORA, FACES]
    assert ImageCache(tmp_path).get(SEPHORA) is None  # retried on a later run


@pytest.mark.parametrize(
    ("answer", "status", "cached"),
    [
        (
            raw(SEPHORA, status=404, body=b"", content_type="text/html"),
            FetchStatus.HTTP_ERROR,
            True,
        ),
        (raw(SEPHORA, status=503, body=b"", content_type=None), FetchStatus.TRANSPORT_ERROR, False),
        (raw(SEPHORA, content_type="text/html", body=b"<p>hi</p>"), FetchStatus.NOT_IMAGE, True),
        (raw(SEPHORA, body=b""), FetchStatus.NOT_IMAGE, True),
        (raw(SEPHORA, content_type=None), FetchStatus.NOT_IMAGE, True),
        (TransportError("timeout"), FetchStatus.TRANSPORT_ERROR, False),
    ],
)
def test_failures(
    tmp_path: Path, answer: RawResponse | Exception, status: FetchStatus, cached: bool
) -> None:
    out = fetcher(tmp_path, FakeTransport({SEPHORA: answer})).fetch(SEPHORA)
    assert out.status is status
    assert out.body is None
    assert (ImageCache(tmp_path).get(SEPHORA) is not None) is cached


def test_too_large(tmp_path: Path) -> None:
    f = ImageFetcher(
        ImageCache(tmp_path),
        FakeTransport({SEPHORA: raw(SEPHORA)}),
        pacer=HostPacer(jitter_s=0.0, sleep=lambda _: None),
        max_bytes=10,
    )
    assert f.fetch(SEPHORA).status is FetchStatus.TOO_LARGE


def test_offline_miss_and_corrupt_cache(tmp_path: Path) -> None:
    assert fetcher(tmp_path, None).fetch(SEPHORA).status is FetchStatus.NOT_FETCHED
    cache = ImageCache(tmp_path)
    fetcher(tmp_path, FakeTransport({SEPHORA: raw(SEPHORA)})).fetch(SEPHORA)
    key = url_key(SEPHORA)
    (tmp_path / key[:2] / f"{key}.img").write_bytes(b"")
    assert cache.get(SEPHORA) is None  # an ok outcome without bytes is a miss
    meta = tmp_path / key[:2] / f"{key}.json"
    meta.write_text('{"url": "https://other", "status": "ok", "detail": null}', encoding="utf-8")
    assert cache.get(SEPHORA) is None


def test_on_request_hook(tmp_path: Path) -> None:
    seen: list[str] = []
    f = ImageFetcher(
        ImageCache(tmp_path),
        FakeTransport({FACES: raw(FACES)}),
        pacer=HostPacer(jitter_s=0.0, sleep=lambda _: None),
        on_request=seen.append,
    )
    f.fetch(FACES)
    assert seen == [FACES]
