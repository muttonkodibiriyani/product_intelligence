"""Pure extraction helpers for Sephora UAE payloads (no network)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree  # type: ignore[import-untyped]

SITE = "https://www.sephora.me"
LOCALES = ("en-AE", "ar-AE")
SITEMAPS_PER_LOCALE = 40
_PDP_RE = re.compile(r"^https://www\.sephora\.me/ae-(en|ar)/p/[^/]+/(P\d+|\d+)/?$")
_LD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
# Fields dropped from the stored extract: long marketing text, not used by the connector.
_DROP = ("longDescription", "c_ingredients", "c_tips", "c_usage", "c_testResults", "seoData")
CHALLENGE_MARKERS = (
    "/cdn-cgi/challenge-platform/",
    "Access Denied",
    "Reference&#32;&#35;",
    "captcha",
    "px-captcha",
    "_Incapsula_Resource",
)


def sitemap_urls(locale: str) -> list[str]:
    return [
        f"{SITE}/sitemap/{locale}/catalog/productSlugsCO-{i}.xml"
        for i in range(SITEMAPS_PER_LOCALE)
    ]


def parse_sitemap(xml: bytes) -> list[tuple[str, str, str]]:
    """UAE PDP URLs in one product sitemap as (lang, product_id, url)."""
    try:
        root = ElementTree.fromstring(xml)
    except ParseError as exc:
        raise ValueError(f"sitemap is not XML: {exc}") from exc
    out = []
    for loc in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
        url = (loc.text or "").strip()
        m = _PDP_RE.match(url)
        if m:
            out.append((m.group(1), m.group(2), url))
    return out


_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.DOTALL)


def _rsc_text(html: str) -> str:
    """Concatenate the decoded Next.js RSC string chunks (self.__next_f.push([1, "..."]))."""
    return "".join(json.loads(f'"{chunk}"') for chunk in _PUSH_RE.findall(html))


def extract_pdp(html: str) -> dict[str, Any]:
    """Compact extract of a PDP: productDetails (minus long text) + JSON-LD blocks."""
    text = _rsc_text(html)
    key = '"productDetails":'
    i = text.find(key)
    if i < 0:
        raise ValueError("productDetails not found")
    details, _ = json.JSONDecoder().raw_decode(text, i + len(key))
    if not isinstance(details, dict) or "id" not in details:
        raise ValueError("productDetails malformed")
    for k in _DROP:
        details.pop(k, None)
    ld = []
    for block in _LD_RE.findall(html):
        try:
            ld.append(json.loads(block))
        except json.JSONDecodeError:
            continue
    return {"productDetails": details, "jsonld": ld}


@dataclass(frozen=True)
class Verdict:
    kind: str  # challenge | blocked | rate_limited
    reason: str


def detect_block(status: int, text: str) -> Verdict | None:
    head = text[:20000]
    for m in CHALLENGE_MARKERS:
        if m in head and (status != 200 or len(text) < 60000):
            return Verdict("challenge", f"marker {m!r} (http {status})")
    if status == 429:
        return Verdict("rate_limited", "http 429")
    if status in (401, 403):
        return Verdict("blocked", f"http {status}")
    return None


def trpc_availability_url(locale: str, product_id: str) -> str:
    payload = json.dumps(
        {"0": {"json": {"locale": locale, "productId": product_id}}}, separators=(",", ":")
    )
    return f"{SITE}/api/trpc/products.getProductAvailability?batch=1&input={payload}"
