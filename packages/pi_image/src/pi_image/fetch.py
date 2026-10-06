"""Polite image fetch with a cache keyed by the URL's SHA-256.

Ordinary access only (ADR-0006): plain HTTP through ``pi_fetch``'s transport with its normal
browser headers, at most one request per second per host (``HostPacer``, with jitter), HTTPS on
the approved image CDNs only. A challenge or refusal (``pi_fetch.blocks``) or a 429 stops that
host for the rest of the run: nothing further is requested from it and the run reports it.

Cache layout: ``<cache>/<h[:2]>/<h>.json`` (the outcome) and ``<h>.img`` (the bytes, ``ok``
only), where ``h`` is the SHA-256 of the URL. Final outcomes (ok, a 4xx, not an image, too
large) are cached; a block, a 5xx or a network error is not, so a later run tries again.
"""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pi_fetch.blocks import detect_response
from pi_fetch.pacing import HostPacer
from pi_fetch.policy import DEFAULT_USER_AGENT
from pi_fetch.transports.base import RawResponse, Transport, TransportError
from pi_fetch.types import FetchRequest, PayloadKind
from pi_image.model import FetchStatus

#: Retailer image CDNs the owner approved (task 01a102ea-4f57). Exact host match, HTTPS only.
APPROVED_HOSTS = frozenset({"img-product.sephora.me", "media.alshaya.com", "www.faces.ae"})
MAX_BYTES = 8 * 1024 * 1024
_ACCEPT = "image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5"
_FINAL = frozenset(
    {FetchStatus.OK, FetchStatus.HTTP_ERROR, FetchStatus.NOT_IMAGE, FetchStatus.TOO_LARGE}
)
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500


@dataclass(frozen=True, slots=True)
class Fetched:
    """One URL's outcome. ``body`` is set exactly when ``status`` is ``ok``."""

    url: str
    status: FetchStatus
    detail: str | None = None
    body: bytes | None = None
    from_cache: bool = False


def url_key(url: str) -> str:
    """The cache key of a URL."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def allowed(url: str, hosts: frozenset[str] = APPROVED_HOSTS) -> bool:
    """HTTPS on an approved host (no user info, no explicit port)."""
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname in hosts
        and parts.port is None
        and parts.username is None
    )


class ImageCache:
    """Outcomes and bytes on disk; writes are atomic (temp file + rename)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = url_key(url)
        folder = self.root / key[:2]
        return folder / f"{key}.json", folder / f"{key}.img"

    def get(self, url: str) -> Fetched | None:
        """The cached final outcome, or None."""
        meta_path, body_path = self._paths(url)
        if not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("url") != url:  # a SHA-256 collision: treat as a miss
            return None
        status = FetchStatus(meta["status"])
        body = body_path.read_bytes() if status is FetchStatus.OK else None
        if status is FetchStatus.OK and not body:
            return None
        return Fetched(url, status, meta.get("detail"), body, from_cache=True)

    def put(self, outcome: Fetched) -> None:
        """Store a final outcome; anything else is ignored."""
        if outcome.status not in _FINAL:
            return
        meta_path, body_path = self._paths(outcome.url)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        if outcome.body is not None:
            _atomic_write(body_path, outcome.body)
        meta = {"url": outcome.url, "status": outcome.status.value, "detail": outcome.detail}
        _atomic_write(meta_path, json.dumps(meta, sort_keys=True).encode("utf-8"))


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


class ImageFetcher:
    """Fetches image URLs politely; ``transport=None`` is a cache-only (offline) fetcher."""

    def __init__(  # noqa: PLR0913 -- the knobs are keyword-only
        self,
        cache: ImageCache,
        transport: Transport | None,
        *,
        pacer: HostPacer | None = None,
        hosts: frozenset[str] = APPROVED_HOSTS,
        max_bytes: int = MAX_BYTES,
        user_agent: str = DEFAULT_USER_AGENT,
        on_request: Callable[[str], None] | None = None,
    ) -> None:
        self._cache = cache
        self._transport = transport
        self._pacer = pacer or HostPacer()
        self._hosts = hosts
        self._max_bytes = max_bytes
        self._headers = {"User-Agent": user_agent, "Accept": _ACCEPT}
        self._on_request = on_request
        #: Hosts stopped for this run, with the reason.
        self.stopped: dict[str, str] = {}
        self.requests = 0

    def fetch(self, url: str) -> Fetched:
        """The cached outcome, else one paced request (unless offline or the host is stopped)."""
        if not allowed(url, self._hosts):
            return Fetched(url, FetchStatus.NOT_ALLOWED_HOST, urlsplit(url).hostname)
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        host = urlsplit(url).hostname or ""
        if self._transport is None:
            return Fetched(url, FetchStatus.NOT_FETCHED, "offline: not in cache")
        if host in self.stopped:
            return Fetched(url, FetchStatus.NOT_FETCHED, f"host stopped: {self.stopped[host]}")
        self._pacer.wait(host)
        self.requests += 1
        if self._on_request is not None:
            self._on_request(url)
        request = FetchRequest(url=url, kind=PayloadKind.IMAGE, locale="en")  # type: ignore[arg-type]
        try:
            raw = self._transport.send(request, self._headers)
        except TransportError as exc:
            return Fetched(url, FetchStatus.TRANSPORT_ERROR, str(exc)[:200])
        outcome = self._classify(url, host, raw)
        self._cache.put(outcome)
        return outcome

    def _classify(  # noqa: PLR0911 -- the outcome table, one return per row
        self, url: str, host: str, raw: RawResponse
    ) -> Fetched:
        if not allowed(raw.final_url, self._hosts):
            return Fetched(url, FetchStatus.NOT_ALLOWED_HOST, f"redirected to {raw.final_url}")
        verdict = detect_response(raw.status, raw.headers, raw.body, PayloadKind.IMAGE)
        refused = raw.status == _TOO_MANY_REQUESTS or (
            verdict is not None and raw.status not in {404, 410}
        )
        if refused:
            reason = f"HTTP {raw.status}" + (f" {verdict.kind}" if verdict else "")
            self.stopped[host] = reason
            return Fetched(url, FetchStatus.BLOCKED, reason)
        self._pacer.succeeded(host)
        if raw.status >= _SERVER_ERROR:
            return Fetched(url, FetchStatus.TRANSPORT_ERROR, f"HTTP {raw.status}")
        if raw.status != 200:
            return Fetched(url, FetchStatus.HTTP_ERROR, f"HTTP {raw.status}")
        content_type = (raw.content_type or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            return Fetched(url, FetchStatus.NOT_IMAGE, content_type or "no content-type")
        if len(raw.body) > self._max_bytes:
            return Fetched(url, FetchStatus.TOO_LARGE, f"{len(raw.body)} bytes")
        if not raw.body:
            return Fetched(url, FetchStatus.NOT_IMAGE, "empty body")
        return Fetched(url, FetchStatus.OK, content_type, raw.body)
