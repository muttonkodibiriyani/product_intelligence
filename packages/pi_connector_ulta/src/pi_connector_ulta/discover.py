"""Pure offline discovery from already-fetched ulta.ae sitemap and category payloads.

Real site layout (probe 2026-09-30, docs/recon/gulf_probe_results.md):

* ``/sitemap.xml`` is an index of ``product-sitemap-ae.xml``, ``category-sitemap-ae.xml`` and
  ``content-sitemap-ae.xml``.
* Product pages are ``/en/buy-<slug>`` and ``/ar/buy-<slug>`` (same slug in both locales).
* The product sitemap is the primary source. A rendered category page adds the product tiles in
  its DOM (first page only: robots disallows ``/*?``, so no ``?page=N``); see
  ``dom.parse_plp_html``. The page-loaded listing JSON (``catalog.parse_plp_payload``) comes
  from ``/graphql``, which robots disallows, so it is an optional path, off unless enabled.

A pinned WebKit engine shows XML as its XML-viewer HTML, so sitemap parsing accepts both raw
XML and that view. Every URL is checked against the host's robots.txt rules, which the caller
must supply (no rules, no URLs: fail closed).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from defusedxml import ElementTree  # type: ignore[import-untyped]

from pi_connector_ulta.catalog import CatalogError, PlpHit, parse_plp_payload
from pi_connector_ulta.dom import parse_plp_html
from pi_fetch.pacing import RobotsRules

__all__ = [
    "DiscoveryError",
    "ListingKey",
    "child_sitemaps",
    "discover_category",
    "discover_category_json",
    "discover_sitemap",
    "locale_url",
    "sitemap_locs",
]

BASE = "https://www.ulta.ae"
_PRODUCT_PATH = re.compile(r"^/(en|ar)/buy-[^/?#]+/?$")
_VIEWER_LOC = re.compile(r"<loc>\s*(\S+?)\s*</loc>")
_TAG = re.compile(r"<[^>]+>")


class DiscoveryError(ValueError):
    """Raised when a discovery document is malformed."""


@dataclass(frozen=True, slots=True)
class ListingKey:
    """Stable input key for later fetching by the shared fetch layer."""

    product_url: str
    source_product_id: str | None = None


def _is_viewer(document: str) -> bool:
    head = document.lstrip()[:512].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def sitemap_locs(document: str) -> tuple[str, ...]:
    """Every ``<loc>`` in a sitemap or sitemap index, raw XML or the WebKit XML-viewer page."""
    if _is_viewer(document):
        text = html.unescape(_TAG.sub(" ", document))
        if "sitemap" not in text.lower() and "urlset" not in text.lower():
            raise DiscoveryError("page is not an XML sitemap view")
        return tuple(dict.fromkeys(_VIEWER_LOC.findall(text)))
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        raise DiscoveryError("invalid sitemap XML") from exc
    locs = [
        node.text.strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text and node.text.strip()
    ]
    return tuple(dict.fromkeys(locs))


def _on_host(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in {"ulta.ae", "www.ulta.ae"}


def child_sitemaps(document: str, robots: RobotsRules) -> tuple[str, ...]:
    """Robots-allowed child sitemaps of a sitemap index, product sitemaps first."""
    found = [
        u for u in sitemap_locs(document) if _on_host(u) and u.endswith(".xml") and robots.allows(u)
    ]
    return tuple(sorted(found, key=lambda u: ("product" not in u, u)))


def _product_url(url: str, robots: RobotsRules) -> str | None:
    if not _on_host(url):
        return None
    parts = urlsplit(url)
    if parts.query or parts.fragment or not _PRODUCT_PATH.match(parts.path):
        return None
    clean = f"{BASE}{parts.path.rstrip('/')}"
    return clean if robots.allows(clean) else None


def locale_url(url: str, locale: str) -> str:
    """The same product page in the given storefront locale (``en`` or ``ar``)."""
    parts = urlsplit(url)
    if not _on_host(url) or not _PRODUCT_PATH.match(parts.path) or locale not in {"en", "ar"}:
        raise DiscoveryError(f"not a product URL or locale: {url} {locale}")
    return f"{BASE}/{locale}{parts.path[3:].rstrip('/')}"


def discover_sitemap(document: str, robots: RobotsRules) -> tuple[ListingKey, ...]:
    """Deduplicated, robots-allowed product URLs from one product sitemap."""
    urls = {u for loc in sitemap_locs(document) if (u := _product_url(loc, robots))}
    return tuple(ListingKey(url) for url in sorted(urls))


def _keys(hits: list[PlpHit], robots: RobotsRules) -> tuple[ListingKey, ...]:
    found: dict[str, ListingKey] = {}
    for hit in hits:
        url = _product_url(urljoin(BASE, hit.url_path), robots)
        if url is not None:
            found[url] = ListingKey(url, hit.sku)
    return tuple(found[url] for url in sorted(found))


def discover_category(document: str, locale: str, robots: RobotsRules) -> tuple[ListingKey, ...]:
    """Product keys from the tiles rendered on a category page (first page only)."""
    return _keys(parse_plp_html(document, locale), robots)


def discover_category_json(
    document: str, locale: str, robots: RobotsRules
) -> tuple[ListingKey, ...]:
    """Optional path: keys from the page-loaded listing JSON (``/graphql``, off by default)."""
    try:
        hits = parse_plp_payload(document, locale)
    except CatalogError as exc:
        raise DiscoveryError("invalid category listing payload") from exc
    return _keys(hits, robots)
