"""Playwright adapter: stock Chromium, default context options, nothing tuned for the site.

This is the only module that imports Playwright. The unit tests never load it (no browser in
CI); ``tests/test_browser_pw_live.py`` drives it against a local site inside the job image and
asserts that exactly the gate-allowed requests reached the server. It stays thin: translate,
never decide. Decisions are the ``Gate``'s (policy) and the job's (run).

Process-model flags (``--no-sandbox``, ``--single-process`` ...) come from ``CHROMIUM_ARGS`` so
the same image runs under Docker on a host without user namespaces or under gVisor; they change
how Chromium forks, not what a site sees, and the manifest records them. Because
``--single-process`` allows one document per launch, every page and every robots fetch gets its
own browser: launch, use, close. That is a stronger isolation than a fresh context and costs about
a second, well inside the pace.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import version
from urllib.parse import urljoin

from playwright.sync_api import Browser, Page, Request, Route, WebSocketRoute, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from browser_capture.policy import DOCUMENT, FRAME, MAIN, POPUP, SHUT_PATHS, Gate
from browser_capture.session import Answer, Engine, Hop, TransportError, Visit

ABORT = "blockedbyclient"
MAX_HOPS = 5


@dataclass
class _Walk:
    """Route handler state for one page view.

    Every document (main frame, child frame) is fetched by Playwright with redirects *not*
    followed and only a non-3xx answer is handed to the browser, so a hop is never requested
    behind the gate's back: the handler cancels the navigation, remembers the hop, and ``visit``
    decides, paces and opens the target as a new navigation. Pop-up windows are refused and
    closed; sockets are refused by ``route_web_socket``.
    """

    gate: Gate
    page: Page
    expected: str = ""  # the main-frame URL the job already decided on
    pending: tuple[str, int, str] | None = None  # (url, status, location) of a hop to follow
    failure: str | None = None
    served: Answer | None = None  # the last main-frame document handed to the browser
    hops: list[Hop] = field(default_factory=list)
    documents: list[Hop] = field(default_factory=list)

    def expect(self, url: str) -> None:
        self.expected, self.pending, self.failure = url, None, None

    def popup(self, page: Page) -> None:
        if page is not self.page:
            self.gate.count("popups_closed")
            page.close()

    def websocket(self, ws: WebSocketRoute) -> None:
        self.gate.count("refused_websocket")  # not connected: the handshake never leaves

    def scope_of(self, request: Request) -> str:
        try:
            frame = request.frame
        except PlaywrightError:
            return POPUP  # a request issued before its frame exists is a new window opening
        if frame.page is not self.page:
            return POPUP
        if frame is self.page.main_frame:
            return MAIN
        return FRAME

    def handle(self, route: Route, request: Request) -> None:
        is_doc = request.is_navigation_request() or request.resource_type == DOCUMENT
        scope = self.scope_of(request)
        decided = scope == MAIN and is_doc and request.url == self.expected
        if not decided:
            decision = self.gate.decide(
                request.url,
                request.resource_type,
                request.is_navigation_request(),
                method=request.method,
                scope=scope,
            )
            if not decision.allow:
                route.abort(ABORT)
                return
        if not is_doc:
            route.continue_()
            return
        try:
            answer = route.fetch(max_redirects=0)
        except PlaywrightError as exc:
            self.failure = repr(exc)
            route.abort("failed")
            return
        status = answer.status
        location = answer.headers.get("location", "")
        if 300 <= status < 400 and location:
            if scope == MAIN:
                self.pending = (request.url, status, urljoin(request.url, location))
                # 204 cancels the navigation without committing an error page, so the hop can
                # be opened as a fresh navigation once the job has decided and paced it
                route.fulfill(status=204)
            else:
                self.gate.count("refused_frame_redirect")
                route.abort(ABORT)
            return
        if scope == MAIN:
            self.served = Answer(status, dict(answer.headers), answer.body(), answer.url)
            self.documents.append(Hop(answer.url, status))
        route.fulfill(response=answer)


class PlaywrightSession:
    def __init__(self, launch_args: tuple[str, ...] = ()) -> None:
        self._pw = sync_playwright().start()
        self._args = launch_args
        try:
            with self._browser() as browser:
                page = browser.new_page()
                ua = str(page.evaluate("navigator.userAgent"))
                size = page.viewport_size or {"width": 0, "height": 0}
                self._engine = Engine(
                    name="chromium",
                    version=browser.version,
                    playwright=version("playwright"),
                    user_agent=ua,
                    viewport=(int(size["width"]), int(size["height"])),
                    launch_args=launch_args,
                    policy_args=SHUT_PATHS,
                )
        except Exception:
            self._pw.stop()  # a driver left running keeps an event loop in this thread
            raise

    @contextmanager
    def _browser(self) -> Iterator[Browser]:
        # headless, no other options: the policy flags shut SharedWorker and WebRTC UDP
        browser = self._pw.chromium.launch(args=[*SHUT_PATHS, *self._args])
        try:
            yield browser
        finally:
            browser.close()

    @property
    def engine(self) -> Engine:
        return self._engine

    def answer(self, url: str, *, timeout_s: float) -> Answer:
        with self._browser() as browser:
            ctx = browser.new_context()
            try:
                r = ctx.request.get(url, max_redirects=0, timeout=timeout_s * 1000)
                return Answer(r.status, dict(r.headers), r.body(), r.url)
            except PlaywrightError as exc:
                raise TransportError(repr(exc)) from exc

    def visit(  # noqa: PLR0913 - the job's knobs, all keyword-only
        self,
        url: str,
        gate: Gate,
        *,
        nav_timeout_s: float,
        idle_timeout_s: float,
        screenshot: bool,
        pace: Callable[[str], None],
    ) -> Visit:
        with self._browser() as browser:  # fresh process, cookies and storage per page
            ctx = browser.new_context(service_workers="block")  # no worker ever registers
            page = ctx.new_page()
            walk = _Walk(gate, page)
            ctx.route("**/*", walk.handle)  # the context, so pop-up windows are routed too
            ctx.route_web_socket("**/*", walk.websocket)  # never connects: a socket is refused
            ctx.on("page", walk.popup)
            t0 = time.monotonic()
            current = url
            for _ in range(MAX_HOPS + 1):
                if not gate.decide(current, DOCUMENT, True).allow:
                    why = gate.refused_document[1] if gate.refused_document else "refused"
                    raise TransportError(f"document refused: {current}: {why}")
                if current != url:
                    pace(current)
                walk.expect(current)
                try:
                    page.goto(current, wait_until="domcontentloaded", timeout=nav_timeout_s * 1000)
                except PlaywrightError as exc:
                    if walk.pending is None:
                        raise TransportError(walk.failure or repr(exc)) from exc
                    hop_url, hop_status, target = walk.pending
                    walk.hops.append(Hop(hop_url, hop_status))
                    current = target
                    continue
                break
            else:
                raise TransportError(f"more than {MAX_HOPS} redirects")
            nav_ms = int((time.monotonic() - t0) * 1000)
            t1 = time.monotonic()
            idle_timeout = False
            try:
                page.wait_for_load_state("networkidle", timeout=idle_timeout_s * 1000)
            except PlaywrightError:
                idle_timeout = True
            settle_ms = int((time.monotonic() - t1) * 1000)
            served = walk.served
            return Visit(
                status=served.status if served else None,
                final_url=page.url,
                headers=dict(served.headers) if served else {},
                server_body=served.body if served else b"",
                rendered=page.content(),
                title=page.title(),
                hops=tuple(walk.hops),
                document_url=served.url if served else "",
                documents=tuple(walk.documents),
                navigated_away=bool(served) and len(walk.documents) > 1,
                screenshot=page.screenshot() if screenshot else None,
                idle_timeout=idle_timeout,
                nav_ms=nav_ms,
                settle_ms=settle_ms,
                gate_counts=dict(gate.counts),
                hosts_seen=dict(gate.hosts_seen),
            )

    def close(self) -> None:
        self._pw.stop()
