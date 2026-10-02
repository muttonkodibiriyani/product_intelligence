"""Rungs 2 and 4: a real Playwright browser (ADR-0006 decision 2).

Stock Chromium, Firefox or WebKit as shipped by Playwright, whichever the source's pinned
``BrowserProfile`` names: no stealth plugins, no patched builds, no
fingerprint, User-Agent or navigator overrides and no persistent profile. The only additions are
Accept-Language (from the request locale) and, when asked, recording the JSON responses the page
loads by itself (``capture_json``). Every attempt gets a fresh in-memory context, closed after
it, so no cookie (e.g. a WAF's cf_clearance or _abck) is carried from one fetch to the next.

Behind a residential proxy (rung 5, ``credentials`` set) the context also:

- blocks service workers and closes every WebSocket, so no request can bypass the route guard
  (``context.route`` does not see service-worker traffic);
- aborts heavy assets and third-party hosts before they are requested
  (``pi_fetch.proxy.should_abort``);
- applies robots.txt to **every** sub-request the page makes (XHR/fetch/script included): one the
  source's robots rules do not tag ALLOWED, or any when robots.txt is unavailable, is aborted
  and never captured. Only the navigation itself is exempt; the fetcher checked it already;
- meters every finished request's bytes (``ProxyMeter``; nothing more is let through once the
  cap is reached) and logs each page's bytes and aborts (``proxy_page_bytes``);
- scrubs the proxy login from every error message.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
    ProxySettings,
    Request,
    Response,
    Route,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from pydantic import HttpUrl

from pi_fetch.proxy import ProxyCredentials, ProxyMeter, redact, should_abort
from pi_fetch.transports.base import RawResponse, TransportError
from pi_fetch.types import BrowserProfile, CapturedJson, FetchRequest, PayloadKind

_CAPTURED_RESOURCE_TYPES = frozenset({"xhr", "fetch"})
audit_log = logging.getLogger("pi_fetch.audit")
#: ``url -> True`` when robots.txt lets the crawler request it (proxied sub-requests).
SubrequestCheck = Callable[[str], bool]


def is_json_response(content_type: str | None, resource_type: str) -> bool:
    """True for a JSON XHR/fetch response the page made itself."""
    if resource_type not in _CAPTURED_RESOURCE_TYPES or content_type is None:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


class BrowserTransport:
    """One browser per (profile, egress) route, started lazily; a new context per attempt."""

    def __init__(  # noqa: PLR0913 - keyword-only; proxy pieces are all injected
        self,
        *,
        profile: BrowserProfile,
        timeout_s: float = 30.0,
        proxy: str | None = None,
        credentials: ProxyCredentials | None = None,
        meter: ProxyMeter | None = None,
        allow_hosts: frozenset[str] = frozenset(),
        subrequest_allowed: SubrequestCheck | None = None,
    ) -> None:
        if credentials is not None and (meter is None or subrequest_allowed is None):
            msg = "a residential proxy needs a byte meter and a robots check for sub-requests"
            raise ValueError(msg)
        self._profile = profile
        self._timeout_ms = timeout_s * 1000
        self._proxy = proxy
        self._credentials = credentials
        self._meter = meter
        self._allow_hosts = frozenset(h.lower() for h in allow_hosts)
        self._subrequest_allowed = subrequest_allowed
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def __repr__(self) -> str:
        proxied = "residential" if self._credentials else ("egress" if self._proxy else "direct")
        return f"BrowserTransport(engine={self._profile.engine.value}, proxy={proxied})"

    def _proxy_settings(self) -> ProxySettings | None:
        if self._credentials is not None:
            creds = self._credentials.playwright_proxy()
            return {
                "server": creds["server"],
                "username": creds["username"],
                "password": creds["password"],
            }
        return {"server": self._proxy} if self._proxy else None

    def _scrub(self, text: str) -> str:
        return redact(text, self._credentials.secrets()) if self._credentials else text

    def _new_context(self, accept_language: str) -> BrowserContext:
        if self._browser is None:
            self._playwright = sync_playwright().start()
            launcher = getattr(self._playwright, self._profile.engine.value)
            self._browser = launcher.launch(
                headless=self._profile.headless,
                proxy=self._proxy_settings(),
            )
        return self._browser.new_context(
            extra_http_headers={"Accept-Language": accept_language},
            viewport={
                "width": self._profile.viewport_width,
                "height": self._profile.viewport_height,
            },
            # Service-worker requests skip context.route: block them when guarding the proxy.
            service_workers="block" if self._credentials is not None else "allow",
        )

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        """Navigate once and wait for the network to settle; never interacts with the page."""
        started = time.monotonic()
        captured: list[CapturedJson] = []
        aborted: Counter[str] = Counter()
        if self._meter is not None:
            self._meter.check()
        before = self._meter.run_bytes if self._meter is not None else 0
        try:
            context = self._new_context(headers.get("Accept-Language", "en"))
            if self._meter is not None:
                self._guard(context, request.url.host or "", self._meter, aborted)
            page_handle = context.new_page()
            try:
                if request.capture_json:
                    page_handle.on("response", _collector(captured, self._subrequest_allowed))
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
                if self._meter is not None:
                    self._log_page(request, self._meter.run_bytes - before, aborted)
        except PlaywrightError as exc:
            msg = self._scrub(f"browser fetch of {request.url} failed: {exc.message}")
            if self._credentials is not None:
                # Do not chain: the original error text may carry the proxy login.
                raise TransportError(msg) from None
            raise TransportError(msg) from exc

    def _guard(
        self, context: BrowserContext, site_host: str, meter: ProxyMeter, aborted: Counter[str]
    ) -> None:
        """Abort what must not go through the proxy and meter the rest (proxied contexts only).

        Reasons, first match wins: ``cap`` (a sub-request could cross the byte cap), ``asset``
        (heavy or third-party, ``should_abort``), ``robots`` (not ALLOWED by robots.txt, or
        robots.txt unavailable). The first navigation request is the page the fetcher already
        robots-checked (or robots.txt itself) and is exempt from the robots check only.
        """
        allow_hosts = self._allow_hosts
        robots_ok = self._subrequest_allowed or (lambda _url: False)
        navigated = False

        def on_route(route: Route, request: Request) -> None:
            nonlocal navigated
            host = urlsplit(request.url).hostname or ""
            is_page = not navigated and request.is_navigation_request()
            navigated = navigated or is_page
            if not meter.allows_subrequest():
                reason = "cap"
            elif should_abort(request.resource_type, host, site_host, allow_hosts):
                reason = "asset"
            elif not is_page and not robots_ok(request.url):
                reason = "robots"
            else:
                route.continue_()
                return
            aborted[reason] += 1
            route.abort("blockedbyclient")

        context.route("**/*", on_route)
        # WebSockets are not routed or metered: close every one before it connects.
        context.route_web_socket("**/*", lambda ws: ws.close())
        context.on("requestfinished", _metering(meter))

    def _log_page(self, request: FetchRequest, page_bytes: int, aborted: Counter[str]) -> None:
        audit_log.info(
            "proxy page %s bytes=%s aborted=%s",
            request.url,
            page_bytes,
            dict(aborted),
            extra={
                "event": "proxy_page_bytes",
                "url": str(request.url),
                "bytes": page_bytes,
                "aborted": dict(sorted(aborted.items())),
            },
        )

    def close(self) -> None:
        """Close the browser and Playwright."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


def _metering(meter: ProxyMeter) -> Callable[[Request], None]:
    def on_finished(request: Request) -> None:
        try:
            sizes = request.sizes()
        except PlaywrightError:
            return
        meter.add(
            sizes["requestHeadersSize"] + sizes["requestBodySize"],
            sizes["responseHeadersSize"] + sizes["responseBodySize"],
        )

    return on_finished


def _collector(
    sink: list[CapturedJson], allowed: SubrequestCheck | None = None
) -> Callable[[Response], None]:
    """Record page-loaded JSON; with ``allowed``, never from a URL robots.txt does not allow."""

    def on_response(response: Response) -> None:
        if not is_json_response(
            response.header_value("content-type"), response.request.resource_type
        ):
            return
        if allowed is not None and not allowed(response.url):
            return
        try:
            body = response.body()
        except PlaywrightError:
            # The page discarded the response (e.g. a redirect); nothing to record.
            return
        sink.append(CapturedJson(url=HttpUrl(response.url), status=response.status, body=body))

    return on_response
