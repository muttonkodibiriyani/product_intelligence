"""Pure helpers: block detection, redaction and field presence. No I/O, no third-party imports."""

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_SENSITIVE_HEADERS: Final = frozenset(
    {"set-cookie", "cookie", "authorization", "x-api-key", "x-algolia-api-key"}
)
_BLOCK_STATUSES: Final = frozenset({401, 403, 429, 503})
_KEY_PATTERNS: Final = (
    # Algolia and similar search keys embedded in page config: keep the name, drop the value.
    re.compile(r'("(?:api[_-]?key|apiKey|search[_-]?key|algolia[A-Za-z_]*Key)"\s*:\s*")([^"]+)(")'),
    re.compile(r"((?:x-algolia-api-key|apiKey)=)([A-Za-z0-9]+)()"),
    re.compile(r'("(?:passkey|passKey)"\s*:\s*")([^"]+)(")'),
)
_CHALLENGE_MARKERS: Final = (
    "<title>just a moment...</title>",
    "<title>attention required! | cloudflare</title>",
    "<title>access denied</title>",
    "cf-challenge",
    "/cdn-cgi/challenge-platform/",  # Cloudflare managed challenge (any language, any status)
    "px-captcha",
    "captcha-delivery.com",
)
_JSON_LD: Final = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)
_STATE_MARKERS: Final = {
    "next_data": "__NEXT_DATA__",
    "nuxt": "__NUXT__",
    "initial_state": "__INITIAL_STATE__",
    "preloaded_state": "__PRELOADED_STATE__",
    "drupal_settings": "drupalSettings",
    "algolia": "algolia",
    "bazaarvoice": "bazaarvoice",
}


class BlockVendor(StrEnum):
    """Who served the block, from response signatures."""

    AKAMAI = "akamai"
    CLOUDFLARE = "cloudflare"
    PERIMETERX = "perimeterx"
    DATADOME = "datadome"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class BlockVerdict:
    """A response judged to be a block rather than content."""

    vendor: BlockVendor
    reason: str


def _lower(headers: Mapping[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def detect_vendor(headers: Mapping[str, str], body: str) -> BlockVendor | None:
    """Return the bot-protection vendor fronting the response, if recognisable."""
    h = _lower(headers)
    server = h.get("server", "").lower()
    if "akamaighost" in server or "errors.edgesuite.net" in body:
        return BlockVendor.AKAMAI
    if "cloudflare" in server or "cf-ray" in h:
        return BlockVendor.CLOUDFLARE
    if "_pxhd" in h.get("set-cookie", "") or "px-captcha" in body:
        return BlockVendor.PERIMETERX
    if "datadome" in server or "x-datadome" in h:
        return BlockVendor.DATADOME
    return None


def detect_block(
    status: int, headers: Mapping[str, str], body: str, *, size: int | None = None
) -> BlockVerdict | None:
    """Classify a response as blocked (vendor + reason) or ``None`` when it looks like content.

    ``size`` is the raw byte length for binary payloads (images), whose ``body`` is not decoded.
    """
    vendor = detect_vendor(headers, body)
    lowered = body[:20_000].lower()
    if status in _BLOCK_STATUSES:
        return BlockVerdict(vendor or BlockVendor.GENERIC, f"http {status}")
    for marker in _CHALLENGE_MARKERS:
        if marker in lowered:
            return BlockVerdict(vendor or BlockVendor.GENERIC, f"challenge marker: {marker}")
    empty = size == 0 if size is not None else not body.strip()
    if 200 <= status < 300 and empty:
        return BlockVerdict(vendor or BlockVendor.GENERIC, "empty 200 body")
    return None


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Drop cookies and credentials; everything else is kept for evidence."""
    return {k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS}


def redact_text(text: str) -> str:
    """Replace embedded API keys / passkeys with ``REDACTED`` so fixtures are safe to commit."""
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(r"\1REDACTED\3", text)
    return text


def json_ld_blocks(html: str) -> list[object]:
    """Parse every JSON-LD script block; unparsable blocks are skipped."""
    out: list[object] = []
    for raw in _JSON_LD.findall(html):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _walk(node: object) -> Iterator[dict[str, object]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _is_product(node: dict[str, object]) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return "Product" in kinds or "ProductGroup" in kinds


def product_fields(html: str) -> dict[str, bool]:
    """Which product fields a page exposes via JSON-LD, plus embedded-state markers."""
    products = [n for block in json_ld_blocks(html) for n in _walk(block) if _is_product(n)]
    offers = [
        n for p in products for n in _walk(p.get("offers", {})) if "price" in n or "lowPrice" in n
    ]

    def has(key: str) -> bool:
        return any(p.get(key) not in (None, "", []) for p in products)

    fields = {
        "jsonld_product": bool(products),
        "name": has("name"),
        "brand": has("brand"),
        "sku": has("sku") or has("productID"),
        "gtin": any(has(k) for k in ("gtin", "gtin13", "gtin12", "gtin8", "gtin14")),
        "image": has("image"),
        "description": has("description"),
        "price": bool(offers),
        "currency": any("priceCurrency" in o for o in offers),
        "availability": any("availability" in o for o in offers),
        "rating": has("aggregateRating"),
        "variants": has("hasVariant") or len(offers) > 1,
    }
    for name, marker in _STATE_MARKERS.items():
        fields[f"marker_{name}"] = marker in html
    return fields


def json_fields(payload: object) -> dict[str, bool]:
    """Coarse field presence for a JSON payload (BFF/XHR): which well-known keys occur anywhere."""
    keys = {k.lower() for node in _walk(payload) for k in node}
    wanted = {
        "price": ("price", "saleprice", "listprice", "final_price"),
        "original_price": (
            "originalprice",
            "listprice",
            "regularprice",
            "original_price",
            "standardprice",
        ),
        "stock": ("instock", "availability", "stock", "orderable", "ats", "stock_status"),
        "variants": ("variants", "variationattributes", "variationvalues", "children"),
        "images": ("images", "image", "imageurl", "media"),
        "rating": ("rating", "averagerating", "reviewcount"),
        "brand": ("brand", "brandname", "manufacturer"),
    }
    return {name: any(c in keys for c in cands) for name, cands in wanted.items()}


def sitemap_locs(xml: str) -> list[str]:
    """``<loc>`` values in document order (works for index and urlset files)."""
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


def sitemap_stats(xml: str) -> dict[str, int]:
    """Counts for SRC-03 reconciliation: url entries, locs, image children, hreflang alternates."""
    return {
        "url_elements": len(re.findall(r"<url>", xml)),
        "locs": len(sitemap_locs(xml)),
        "image_children": len(re.findall(r"<image:image>", xml)),
        "hreflang_links": len(re.findall(r"<xhtml:link", xml)),
    }


def trim_for_fixture(html: str, limit: int = 60_000) -> str:
    """Small, committable extract: JSON-LD blocks + title, redacted; never the full page."""
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    parts = [f"<title>{title.group(1).strip()}</title>" if title else "<title></title>"]
    parts += [f'<script type="application/ld+json">{m}</script>' for m in _JSON_LD.findall(html)]
    return redact_text("\n".join(parts))[:limit]


ROBOTS_ALLOW_ALL_STATUSES = frozenset({404, 410})


def robots_gate(
    site: str,
    path_and_query: str,
    rules: list[tuple[bool, str]] | None,
    robots_status: int | None,
) -> str | None:
    """Decide whether a probe URL may be requested. Returns a skip reason, or None to proceed.

    Fails CLOSED (PR #15 review): for any host other than Sephora (tag_only, ADR-0005), a URL is
    requested only if robots.txt was parsed and allows it, or robots.txt answered 404/410
    (allow-all). Any other robots outcome (not fetched yet, 401/403/429/5xx, challenge,
    transport error) refuses everything except ``/robots.txt`` itself.
    """
    if site == "sephora" or path_and_query == "/robots.txt":
        return None
    if rules is not None:
        return None if robots_allowed(rules, path_and_query) else "robots_disallowed"
    if robots_status in ROBOTS_ALLOW_ALL_STATUSES:
        return None
    return "robots_unavailable"


def robots_rules(robots_txt: str, agent: str = "*") -> list[tuple[bool, str]]:
    """(allow, pattern) rules of the group for ``agent`` (falls back to ``*``).

    Frozen with this one-off probe: no BOM strip or percent normalisation. Do not reuse;
    production code uses ``pi_fetch.pacing.RobotsRules`` (RFC 9309, #16).
    """
    groups: dict[str, list[tuple[bool, str]]] = {}
    current: list[str] = []
    in_rules = False
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                current, in_rules = [], False
            current.append(value.lower())
            for name in current:
                groups.setdefault(name, [])
        elif key in ("allow", "disallow") and current:
            in_rules = True
            if value:
                for name in current:
                    groups[name].append((key == "allow", value))
    return groups.get(agent.lower(), groups.get("*", []))


def _robots_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def robots_allowed(rules: list[tuple[bool, str]], path_and_query: str) -> bool:
    """RFC 9309 matching: longest matching pattern wins; ties go to Allow; no match = allowed."""
    best: tuple[int, bool] | None = None
    for allow, pattern in rules:
        if _robots_regex(pattern).match(path_and_query):
            candidate = (len(pattern), allow)
            if best is None or candidate > best:
                best = candidate
    return True if best is None else best[1]
