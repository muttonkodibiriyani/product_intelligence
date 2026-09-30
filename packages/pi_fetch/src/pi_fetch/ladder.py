"""The fetcher: one polite attempt per request on a permitted rung, never rung 3.

``Fetcher.fetch`` resolves the rung from the context (``policy.plan``), waits for the host's
pacing slot, sends the request **once** and returns a ``FetchResult``. A block or challenge is
returned as a result with ``block`` set; it is never solved, waited out or retried, and the
fetcher does not climb to another rung by itself. Moving a context up the ladder (0 → 1 → 2 → 4,
skipping 3; 5 only with owner approval) is a separate, audited decision: ``policy.next_rung``.
The browser engine is pinned per source (``FetchPolicy.browsers``) and never switched here.

Before any request to a URL the fetcher reads the host's robots.txt (once, paced) and, unless
the source is configured ``tag_only``, refuses a disallowed URL, or any URL when robots.txt is
unavailable, with ``RobotsRefusedError``. A 429 backs the host off (``HostPacer.back_off``) and
is returned as a blocked result, so its listings are recorded not observed.
When that returns None the source is marked blocked and a Proxy Decision Report is written
(ADR-0006 decision 4).
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import HttpUrl

from pi_core import CollectionContext, Locale, Market
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
from pi_fetch.transports.base import RawResponse, Transport, TransportError
from pi_fetch.transports.browser import BrowserTransport
from pi_fetch.transports.http import HttpTransport
from pi_fetch.types import (
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
_TOO_MANY_REQUESTS = 429
#: robots.txt statuses that mean "no robots.txt": everything allowed (RFC 9309 §2.3.1.3).
_ROBOTS_ABSENT = frozenset({404, 410})
_ROBOTS_ACCEPT = "text/plain,*/*;q=0.8"


#: Builds the transport for a route; the fetcher keeps one per (engine, egress).
TransportFactory = Callable[[FetchPlan, FetchPolicy], Transport]


def default_transport(route: FetchPlan, policy: FetchPolicy) -> Transport:
    """httpx for the HTTP engine, the pinned stock Playwright browser for the browser engine."""
    proxy = route.egress.proxy_url()
    if route.browser is not None:
        return BrowserTransport(profile=route.browser, timeout_s=policy.timeout_s, proxy=proxy)
    return HttpTransport(timeout_s=policy.timeout_s, proxy=proxy)


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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._policy = policy
        self._evidence = evidence
        self._pacer = pacer or HostPacer()
        self._cache = cache
        self._robots = robots or RobotsTagger()
        self._factory = transport_factory
        self._clock = clock
        self._transports: dict[tuple[Engine, str, BrowserProfile | None], Transport] = {}

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close every transport opened so far."""
        for transport in self._transports.values():
            transport.close()
        self._transports.clear()

    def _transport(self, route: FetchPlan) -> Transport:
        key = (route.engine, route.egress.name, route.browser)
        transport = self._transports.get(key)
        if transport is None:
            transport = self._factory(route, self._policy)
            self._transports[key] = transport
        return transport

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
        interval = self._policy.interval_for(source_id)
        robots = self._robots_tag(request, route, interval)
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
        raw = self._transport(route).send(request, headers)
        self._pace_after(host, raw, retrieved_at)
        result = self._result(request, route, raw, retrieved_at)
        self._audit(result, ctx, robots)
        return result

    def _pace_after(self, host: str, raw: RawResponse, now: datetime) -> None:
        retry_after = parse_retry_after(redact_headers(raw.headers).get("retry-after"), now)
        if raw.status != _TOO_MANY_REQUESTS:
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

    def _robots_tag(self, request: FetchRequest, route: FetchPlan, interval: float) -> RobotsTag:
        host = request.url.host or ""
        if not self._robots.known(host):
            self._load_robots(request, route, interval)
        return self._robots.tag(host, str(request.url))

    def _load_robots(self, request: FetchRequest, route: FetchPlan, interval: float) -> None:
        """GET the host's robots.txt once over plain HTTP on the request's egress, paced."""
        host = request.url.host or ""
        robots_url = HttpUrl(
            f"{request.url.scheme}://{request.url.host}{_port(request.url)}/robots.txt"
        )
        robots_request = FetchRequest(url=robots_url, kind=PayloadKind.HTML, locale=request.locale)
        http_route = FetchPlan(
            rung=route.rung, method=route.method, engine=Engine.HTTP, egress=route.egress
        )
        headers = {"User-Agent": self._policy.user_agent, "Accept": _ROBOTS_ACCEPT}
        self._pacer.wait(host, interval)
        try:
            raw = self._transport(http_route).send(robots_request, headers)
        except TransportError:
            status: int | None = None
        else:
            status = raw.status
            self._pace_after(host, raw, self._clock())
        if status is not None and 200 <= status < 300:
            self._robots.add(host, raw.body.decode("utf-8", errors="replace"))
        elif status in _ROBOTS_ABSENT:
            self._robots.add(host, "")
        else:
            self._robots.mark_unavailable(host)
        audit_log.info(
            "robots.txt %s status=%s",
            host,
            status,
            extra={"event": "robots_loaded", "host": host, "http_status": status},
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
                "block_vendor": result.block.vendor.value if result.block else None,
                "block_reason": result.block.reason if result.block else None,
                "robots": robots.value,
                "from_cache": result.from_cache,
                "evidence_uri": result.evidence_uri,
            },
        )


def _port(url: HttpUrl) -> str:
    default = {"http": 80, "https": 443}.get(url.scheme)
    return "" if url.port in {None, default} else f":{url.port}"
