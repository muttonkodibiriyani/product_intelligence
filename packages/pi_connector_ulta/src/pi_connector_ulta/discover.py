"""Pure offline discovery from already-fetched sitemap and category payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse

from defusedxml import ElementTree  # type: ignore[import-untyped]


class DiscoveryError(ValueError):
    """Raised when a discovery document is malformed."""


@dataclass(frozen=True, slots=True)
class ListingKey:
    """Stable input key for later fetching by the shared fetch layer."""

    product_url: str
    source_product_id: str | None = None


def _is_ulta_product_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"ulta.ae", "www.ulta.ae"}
        and bool(parsed.path)
    )


def discover_sitemap(document: str) -> tuple[ListingKey, ...]:
    """Extract deduplicated product URLs from a sitemap document."""
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        raise DiscoveryError("invalid sitemap XML") from exc
    urls: set[str] = set()
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "loc" or node.text is None:
            continue
        url = node.text.strip()
        if _is_ulta_product_url(url) and "/product/" in urlparse(url).path:
            urls.add(url)
    return tuple(ListingKey(url) for url in sorted(urls))


def discover_category(document: str) -> tuple[ListingKey, ...]:
    """Extract product keys from an already-fetched category JSON payload."""
    try:
        payload = json.loads(document)
        items = payload["items"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DiscoveryError("invalid category JSON") from exc
    if not isinstance(items, list):
        raise DiscoveryError("category items must be a list")
    found: dict[str, ListingKey] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        product_id = item.get("id")
        if isinstance(url, str) and _is_ulta_product_url(url) and "/product/" in urlparse(url).path:
            found[url] = ListingKey(url, str(product_id) if product_id is not None else None)
    return tuple(found[url] for url in sorted(found))
