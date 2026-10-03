"""What the real browser may ask for, decided before each request leaves (ADR-0006 rung 2).

Documents (the main-frame navigation, every redirect hop it takes, every JavaScript navigation
and any child frame) must be ``https`` on the shop's own storefront host set, exactly as the page
jobs gate their hops (sephora_snapshot, #167), and must pass the job's ``document_check`` (the
host's robots.txt, fail closed). Pop-up windows are refused outright: a page view is one
document. Pictures, media, fonts, beacons, sockets and workers are never requested here:
pictures are collected separately and direct. Scripts, styles and data calls are what makes a
client-side shop render at all. Under the ``record`` policy GET calls may go to any ``https``
host and every host is counted, so the first slice reports the exact set a later run then
enforces with an explicit host list, fail closed: anything else is aborted and counted, never
guessed. Writes (anything but GET/HEAD) never leave the storefront under either policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit

RECORD: Final = "record"
ENFORCE_HOSTS: Final = "enforce"
DOCUMENT: Final = "document"
MAIN: Final = "main"  # the page's own frame
FRAME: Final = "frame"  # a child frame of the page
POPUP: Final = "popup"  # a window the page opened: always refused
HTTPS_ONLY: Final = frozenset({"https"})
READ_METHODS: Final = frozenset({"GET", "HEAD"})
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

# Browser flags that shut the two request paths no route handler ever sees. A SharedWorker's
# fetches bypass context routing, so the feature is off; WebRTC ICE would send UDP (STUN) to a
# host the page chooses, so non-proxied UDP is off. These are policy, not process-model flags,
# and are recorded in the manifest as such.
SHUT_PATHS: Final = (
    "--disable-features=SharedWorker",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
)

# Run in every frame before any page script: WebRTC is removed outright. The UDP flag above only
# moves ICE onto TCP, and a TURN allocation over TCP still goes to a host the page chooses,
# unseen by any route handler. With no constructor there is no connection on any transport.
NO_WEBRTC: Final = (
    "delete window.RTCPeerConnection; "
    "delete window.webkitRTCPeerConnection; "
    "delete window.RTCDataChannel;"
)
_WEBRTC_CONSTRUCTORS: Final = ("RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel")


def webrtc_state(init_script: str) -> str:
    """What the manifest says about WebRTC, derived from the init script actually installed.

    Only a script that deletes all three constructors earns the "removed" statement; anything
    else is recorded as left in place, naming the constructors the script does not delete.
    """
    kept = [c for c in _WEBRTC_CONSTRUCTORS if f"delete window.{c};" not in init_script]
    if not kept:
        return "removed from every frame by the init script"
    return "left in place: init script does not delete " + ", ".join(kept)


def host_refusal(
    url: str, allowed: frozenset[str], *, schemes: frozenset[str] = HTTPS_ONLY
) -> str | None:
    """Why ``url`` is not a plain address on one of ``allowed``; None when it is.

    ``schemes`` is https only in the job; the real-browser test passes http for localhost.
    """
    parts = urlsplit(url)
    if parts.scheme not in schemes:
        return f"scheme {parts.scheme or 'none'!r} is not {' or '.join(sorted(schemes))}"
    if "@" in parts.netloc:
        return "userinfo in host"
    if parts.port is not None and schemes == HTTPS_ONLY:
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
    """Per-visit request policy with its own counters; one Gate per page visit.

    ``document_check`` is the job's say on a document target that passed the host rules (its
    robots.txt verdict, a stopped host); it returns the refusal reason or None.
    """

    hosts: frozenset[str]
    subresources: str = RECORD  # RECORD or ENFORCE_HOSTS
    subresource_hosts: frozenset[str] = frozenset()
    document_check: Callable[[str], str | None] | None = None
    schemes: frozenset[str] = HTTPS_ONLY
    counts: dict[str, int] = field(default_factory=dict)
    hosts_seen: dict[str, int] = field(default_factory=dict)
    refused_document: tuple[str, str] | None = None  # (url, why) for the first refused document

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def decide(
        self,
        url: str,
        resource_type: str,
        is_navigation: bool,
        *,
        method: str = "GET",
        scope: str = MAIN,
    ) -> Decision:
        if scope == POPUP:
            self.count("refused_popup")
            return Decision(False, "popup")
        if is_navigation or resource_type == DOCUMENT:
            return self._document(url, scope)
        if resource_type in NEVER_TYPES or resource_type not in RENDER_TYPES:
            self.count(f"refused_type_{resource_type}")
            return Decision(False, f"never:{resource_type}")
        return self._render(url, resource_type, method)

    def _document(self, url: str, scope: str) -> Decision:
        why = host_refusal(url, self.hosts, schemes=self.schemes)
        if why is None and self.document_check is not None:
            why = self.document_check(url)
        if why is not None:
            self.count(f"refused_{scope}_document" if scope != MAIN else "refused_document")
            if self.refused_document is None:
                self.refused_document = (url, why)
            return Decision(False, f"document: {why}")
        self.count("documents" if scope == MAIN else "frame_documents")
        return Decision(True, DOCUMENT)

    def _render(self, url: str, resource_type: str, method: str) -> Decision:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in self.schemes or not host:
            self.count("refused_http")
            return Decision(False, "http")
        self.hosts_seen[host] = self.hosts_seen.get(host, 0) + 1
        own = host in self.hosts
        if not own and method.upper() not in READ_METHODS:
            self.count("refused_third_party_write")
            return Decision(False, f"write:{host}")
        if not own and self.subresources != RECORD and host not in self.subresource_hosts:
            self.count("refused_third_party")
            return Decision(False, f"host:{host}")
        self.count(f"render_{resource_type}")
        if not own:
            self.count("third_party")
        return Decision(True, f"render:{resource_type}")
