"""The fetcher: one polite attempt per request on a permitted rung, never rung 3.

``Fetcher.fetch`` resolves the rung from the context (``policy.plan``), waits for the host's
pacing slot, sends the request **once** and returns a ``FetchResult``. A block or challenge is
returned as a result with ``block`` set; it is never solved, waited out or retried, and the
fetcher does not climb to another rung by itself. Moving a context up the ladder (0 → 1 → 2 → 4,
skipping 3; 5 only with owner approval) is a separate, audited decision: ``policy.next_rung``.
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
from pi_fetch.pacing import HostPacer, RobotsTag, RobotsTagger, parse_retry_after
from pi_fetch.policy import Engine, FetchPlan, FetchPolicy, plan
from pi_fetch.transports.base import RawResponse, Transport
from pi_fetch.transports.browser import BrowserTransport
from pi_fetch.transports.http import HttpTransport
from pi_fetch.types import FetchRequest, FetchResult, PayloadKind, redact_headers

audit_log = logging.getLogger("pi_fetch.audit")

_ACCEPT: dict[PayloadKind, str] = {
    PayloadKind.HTML: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    PayloadKind.JSON: "application/json,text/plain;q=0.9,*/*;q=0.8",
    PayloadKind.XML: "application/xml,text/xml;q=0.9,*/*;q=0.8",
    PayloadKind.IMAGE: "image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5",
}
_NOT_MODIFIED = 304

#: Builds the transport for a route; the fetcher keeps one per (engine, egress).
TransportFactory = Callable[[FetchPlan, FetchPolicy], Transport]


def default_transport(route: FetchPlan, policy: FetchPolicy) -> Transport:
    """httpx for the HTTP engine, stock Playwright Chromium for the browser engine."""
    proxy = route.egress.proxy_url()
    if route.engine is Engine.BROWSER:
        return BrowserTransport(timeout_s=policy.timeout_s, proxy=proxy)
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
        self._robots = robots
        self._factory = transport_factory
        self._clock = clock
        self._transports: dict[tuple[Engine, str], Transport] = {}

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
        key = (route.engine, route.egress.name)
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
        """Fetch once. Raises ``LadderPolicyError`` (config) or ``TransportError`` (network)."""
        route = plan(request, ctx, self._policy)
        host = request.url.host or ""
        headers = self._headers(request, ctx)
        self._pacer.wait(host)
        retrieved_at = self._clock()
        raw = self._transport(route).send(request, headers)
        retry_after = parse_retry_after(redact_headers(raw.headers).get("retry-after"))
        if retry_after is not None:
            self._pacer.defer(host, retry_after)
        result = self._result(request, route, raw, retrieved_at)
        self._audit(result, ctx, host)
        return result

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

    def _audit(self, result: FetchResult, ctx: CollectionContext, host: str) -> None:
        robots = (
            self._robots.tag(host, str(result.request.url)) if self._robots else RobotsTag.UNKNOWN
        )
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
                "http_status": result.http_status,
                "block_vendor": result.block.vendor.value if result.block else None,
                "block_reason": result.block.reason if result.block else None,
                "robots": robots.value,
                "from_cache": result.from_cache,
                "evidence_uri": result.evidence_uri,
            },
        )
