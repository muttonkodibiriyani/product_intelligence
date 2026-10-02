"""What the real browser may ask for, decided before each request leaves (ADR-0006 rung 2).

Documents (the main-frame navigation and every redirect hop it takes, and any child frame) must
be ``https`` on the shop's own storefront host set, exactly as the page jobs gate their hops
(sephora_snapshot, #167). Pictures, media, fonts, beacons and sockets are never requested here:
pictures are collected separately and direct. Scripts, styles and data calls are what makes a
client-side shop render at all. Under the ``record`` policy they may go to any ``https`` host
and every host is counted, so the first slice reports the exact set a later run then enforces
with an explicit host list, fail closed: anything else is aborted and counted, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit

RECORD: Final = "record"
ENFORCE_HOSTS: Final = "enforce"
DOCUMENT: Final = "document"
#: Chromium resource types the browser is never allowed to request from this job.
NEVER_TYPES: Final = frozenset(
    {
        "image",
        "media",
        "font",
        "ping",
        "beacon",
        "websocket",
        "manifest",
        "texttrack",
        "eventsource",
    }
)
#: Resource types a client-side shop needs to render; everything else not listed is refused.
RENDER_TYPES: Final = frozenset({"script", "stylesheet", "xhr", "fetch"})


def host_refusal(url: str, allowed: frozenset[str]) -> str | None:
    """Why ``url`` is not a plain https address on one of ``allowed``; None when it is."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        return f"scheme {parts.scheme or 'none'!r} is not https"
    if "@" in parts.netloc:
        return "userinfo in host"
    if parts.port is not None:
        return f"explicit port {parts.port}"
    if parts.hostname is None or parts.hostname.lower() not in allowed:
        return f"host {parts.netloc.lower()!r} is not in the allowed set"
    return None


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str  # e.g. "document", "render:script", "never:image", "host:cdn.example", "http"


@dataclass
class Gate:
    """Per-visit request policy with its own counters; one Gate per page visit."""

    hosts: frozenset[str]
    subresources: str = RECORD  # RECORD or ENFORCE_HOSTS
    subresource_hosts: frozenset[str] = frozenset()
    counts: dict[str, int] = field(default_factory=dict)
    hosts_seen: dict[str, int] = field(default_factory=dict)
    refused_document: tuple[str, str] | None = None  # (url, why) for the first refused document

    def _count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def decide(self, url: str, resource_type: str, is_navigation: bool) -> Decision:
        if is_navigation or resource_type == DOCUMENT:
            return self._document(url)
        if resource_type in NEVER_TYPES or resource_type not in RENDER_TYPES:
            self._count(f"refused_type_{resource_type}")
            return Decision(False, f"never:{resource_type}")
        return self._render(url, resource_type)

    def _document(self, url: str) -> Decision:
        why = host_refusal(url, self.hosts)
        if why is not None:
            self._count("refused_document")
            if self.refused_document is None:
                self.refused_document = (url, why)
            return Decision(False, f"document: {why}")
        self._count("documents")
        return Decision(True, DOCUMENT)

    def _render(self, url: str, resource_type: str) -> Decision:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            self._count("refused_http")
            return Decision(False, "http")
        self.hosts_seen[host] = self.hosts_seen.get(host, 0) + 1
        own = host in self.hosts
        if not own and self.subresources != RECORD and host not in self.subresource_hosts:
            self._count("refused_third_party")
            return Decision(False, f"host:{host}")
        self._count(f"render_{resource_type}")
        if not own:
            self._count("third_party")
        return Decision(True, f"render:{resource_type}")
