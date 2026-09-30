"""Rungs 0, 1, 4 and 5: plain HTTP over httpx (ADR-0006 decision 1).

Normal headers and session reuse, nothing else: HTTP/1.1 via httpx's default TLS stack, with no
TLS/JA3 or HTTP/2 fingerprint impersonation (``http2=False`` explicitly). Session cookies live
in memory for this transport's lifetime only, like any HTTP client; they are never exported,
persisted or injected, and results never carry them.
"""

import time
from collections.abc import Mapping

import httpx

from pi_fetch.transports.base import RawResponse, TransportError
from pi_fetch.types import FetchRequest


class HttpTransport:
    """One httpx session per (engine, egress) route."""

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        proxy: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            http2=False,
            follow_redirects=True,
            timeout=timeout_s,
            proxy=proxy,
            transport=transport,
        )

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        """GET the URL once. Any HTTP status is returned; only a failed exchange raises."""
        started = time.monotonic()
        try:
            response = self._client.get(str(request.url), headers=dict(headers))
        except httpx.HTTPError as exc:
            msg = f"GET {request.url} failed: {type(exc).__name__}: {exc}"
            raise TransportError(msg) from exc
        return RawResponse(
            final_url=str(response.url),
            status=response.status_code,
            headers=tuple(response.headers.multi_items()),
            body=response.content,
            content_type=response.headers.get("content-type"),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    def close(self) -> None:
        """Close the session."""
        self._client.close()
