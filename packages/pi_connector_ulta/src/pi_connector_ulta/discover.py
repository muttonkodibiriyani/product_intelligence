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
from html.parser import HTMLParser
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
    "strict_sitemap_locs",
]

BASE = "https://www.ulta.ae"
_PRODUCT_PATH = re.compile(r"^/(en|ar)/buy-[^/?#]+/?$")
_VIEWER_LOC = re.compile(r"<loc>\s*(\S+?)\s*</loc>")
_TAG = re.compile(r"<[^>]+>")
_VIEWER_HEADER = (
    "This XML file does not appear to have any style information associated with it. "
    "The document tree is shown below."
)


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
    root_name = root.tag.rsplit("}", 1)[-1]
    if root_name not in {"sitemapindex", "urlset"}:
        raise DiscoveryError(f"invalid sitemap root: {root_name}")
    locs = [
        node.text.strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text and node.text.strip()
    ]
    return tuple(dict.fromkeys(locs))


@dataclass(slots=True)
class _ViewerFrame:
    tag: str
    enters_tree: bool
    enters_hidden: bool
    capture_kind: str | None


class _WebKitXmlViewerParser(HTMLParser):
    """Reconstruct the visible XML tree from WebKit's built-in XML viewer."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.frames: list[_ViewerFrame] = []
        self.tokens: list[tuple[str, str]] = []
        self.capture: list[str] | None = None
        self.capture_kind: str | None = None
        self.tree_depth = 0
        self.hidden_depth = 0
        self.has_style = False
        self.has_tree = False
        self.invalid = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        enters_tree = tag == "div" and values.get("id") == "tree" and "pretty-print" in classes
        if tag == "style" and values.get("id") == "xml-viewer-style":
            self.has_style = True
        if enters_tree:
            self.has_tree = True
            self.tree_depth += 1
        in_tree = self.tree_depth > 0
        enters_hidden = in_tree and "hidden" in classes
        if enters_hidden:
            self.hidden_depth += 1
        capture_kind = None
        if in_tree and self.hidden_depth == 0 and tag == "span":
            kinds = classes.intersection({"tag", "text"})
            if len(kinds) == 1:
                if self.capture is not None:
                    self.invalid = True
                else:
                    capture_kind = kinds.pop()
                    self.capture_kind = capture_kind
                    self.capture = []
        self.frames.append(_ViewerFrame(tag, enters_tree, enters_hidden, capture_kind))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag, attrs

    def handle_endtag(self, tag: str) -> None:
        if not self.frames or self.frames[-1].tag != tag:
            self.invalid = True
            return
        frame = self.frames.pop()
        if frame.capture_kind is not None:
            if self.capture is None or self.capture_kind != frame.capture_kind:
                self.invalid = True
            else:
                self.tokens.append((frame.capture_kind, "".join(self.capture)))
            self.capture = None
            self.capture_kind = None
        if frame.enters_hidden:
            self.hidden_depth -= 1
        if frame.enters_tree:
            self.tree_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capture is not None:
            self.capture.append(data)


def _raw_sitemap_locs(document: str) -> tuple[str, ...]:
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        raise DiscoveryError("invalid sitemap XML") from exc
    root_name = root.tag.rsplit("}", 1)[-1]
    if root_name not in {"sitemapindex", "urlset"}:
        raise DiscoveryError(f"invalid sitemap root: {root_name}")
    return tuple(
        node.text if node.text is not None else ""
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "loc"
    )


def strict_sitemap_locs(document: str) -> tuple[str, ...]:
    """Return every raw ``<loc>`` value without trimming or dropping invalid entries.

    HTML is accepted only when it has WebKit XML viewer's structural markers. Its visible tree is
    reconstructed and parsed as XML; arbitrary HTML containing encoded ``<loc>`` text is refused.
    """
    if not _is_viewer(document):
        return _raw_sitemap_locs(document)
    parser = _WebKitXmlViewerParser()
    try:
        parser.feed(document)
        parser.close()
    except (AssertionError, ValueError) as exc:
        raise DiscoveryError("invalid WebKit XML viewer page") from exc
    if (
        parser.invalid
        or parser.frames
        or not parser.has_style
        or not parser.has_tree
        or _VIEWER_HEADER not in document
    ):
        raise DiscoveryError("page is not a WebKit XML sitemap view")
    reconstructed = "".join(
        value if kind == "tag" else html.escape(value, quote=False) for kind, value in parser.tokens
    )
    return _raw_sitemap_locs(reconstructed)


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
