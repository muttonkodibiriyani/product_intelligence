"""Pure helpers for the product-picture pass (task 01a0fc6d): which image URLs a PDP exposes,
where a downloaded picture is stored, and a small RFC 9309 robots matcher for the image host.

Pictures are fetched directly from the image host (never through a proxy), paced on their own,
and the host's robots.txt is obeyed fail-closed: unreadable robots.txt means no pictures.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

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
    """Rules of the group matching our product token (else ``*``); unknown status is refused."""

    def __init__(self, text: str, status: int | None, agent_name: str = "pi-snapshot") -> None:
        self.status = status
        groups: list[tuple[list[str], list[Rule]]] = []
        agents: list[str] = []
        rules: list[Rule] = []
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, _, value = (p.strip() for p in line.partition(":"))
            key = key.lower()
            if key == "user-agent":
                if in_rules:
                    groups.append((agents, rules))
                    agents, rules, in_rules = [], [], False
                agents.append(value.lower())
            elif agents and key in ("allow", "disallow"):
                in_rules = True
                if value:
                    rules.append(Rule(key == "allow", value, _compile(value)))
        if agents:
            groups.append((agents, rules))
        token = agent_name.lower()
        mine = [r for a, rs in groups if token in a for r in rs]
        star = [r for a, rs in groups if "*" in a for r in rs]
        self.rules = mine if any(token in a for a, _ in groups) else star

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
