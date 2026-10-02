"""Test helpers: contexts, a scripted transport, a fake clock and a local HTTP server.

Imported directly (``packages/pi_fetch/tests`` is on the pytest path). No live sites.
"""

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pi_core import (
    CollectionContext,
    FetchMethod,
    LadderRung,
    Locale,
    Market,
    SourceContext,
)
from pi_fetch.cache import LocalEvidenceStore
from pi_fetch.ladder import robots_key
from pi_fetch.pacing import HostPacer, RobotsTagger
from pi_fetch.policy import FetchPlan, FetchPolicy
from pi_fetch.transports.base import RawResponse, Transport
from pi_fetch.types import BrowserEngine, BrowserProfile, FetchRequest

NOW = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
#: The browser the owner pinned for the test source (source_id 3).
WEBKIT = BrowserProfile(engine=BrowserEngine.WEBKIT)
PINNED = {3: WEBKIT}

#: A method for each rung a context may record.
METHOD_FOR_RUNG = {
    LadderRung.SITE_DATA: FetchMethod.SITEMAP,
    LadderRung.PLAIN_HTTP: FetchMethod.PLAIN_HTTP,
    LadderRung.BROWSER: FetchMethod.PLAYWRIGHT,
    LadderRung.EGRESS_VARIATION: FetchMethod.EGRESS_VARIATION,
    LadderRung.PAID_PROXY: FetchMethod.RESIDENTIAL_PROXY,
}


def make_source_context(
    max_allowed: LadderRung = LadderRung.EGRESS_VARIATION, locale: Locale = Locale.EN
) -> SourceContext:
    return SourceContext(
        id=7,
        source_id=3,
        country=Market.UAE,
        locale=locale,
        currency="AED",
        time_zone="Asia/Dubai",
        ladder_rung_max_allowed=max_allowed,
        valid_from=NOW,
    )


def make_ctx(
    rung: LadderRung = LadderRung.PLAIN_HTTP,
    max_allowed: LadderRung = LadderRung.EGRESS_VARIATION,
    locale: Locale = Locale.EN,
) -> CollectionContext:
    return CollectionContext(
        source_context=make_source_context(max(max_allowed, rung), locale),
        crawl_run_id=11,
        connector_version="0.1.0",
        ladder_rung_used=rung,
        fetch_method=METHOD_FOR_RUNG[rung],
    )


class ScriptedTransport:
    """Returns queued responses and records every send (route, request, headers)."""

    def __init__(self, route: FetchPlan, responses: list[RawResponse]) -> None:
        self.route = route
        self.responses = responses
        self.sent: list[tuple[FetchRequest, dict[str, str]]] = []
        self.closed = False

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        self.sent.append((request, dict(headers)))
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class ScriptedFactory:
    """A ``TransportFactory`` handing every route the same response queue."""

    def __init__(self, *responses: RawResponse) -> None:
        self.responses = list(responses)
        self.transports: list[ScriptedTransport] = []

    def __call__(self, route: FetchPlan, policy: FetchPolicy) -> Transport:
        transport = ScriptedTransport(route, self.responses)
        self.transports.append(transport)
        return transport

    @property
    def sends(self) -> list[tuple[FetchPlan, FetchRequest, dict[str, str]]]:
        return [(t.route, r, h) for t in self.transports for r, h in t.sent]


def raw(
    status: int = 200,
    body: bytes = b"<html>ok</html>",
    headers: tuple[tuple[str, str], ...] = (("content-type", "text/html"),),
    url: str = "https://shop.example/p/1",
) -> RawResponse:
    content_type = next((v for k, v in headers if k.lower() == "content-type"), None)
    return RawResponse(
        final_url=url,
        status=status,
        headers=headers,
        body=body,
        content_type=content_type,
        elapsed_ms=5,
    )


class FakeClock:
    """Monotonic clock whose sleep advances time instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def fake_pacer(clock: FakeClock) -> HostPacer:
    return HostPacer(clock=clock, sleep=clock.sleep)


ROUTE_ENGINES = ("http", "chromium", "firefox", "webkit")
ROUTE_EGRESSES = ("direct", "gulf", "iproyal_ae")


def allow_all_robots(*hosts: str, text: str = "") -> RobotsTagger:
    """A tagger that already knows robots.txt of ``hosts`` (allow all by default) on every test
    route, so no robots.txt is fetched."""
    tagger = RobotsTagger()
    for host in hosts or ("shop.example",):
        for engine in ROUTE_ENGINES:
            for egress in ROUTE_EGRESSES:
                tagger.add(robots_key(host, engine, egress), text)
    return tagger


def evidence_store(tmp_path: Path) -> LocalEvidenceStore:
    return LocalEvidenceStore(tmp_path / "evidence")


Route = Callable[[BaseHTTPRequestHandler], tuple[int, list[tuple[str, str]], bytes]]


class LocalServer:
    """A ThreadingHTTPServer on 127.0.0.1 with per-path handlers; records request headers."""

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[tuple[str, dict[str, str], str]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server.requests.append((self.path, dict(self.headers), self.request_version))
                route = server.routes.get(self.path.split("?", 1)[0])
                if route is None:
                    status, headers, body = 404, [("Content-Type", "text/plain")], b"missing"
                else:
                    status, headers, body = route(self)
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host!s}:{port}"

    def static(self, path: str, body: bytes, content_type: str, *extra: tuple[str, str]) -> None:
        self.routes[path] = lambda _h: (200, [("Content-Type", content_type), *extra], body)


@contextmanager
def local_server() -> Iterator[LocalServer]:
    srv = LocalServer()
    srv.thread.start()
    try:
        yield srv
    finally:
        srv.httpd.shutdown()
        srv.httpd.server_close()
