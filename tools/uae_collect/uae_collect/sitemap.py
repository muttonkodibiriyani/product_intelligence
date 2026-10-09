"""Sitemap documents: an index of child sitemaps, or a urlset of pages with optional lastmod."""

from __future__ import annotations

from dataclasses import dataclass

from defusedxml import ElementTree  # type: ignore[import-untyped]

#: child sitemaps followed from one index; a shop that lists more is refused, not truncated
MAX_CHILDREN = 50


@dataclass(frozen=True)
class Sitemap:
    #: child sitemap URLs (a sitemap index)
    children: tuple[str, ...]
    #: page URL -> lastmod as written (None when absent), in document order
    urls: dict[str, str | None]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el: object, name: str) -> str | None:
    for child in el:  # type: ignore[attr-defined]
        if _local(child.tag) == name and (child.text or "").strip():
            return str(child.text).strip()
    return None


def parse(text: str) -> Sitemap:
    """A ``<sitemapindex>`` or ``<urlset>``; anything else raises ``ValueError``."""
    try:
        root = ElementTree.fromstring(text.lstrip())
    except ElementTree.ParseError as exc:
        raise ValueError(f"not a sitemap: {exc}") from None
    kind = _local(root.tag)
    if kind == "sitemapindex":
        children = tuple(
            loc for el in root if _local(el.tag) == "sitemap" and (loc := _child_text(el, "loc"))
        )
        if len(children) > MAX_CHILDREN:
            raise ValueError(f"sitemap index lists {len(children)} children (> {MAX_CHILDREN})")
        return Sitemap(children=children, urls={})
    if kind == "urlset":
        urls: dict[str, str | None] = {}
        for el in root:
            if _local(el.tag) != "url":
                continue
            loc = _child_text(el, "loc")
            if loc:
                urls.setdefault(loc, _child_text(el, "lastmod"))
        return Sitemap(children=(), urls=urls)
    raise ValueError(f"not a sitemap: root element <{kind}>")
