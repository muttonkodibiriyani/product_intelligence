"""Rungs 2 and 4: a real Playwright browser (ADR-0006 decision 2).

Stock Chromium, Firefox or WebKit as shipped by Playwright, whichever the source's pinned
``BrowserProfile`` names: no stealth plugins, no patched builds, no
fingerprint, User-Agent or navigator overrides and no persistent profile. The only additions are
Accept-Language (from the request locale) and, when asked, recording the JSON responses the page
loads by itself (``capture_json``). Every attempt gets a fresh in-memory context, closed after
it, so no cookie (e.g. a WAF's cf_clearance or _abck) is carried from one fetch to the next.
"""

import time
from collections.abc import Callable, Mapping

from playwright.sync_api import Browser, BrowserContext, Playwright, Response, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from pydantic import HttpUrl

from pi_fetch.transports.base import RawResponse, TransportError
from pi_fetch.types import BrowserProfile, CapturedJson, FetchRequest, PayloadKind

_CAPTURED_RESOURCE_TYPES = frozenset({"xhr", "fetch"})


def is_json_response(content_type: str | None, resource_type: str) -> bool:
    """True for a JSON XHR/fetch response the page made itself."""
    if resource_type not in _CAPTURED_RESOURCE_TYPES or content_type is None:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


class BrowserTransport:
    """One browser per (profile, egress) route, started lazily; a new context per attempt."""

    def __init__(
        self,
        *,
        profile: BrowserProfile,
        timeout_s: float = 30.0,
        proxy: str | None = None,
    ) -> None:
        self._profile = profile
        self._timeout_ms = timeout_s * 1000
        self._proxy = proxy
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def _new_context(self, accept_language: str) -> BrowserContext:
        if self._browser is None:
            self._playwright = sync_playwright().start()
            launcher = getattr(self._playwright, self._profile.engine.value)
            self._browser = launcher.launch(
                headless=self._profile.headless,
                proxy={"server": self._proxy} if self._proxy else None,
            )
        return self._browser.new_context(
            extra_http_headers={"Accept-Language": accept_language},
            viewport={
                "width": self._profile.viewport_width,
                "height": self._profile.viewport_height,
            },
        )

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        """Navigate once and wait for the network to settle; never interacts with the page."""
        started = time.monotonic()
        captured: list[CapturedJson] = []
        try:
            context = self._new_context(headers.get("Accept-Language", "en"))
            page_handle = context.new_page()
            try:
                if request.capture_json:
                    page_handle.on("response", _collector(captured))
                extra = {k: v for k, v in headers.items() if k in request.headers}
                if extra:
                    page_handle.set_extra_http_headers(extra)
                response = page_handle.goto(
                    str(request.url), wait_until="networkidle", timeout=self._timeout_ms
                )
                if response is None:
                    msg = f"navigation to {request.url} returned no response"
                    raise TransportError(msg)
                body = (
                    page_handle.content().encode()
                    if request.kind is PayloadKind.HTML
                    else response.body()
                )
                return RawResponse(
                    final_url=response.url,
                    status=response.status,
                    headers=tuple((h["name"], h["value"]) for h in response.headers_array()),
                    body=body,
                    content_type=response.header_value("content-type"),
                    captured_json=tuple(captured),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            finally:
                page_handle.close()
                context.close()
        except PlaywrightError as exc:
            msg = f"browser fetch of {request.url} failed: {exc.message}"
            raise TransportError(msg) from exc

    def close(self) -> None:
        """Close the browser and Playwright."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


def _collector(sink: list[CapturedJson]) -> Callable[[Response], None]:
    def on_response(response: Response) -> None:
        if not is_json_response(
            response.header_value("content-type"), response.request.resource_type
        ):
            return
        try:
            body = response.body()
        except PlaywrightError:
            # The page discarded the response (e.g. a redirect); nothing to record.
            return
        sink.append(CapturedJson(url=HttpUrl(response.url), status=response.status, body=body))

    return on_response
