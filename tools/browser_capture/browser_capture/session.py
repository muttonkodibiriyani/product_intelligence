"""The browser as the job sees it: one plain answer for robots.txt, one Visit per page.

Everything Playwright-specific lives in ``pw``; tests use a fake that satisfies ``Session``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from browser_capture.policy import Gate


class TransportError(Exception):
    """The browser could not complete the request (DNS, reset, timeout, aborted navigation)."""


@dataclass(frozen=True)
class Answer:
    """One HTTP answer without JavaScript (robots.txt), redirects *not* followed."""

    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    @property
    def location(self) -> str:
        return self.headers.get("location", "")


@dataclass(frozen=True)
class Hop:
    url: str
    status: int | None


@dataclass(frozen=True)
class Visit:
    """One rendered page view: the server's document, the DOM after settling, and the evidence."""

    status: int | None
    final_url: str
    headers: Mapping[str, str]
    server_body: bytes
    rendered: str
    title: str
    hops: tuple[Hop, ...] = ()  # redirects before the final document, in order
    screenshot: bytes | None = None
    idle_timeout: bool = False  # the network never went quiet within the cap; captured anyway
    nav_ms: int = 0
    settle_ms: int = 0
    gate_counts: Mapping[str, int] = field(default_factory=dict)
    hosts_seen: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Engine:
    """What ran, for the manifest: recorded, never tuned."""

    name: str  # chromium
    version: str
    playwright: str
    user_agent: str
    viewport: tuple[int, int]
    headless: bool = True
    launch_args: tuple[str, ...] = ()  # process-model flags only, recorded verbatim


class Session(Protocol):
    @property
    def engine(self) -> Engine: ...

    def answer(self, url: str, *, timeout_s: float) -> Answer:
        """Plain GET through the browser's own request stack (its headers, no JS, no redirects)."""
        ...

    def visit(
        self, url: str, gate: Gate, *, nav_timeout_s: float, idle_timeout_s: float, screenshot: bool
    ) -> Visit:
        """Open ``url`` in a fresh context, every request passing through ``gate`` first."""
        ...

    def close(self) -> None: ...
