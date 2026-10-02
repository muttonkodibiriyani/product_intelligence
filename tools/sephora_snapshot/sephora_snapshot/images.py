"""Pure helpers for the product-picture pass (task 01a0fc6d): which image URLs a PDP exposes,
where a downloaded picture is stored, and a small RFC 9309 robots matcher for the image host.

Pictures are fetched directly from the image host (never through a proxy), paced on their own,
and the host's robots.txt is obeyed fail-closed: unreadable robots.txt means no pictures.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

DEFAULT_IMAGE_HOSTS = frozenset({"img-product.sephora.me"})

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
    "image/svg+xml": "svg",
}


def _walk(node: Any, keys: tuple[str, ...]) -> Iterator[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in keys and isinstance(v, str) and v.startswith("http"):
                yield v
            else:
                yield from _walk(v, keys)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, keys)


def image_urls(details: dict[str, Any]) -> list[str]:
    """Every distinct picture URL a productDetails block exposes, in page order: the product's
    own ``images[]`` and each variant's ``images[]`` (``disBaseLink`` = the image CDN; the
    origin ``link`` is skipped when a CDN link is present) plus variant swatches."""
    out: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)

    for image in details.get("images") or []:
        if isinstance(image, dict):
            add(image.get("disBaseLink") or image.get("link") or "")
    for variant in details.get("c_variantsInfo") or []:
        if not isinstance(variant, dict):
            continue
        for image in variant.get("images") or []:
            if isinstance(image, dict):
                add(image.get("disBaseLink") or image.get("link") or "")
        swatch = variant.get("swatchImage")
        if isinstance(swatch, str) and swatch.startswith("http"):
            add(swatch)
    # anything else that looks like a picture link (sets, routine products)
    for url in _walk(details.get("setProducts"), ("disBaseLink",)):
        add(url)
    return out


def host_refusal(url: str, allowed: Iterable[str]) -> str | None:  # noqa: PLR0911 - one per reason
    """Why a picture URL must not be fetched, or ``None`` when it may.

    Scraped content never chooses our request targets: only ``https``, only an exact hostname in
    ``allowed`` (lower-cased; no suffix match), no userinfo, no port, no empty host.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "unparseable url"
    if parts.scheme != "https":
        return f"scheme {parts.scheme or 'none'!r} is not https"
    if "@" in parts.netloc:
        return "userinfo in host"
    if parts.port is not None or parts.netloc.rsplit("]", 1)[-1].count(":"):
        return "explicit port"
    host = (parts.hostname or "").lower()
    if not host:
        return "empty host"
    if host not in {h.lower() for h in allowed}:
        return f"host {host!r} is not an allowed image host"
    return None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_name(digest: str, content_type: str) -> str:
    ext = EXTENSIONS.get(content_type.split(";", maxsplit=1)[0].strip().lower(), "bin")
    return f"images/{digest}.{ext}"


# ------------------------------------------------------------------ robots (RFC 9309 subset)
@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @property
    def specificity(self) -> int:
        return len(self.pattern.replace("*", "").rstrip("$"))


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "^" + re.escape(unquote(body)).replace(r"\*", ".*") + ("$" if anchored else "")
    return re.compile(regex)


class Robots:
    """Rules of the group matching our product token (else ``*``); unknown status is refused.

    ``crawl_delay`` is the group's ``Crawl-delay`` in seconds when it states one (RFC 9309 leaves
    it to the operator; we honour it as a pacing floor).
    """

    def __init__(self, text: str, status: int | None, agent_name: str = "pi-snapshot") -> None:
        self.status = status
        groups: list[tuple[list[str], list[Rule], float | None]] = []
        agents: list[str] = []
        rules: list[Rule] = []
        delay: float | None = None
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, _, value = (p.strip() for p in line.partition(":"))
            key = key.lower()
            if key == "user-agent":
                if in_rules:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = [], [], None, False
                agents.append(value.lower())
            elif agents and key in ("allow", "disallow"):
                in_rules = True
                if value:
                    rules.append(Rule(key == "allow", value, _compile(value)))
            elif agents and key == "crawl-delay":
                in_rules = True
                with contextlib.suppress(ValueError):
                    delay = float(value) if 0 < float(value) <= 3600 else delay
        if agents:
            groups.append((agents, rules, delay))
        token = agent_name.lower()
        mine = [g for g in groups if token in g[0]]
        star = [g for g in groups if "*" in g[0]]
        chosen = mine or star
        self.rules = [r for _, rs, _ in chosen for r in rs]
        delays = [d for _, _, d in chosen if d is not None]
        self.crawl_delay: float | None = max(delays) if delays else None

    def allows(self, url: str) -> bool:
        if self.status in (404, 410):
            return True
        if self.status != 200:
            return False
        parts = urlsplit(url)
        target = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        matched = [r for r in self.rules if r.regex.search(target)]
        if not matched:
            return True
        best = max(matched, key=lambda r: (r.specificity, r.allow))
        return best.allow


def hosts(urls: Iterable[str]) -> set[str]:
    return {urlsplit(u).netloc for u in urls}
