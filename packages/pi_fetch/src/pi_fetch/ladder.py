"""The fetcher: one polite attempt per request on a permitted rung, never rung 3.

``Fetcher.fetch`` resolves the rung from the context (``policy.plan``), waits for the host's
pacing slot, sends the request **once** and returns a ``FetchResult``. A block or challenge is
returned as a result with ``block`` set; it is never solved, waited out or retried, and the
fetcher does not climb to another rung by itself. Moving a context up the ladder (0 → 1 → 2 → 4,
skipping 3; 5 only with owner approval) is a separate, audited decision: ``policy.next_rung``.
The browser engine is pinned per source (``FetchPolicy.browsers``) and never switched here.

Before any request to a URL the fetcher reads the host's robots.txt (once, paced) and, unless
the source is configured ``tag_only``, refuses a disallowed URL, or any URL when robots.txt is
unavailable, with ``RobotsRefusedError``. robots.txt counts as unavailable on any status other
than 2xx, 404 or 410 (401/403/429 included), on a transport error, and on a 2xx HTML page: a
deliberate deviation from RFC 9309 §2.3.1.3, which treats 4xx as "no robots.txt" (ADR-0006
consequences). Groups are chosen by the product token of our User-Agent, else ``*``.
A 429 backs the host off (``HostPacer.back_off``) and
is returned with a RATE_LIMITED verdict (``rate_limited``): its listings are recorded not
observed, but it does not mark the source blocked (only CHALLENGE and BLOCKED verdicts do).
When ``next_rung`` returns None after real blocks, the source is marked blocked and a Proxy
Decision Report is written (ADR-0006 decision 4).

robots.txt is fetched through the **same route** as the page (engine, pinned browser, egress and
proxy): never via another engine or network path as a fallback. It is read once per (host, route)
in a fresh browser context, paced by the HostPacer and counted toward its back-off, and the
``robots_loaded`` audit event names the transport, engine and egress. A browser shows a plain
text file as a ``<pre>`` viewer page; ``robots_text_from_viewer`` extracts it strictly, and any
other shape (an HTML page, a challenge) makes robots.txt unavailable.

Residential-proxy sources (``FetchPolicy.residential_proxy``, owner decision for ulta.ae) are
stricter: the first CHALLENGE/BLOCKED verdict (a challenge marker at any status: 403, 429, 503),
401/403/407, a proxy connect/auth error or unreadable proxy secret, or a second 429 in a row,
robots.txt included, **stops the
source for the run** (``SourceStoppedError`` on every later fetch; no retry, no egress or engine
switch), and so does reaching the proxy byte cap. ``Fetcher.proxy_usage()`` gives the proxy bytes
for the run manifest and ``Fetcher.stopped_sources()`` the stop reasons.
"""

import html
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from pydantic import HttpUrl

from pi_core import CollectionContext, Locale, Market
from pi_core.types import DbId
from pi_fetch.blocks import detect_response
from pi_fetch.cache import EvidenceStore, ValidatorCache, entry_from_headers
from pi_fetch.pacing import (
    HostPacer,
    RobotsMode,
    RobotsRefusedError,
    RobotsTag,
    RobotsTagger,
    parse_retry_after,
)
from pi_fetch.policy import Engine, FetchPlan, FetchPolicy, plan
from pi_fetch.proxy import (
    ProxyBudgetExceededError,
    ProxyConfigError,
    ProxyCredentials,
    ProxyMeter,
    ProxyUsage,
    SecretManagerReader,
    SecretReader,
    load_credentials,
)
from pi_fetch.transports.base import RawResponse, Transport, TransportError
from pi_fetch.transports.browser import BrowserTransport
from pi_fetch.transports.http import HttpTransport
from pi_fetch.types import (
    TOO_MANY_REQUESTS,
    BlockVerdict,
    BrowserProfile,
    FetchRequest,
    FetchResult,
    PayloadKind,
    redact_headers,
)

audit_log = logging.getLogger("pi_fetch.audit")

_ACCEPT: dict[PayloadKind, str] = {
    PayloadKind.HTML: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    PayloadKind.JSON: "application/json,text/plain;q=0.9,*/*;q=0.8",
    PayloadKind.XML: "application/xml,text/xml;q=0.9,*/*;q=0.8",
    PayloadKind.IMAGE: "image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5",
}
_NOT_MODIFIED = 304
#: robots.txt statuses that mean "no robots.txt": everything allowed. DEVIATION from RFC 9309
#: §2.3.1.3, which allows every 4xx: here every other non-2xx (401/403/418/429 included), a
#: transport error or a 2xx HTML page makes robots.txt unavailable and refuses the host. That is
#: stricter than the RFC on purpose (ADR-0006 consequences; coordinator decision).
_ROBOTS_ABSENT = frozenset({404, 410})
_ROBOTS_ACCEPT = "text/plain,*/*;q=0.8"
#: Statuses that stop a residential-proxy source for the run (with CHALLENGE/BLOCKED verdicts).
_STOP_STATUSES = frozenset({401, 403, 407})
#: A plain 429 backs the host off; this many in a row stop a residential-proxy source.
_MAX_CONSECUTIVE_429 = 2
#: The whole document a browser renders for a text/plain response: head (no script), one <pre>.
_VIEWER_RE = re.compile(
    r"\A\s*<html[^>]*>\s*<head>(?P<head>.*?)</head>\s*<body[^>]*>\s*"
    r"<pre[^>]*>(?P<text>[^<]*)</pre>\s*</body>\s*</html>\s*\Z",
    re.DOTALL | re.IGNORECASE,
)


#: Builds the transport for a route; the fetcher keeps one per (engine, egress).
TransportFactory = Callable[[FetchPlan, FetchPolicy], Transport]
#: Builds the transport for a residential-proxy route from its credentials and the run's meter.
ProxyTransportFactory = Callable[[FetchPlan, FetchPolicy, ProxyCredentials, ProxyMeter], Transport]


class SourceStoppedError(Exception):
    """The source was stopped for this run (first block/401/403 or proxy byte cap); no request
    was sent. The run must mark the source blocked and move on."""

    def __init__(self, source_id: DbId, reason: str) -> None:
        super().__init__(f"source {source_id} stopped for this run: {reason}")
        self.source_id = source_id
        self.reason = reason


def default_transport(route: FetchPlan, policy: FetchPolicy) -> Transport:
    """httpx for the HTTP engine, the pinned stock Playwright browser for the browser engine."""
    proxy = route.egress.proxy_url()
    if route.browser is not None:
        return BrowserTransport(profile=route.browser, timeout_s=policy.timeout_s, proxy=proxy)
    return HttpTransport(timeout_s=policy.timeout_s, proxy=proxy)


def default_proxy_transport(
    route: FetchPlan, policy: FetchPolicy, credentials: ProxyCredentials, meter: ProxyMeter
) -> Transport:
    """The pinned stock browser through the residential proxy, guarded and metered."""
    if route.browser is None or route.proxy is None:
        msg = "the residential proxy carries only the pinned browser"
        raise ValueError(msg)
    return BrowserTransport(
        profile=route.browser,
        timeout_s=policy.timeout_s,
        credentials=credentials,
        meter=meter,
        allow_hosts=route.proxy.allow_hosts,
    )


def robots_text_from_viewer(document: str) -> str | None:
    """The robots.txt text from a browser's plain-text viewer page, or None for any other page.

    Strict: the document must be exactly ``<html><head>…</head><body><pre>TEXT</pre></body>
    </html>`` with no script in the head and no markup inside the ``<pre>``.
    """
    found = _VIEWER_RE.fullmatch(document)
    if found is None or "<script" in found.group("head").lower():
        return None
    return html.unescape(found.group("text"))


def accept_language(locale: Locale, market: Market) -> str:
    """e.g. ``ar-AE,ar;q=0.9,en;q=0.8`` for Arabic in the UAE."""
    primary = f"{locale.value}-{market.value},{locale.value};q=0.9"
    return primary if locale is Locale.EN else f"{primary},en;q=0.8"


class Fetcher:
    """Owns pacing, transports, block detection, evidence and the audit log for all fetches."""

    def __init__(  # noqa: PLR0913 - keyword-only collaborators, all injectable for tests
        self,
        *,
        policy: FetchPolicy,
        evidence: EvidenceStore,
        pacer: HostPacer | None = None,
        cache: ValidatorCache | None = None,
        robots: RobotsTagger | None = None,
        transport_factory: TransportFactory = default_transport,
        proxy_transport_factory: ProxyTransportFactory = default_proxy_transport,
        secret_reader: SecretReader | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._policy = policy
        self._evidence = evidence
        self._pacer = pacer or HostPacer()
        self._cache = cache
        self._robots = robots or RobotsTagger(self._policy.robots_group_agent)
        self._factory = transport_factory
        self._proxy_factory = proxy_transport_factory
        self._secret_reader = secret_reader
        self._clock = clock
        self._transports: dict[tuple[Engine, str, BrowserProfile | None], Transport] = {}
        self._meters: dict[str, ProxyMeter] = {}
        self._stopped: dict[DbId, str] = {}
        self._consecutive_429: dict[DbId, int] = {}

    def proxy_usage(self) -> tuple[ProxyUsage, ...]:
        """Bytes through each residential proxy so far this run (for the run manifest)."""
        return tuple(meter.usage() for meter in self._meters.values())

    def stopped_sources(self) -> Mapping[DbId, str]:
        """Sources stopped for this run, with the reason."""
        return dict(self._stopped)

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close every transport opened so far and log the run's proxy usage."""
        for transport in self._transports.values():
            transport.close()
        self._transports.clear()
        for usage in self.proxy_usage():
            audit_log.info(
                "proxy usage %s: %s bytes (cap %s)",
                usage.egress,
                usage.total,
                usage.byte_cap,
                extra={"event": "proxy_usage", **usage.model_dump()},
            )

    def _transport(self, route: FetchPlan) -> Transport:
        key = (route.engine, route.egress.name, route.browser)
        transport = self._transports.get(key)
        if transport is None:
            if route.proxy is None:
                transport = self._factory(route, self._policy)
            else:
                reader = self._secret_reader or SecretManagerReader()
                credentials = load_credentials(reader, route.proxy.secret_resource)
                transport = self._proxy_factory(
                    route, self._policy, credentials, self._meter(route)
                )
            self._transports[key] = transport
        return transport

    def _meter(self, route: FetchPlan) -> ProxyMeter:
        if route.proxy is None:  # pragma: no cover - only called for proxied routes
            msg = "no proxy on this route"
            raise ValueError(msg)
        meter = self._meters.get(route.egress.name)
        if meter is None:
            meter = ProxyMeter.for_config(route.proxy)
            self._meters[route.egress.name] = meter
        return meter

    def _stop(self, source_id: DbId, reason: str) -> None:
        if source_id in self._stopped:
            return
        self._stopped[source_id] = reason
        audit_log.warning(
            "source %s stopped for this run: %s",
            source_id,
            reason,
            extra={"event": "source_stopped", "source_id": source_id, "reason": reason},
        )

    def _send(
        self, route: FetchPlan, request: FetchRequest, headers: dict[str, str], source_id: DbId
    ) -> RawResponse:
        """One send; a proxied route checks and afterwards enforces the byte cap."""
        try:
            return self._transport(route).send(request, headers)
        except ProxyBudgetExceededError:
            self._stop(source_id, "proxy_byte_cap")
            raise
        except (TransportError, ProxyConfigError) as exc:
            if route.proxy is not None:
                # Proxy auth/connect failure or unreadable secret: stop, never fall back to
                # direct. Messages are already scrubbed of the proxy login.
                self._stop(source_id, f"proxy error: {exc}")
            raise
        finally:
            if route.proxy is not None and self._meter(route).exhausted:
                self._stop(source_id, "proxy_byte_cap")

    def _headers(self, request: FetchRequest, ctx: CollectionContext) -> dict[str, str]:
        headers = {
            "User-Agent": self._policy.user_agent,
            "Accept": _ACCEPT[request.kind],
            "Accept-Language": accept_language(request.locale, ctx.market),
        }
        headers.update(request.headers)
        if self._cache is not None:
            entry = self._cache.get(str(request.url), request.locale)
            if entry is not None:
                headers.update(entry.conditional_headers())
        return headers

    def fetch(self, request: FetchRequest, ctx: CollectionContext) -> FetchResult:
        """Fetch once. Raises ``LadderPolicyError`` (config), ``RobotsRefusedError`` (robots.txt,
        nothing sent) or ``TransportError`` (network)."""
        route = plan(request, ctx, self._policy)
        host = request.url.host or ""
        source_id = ctx.source_context.source_id
        self._check_not_stopped(source_id)
        interval = self._policy.interval_for(source_id)
        robots = self._robots_tag(request, route, interval, source_id)
        self._check_not_stopped(source_id)
        if robots is not RobotsTag.ALLOWED and (
            self._policy.robots_mode_for(source_id) is RobotsMode.OBEY
        ):
            audit_log.warning(
                "robots refused %s (%s)",
                request.url,
                robots.value,
                extra={"event": "robots_refused", "url": str(request.url), "robots": robots.value},
            )
            raise RobotsRefusedError(str(request.url), robots)
        headers = self._headers(request, ctx)
        self._pacer.wait(host, interval)
        retrieved_at = self._clock()
        raw = self._send(route, request, headers, source_id)
        self._pace_after(host, raw, retrieved_at)
        result = self._result(request, route, raw, retrieved_at)
        self._audit(result, ctx, robots)
        self._maybe_stop(source_id, result.http_status, result.block)
        return result

    def _check_not_stopped(self, source_id: DbId) -> None:
        reason = self._stopped.get(source_id)
        if reason is not None:
            raise SourceStoppedError(source_id, reason)

    def _maybe_stop(self, source_id: DbId, status: int | None, block: BlockVerdict | None) -> None:
        """Residential-proxy sources stop at the first challenge, block, 401 or 403."""
        if self._policy.proxy_for(source_id) is None:
            return
        if block is not None and block.marks_source_blocked:
            self._stop(source_id, f"{block.kind.value}: {block.reason}")
        elif status in _STOP_STATUSES:
            self._stop(source_id, f"http {status}")
        elif status == TOO_MANY_REQUESTS:
            count = self._consecutive_429.get(source_id, 0) + 1
            self._consecutive_429[source_id] = count
            if count >= _MAX_CONSECUTIVE_429:
                self._stop(source_id, f"{count} consecutive 429s")
            return
        self._consecutive_429[source_id] = 0

    def _pace_after(self, host: str, raw: RawResponse, now: datetime) -> None:
        retry_after = parse_retry_after(redact_headers(raw.headers).get("retry-after"), now)
        if raw.status != TOO_MANY_REQUESTS:
            self._pacer.succeeded(host)
            if retry_after is not None:
                self._pacer.defer(host, retry_after)
            return
        delay, clipped = self._pacer.back_off(host, retry_after)
        if clipped:
            audit_log.warning(
                "429 from %s asks for more than the %ss cap; stop the host for this run",
                host,
                delay,
                extra={"event": "backoff_capped", "host": host, "defer_s": delay},
            )

    def _robots_tag(
        self, request: FetchRequest, route: FetchPlan, interval: float, source_id: DbId
    ) -> RobotsTag:
        key = _robots_key(request.url.host or "", route)
        if not self._robots.known(key):
            self._load_robots(request, route, interval, source_id)
        return self._robots.tag(key, str(request.url))

    def _load_robots(
        self, request: FetchRequest, route: FetchPlan, interval: float, source_id: DbId
    ) -> None:
        """GET the host's robots.txt once per route, through that same route, paced."""
        host = request.url.host or ""
        key = _robots_key(host, route)
        robots_url = HttpUrl(
            f"{request.url.scheme}://{request.url.host}{_port(request.url)}/robots.txt"
        )
        robots_request = FetchRequest(url=robots_url, kind=PayloadKind.HTML, locale=request.locale)
        headers = {"User-Agent": self._policy.user_agent, "Accept": _ROBOTS_ACCEPT}
        self._pacer.wait(host, interval)
        text: str | None = None
        try:
            raw = self._send(route, robots_request, headers, source_id)
        except TransportError:
            status: int | None = None
        else:
            status = raw.status
            self._pace_after(host, raw, self._clock())
            text = _robots_text(route, raw)
            self._maybe_stop(
                source_id,
                status,
                detect_response(raw.status, raw.headers, raw.body, PayloadKind.HTML),
            )
        if text is not None:
            self._robots.add(key, text)
        elif status in _ROBOTS_ABSENT:
            self._robots.add(key, "")
        else:
            self._robots.mark_unavailable(key)
        audit_log.info(
            "robots.txt %s status=%s via %s",
            host,
            status,
            route.engine.value,
            extra={
                "event": "robots_loaded",
                "host": host,
                "http_status": status,
                "readable": text is not None,
                "transport": "playwright" if route.engine is Engine.BROWSER else "httpx",
                "engine": route.browser.engine.value if route.browser else route.engine.value,
                "egress": route.egress.name,
                "ladder_rung_used": int(route.rung),
            },
        )

    def _result(
        self, request: FetchRequest, route: FetchPlan, raw: RawResponse, retrieved_at: datetime
    ) -> FetchResult:
        headers = redact_headers(raw.headers)
        status, body, content_type, from_cache = raw.status, raw.body, raw.content_type, False
        entry = self._cache.get(str(request.url), request.locale) if self._cache else None
        if status == _NOT_MODIFIED and entry is not None:
            # Unchanged since the stored payload: reuse it, and say so.
            status, content_type, from_cache = entry.http_status, entry.content_type, True
            body = self._evidence.get(entry.evidence_uri)
            evidence_uri = entry.evidence_uri
            block = None
        else:
            block = detect_response(raw.status, raw.headers, raw.body, request.kind)
            evidence_uri = self._evidence.put(raw.body, raw.content_type)
        result = FetchResult(
            request=request,
            final_url=HttpUrl(raw.final_url),
            http_status=status,
            content_type=content_type,
            body=body,
            headers=headers,
            captured_json=raw.captured_json,
            ladder_rung_used=route.rung,
            fetch_method=route.method,
            egress=route.egress.name,
            browser=route.browser,
            retrieved_at=retrieved_at,
            elapsed_ms=raw.elapsed_ms,
            from_cache=from_cache,
            block=block,
            evidence_uri=evidence_uri,
        )
        if self._cache is not None and result.ok and not from_cache:
            new_entry = entry_from_headers(
                headers, evidence_uri=evidence_uri, http_status=status, content_type=content_type
            )
            if new_entry is not None:
                self._cache.put(str(request.url), request.locale, new_entry)
        return result

    def _audit(self, result: FetchResult, ctx: CollectionContext, robots: RobotsTag) -> None:
        audit_log.info(
            "fetch %s rung=%s method=%s egress=%s status=%s block=%s robots=%s",
            result.request.url,
            result.ladder_rung_used.name,
            result.fetch_method.value,
            result.egress,
            result.http_status,
            result.block.vendor.value if result.block else "none",
            robots.value,
            extra={
                "crawl_run_id": ctx.crawl_run_id,
                "source_context_id": ctx.source_context.id,
                "url": str(result.request.url),
                "ladder_rung_used": int(result.ladder_rung_used),
                "fetch_method": result.fetch_method.value,
                "egress": result.egress,
                "browser_engine": result.browser.engine.value if result.browser else None,
                "browser_headless": result.browser.headless if result.browser else None,
                "browser_device": result.browser.device.value if result.browser else None,
                "http_status": result.http_status,
                "block_kind": result.block.kind.value if result.block else None,
                "block_vendor": result.block.vendor.value if result.block else None,
                "rate_limited": result.rate_limited,
                "block_reason": result.block.reason if result.block else None,
                "robots": robots.value,
                "from_cache": result.from_cache,
                "evidence_uri": result.evidence_uri,
            },
        )


def _port(url: HttpUrl) -> str:
    default = {"http": 80, "https": 443}.get(url.scheme)
    return "" if url.port in {None, default} else f":{url.port}"


def robots_key(host: str, engine: str, egress: str) -> str:
    """The ``RobotsTagger`` key: robots.txt is cached per host **and** route (engine, egress), so
    each route reads it, and may fail to, on its own. ``engine`` is ``http`` or a browser name."""
    return f"{host.lower()}|{engine}|{egress}"


def _robots_key(host: str, route: FetchPlan) -> str:
    engine = route.browser.engine.value if route.browser else route.engine.value
    return robots_key(host, engine, route.egress.name)


def _robots_text(route: FetchPlan, raw: RawResponse) -> str | None:
    """The robots.txt text of a 2xx response, or None when it is unreadable (e.g. HTML)."""
    if not 200 <= raw.status < 300:
        return None
    if route.engine is Engine.BROWSER:
        # The transport returns the rendered document; the file itself must be plain text.
        if _is_html(raw.content_type, b""):
            return None
        text = robots_text_from_viewer(raw.body.decode("utf-8", errors="replace"))
        return None if text is None else text.removeprefix("\ufeff")
    if _is_html(raw.content_type, raw.body):
        return None
    return raw.body.decode("utf-8-sig", errors="replace")


def _is_html(content_type: str | None, body: bytes) -> bool:
    """A 2xx robots.txt that is really an HTML page (soft 404, block or challenge page)."""
    if content_type is not None and "html" in content_type.lower():
        return True
    head = body.lstrip(b"\xef\xbb\xbf \t\r\n")[:15].lower()
    return head.startswith((b"<!doctype", b"<html"))
