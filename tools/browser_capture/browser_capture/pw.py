"""Playwright adapter: stock Chromium, default context options, nothing tuned for the site.

This is the only module that imports Playwright. It is exercised by the job itself, not by the
unit tests (no browser in CI), so it stays thin: translate, never decide. Decisions are the
``Gate``'s (policy) and the job's (run).

Process-model flags (``--no-sandbox``, ``--single-process`` ...) come from ``CHROMIUM_ARGS`` so
the same image runs under Docker on a host without user namespaces or under gVisor; they change
how Chromium forks, not what a site sees, and the manifest records them. Because
``--single-process`` allows one document per launch, every page and every robots fetch gets its
own browser: launch, use, close. That is a stronger isolation than a fresh context and costs about
a second, well inside the pace.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from typing import Any

from playwright.sync_api import Browser, Request, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from browser_capture.policy import Gate
from browser_capture.session import Answer, Engine, Hop, TransportError, Visit

ABORT = "blockedbyclient"


class PlaywrightSession:
    def __init__(self, launch_args: tuple[str, ...] = ()) -> None:
        self._pw = sync_playwright().start()
        self._args = launch_args
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
            )

    @contextmanager
    def _browser(self) -> Iterator[Browser]:
        browser = self._pw.chromium.launch(args=list(self._args))  # headless, no other options
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

    def visit(
        self, url: str, gate: Gate, *, nav_timeout_s: float, idle_timeout_s: float, screenshot: bool
    ) -> Visit:
        with self._browser() as browser:  # fresh process, cookies and storage per page
            ctx = browser.new_context()
            page = ctx.new_page()

            def handler(route: Route, request: Request) -> None:
                decision = gate.decide(
                    request.url, request.resource_type, request.is_navigation_request()
                )
                if decision.allow:
                    route.continue_()
                else:
                    route.abort(ABORT)

            page.route("**/*", handler)
            t0 = time.monotonic()
            try:
                response = page.goto(
                    url, wait_until="domcontentloaded", timeout=nav_timeout_s * 1000
                )
            except PlaywrightError as exc:
                raise TransportError(repr(exc)) from exc
            nav_ms = int((time.monotonic() - t0) * 1000)
            t1 = time.monotonic()
            idle_timeout = False
            try:
                page.wait_for_load_state("networkidle", timeout=idle_timeout_s * 1000)
            except PlaywrightError:
                idle_timeout = True
            settle_ms = int((time.monotonic() - t1) * 1000)
            hops: list[Hop] = []
            server_body = b""
            status: int | None = None
            headers: dict[str, str] = {}
            if response is not None:
                status = response.status
                headers = dict(response.headers)
                try:
                    server_body = response.body()
                except PlaywrightError:
                    server_body = b""
                prev: Any = response.request.redirected_from
                while prev is not None:
                    resp = prev.response()
                    hops.append(Hop(prev.url, resp.status if resp is not None else None))
                    prev = prev.redirected_from
                hops.reverse()
            return Visit(
                status=status,
                final_url=page.url,
                headers=headers,
                server_body=server_body,
                rendered=page.content(),
                title=page.title(),
                hops=tuple(hops),
                screenshot=page.screenshot() if screenshot else None,
                idle_timeout=idle_timeout,
                nav_ms=nav_ms,
                settle_ms=settle_ms,
                gate_counts=dict(gate.counts),
                hosts_seen=dict(gate.hosts_seen),
            )

    def close(self) -> None:
        self._pw.stop()
