"""Build the full-snapshot URL list from an already-saved robots.txt and product sitemap(s).

Offline only: no request is made here. The inputs are files a person saved (browser "Save page
as", raw XML or the WebKit XML-viewer page) or a run already wrote. Output: the robots-allowed,
de-duplicated English product URLs (``/en/buy-<slug>``), one per line, sorted.

Usage: ``python -m ulta_snapshot.urls ROBOTS_TXT OUT_TXT SITEMAP [SITEMAP ...]``

Fails closed: a robots.txt that is not a plain robots file (e.g. a Cloudflare block page), a
sitemap *index* instead of a product sitemap, or zero URLs stops with an error.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from pi_connector_ulta.discover import (
    DiscoveryError,
    child_sitemaps,
    discover_sitemap,
    sitemap_locs,
)
from pi_fetch.ladder import robots_text_from_viewer
from pi_fetch.pacing import RobotsRules

__all__ = ["UrlListError", "build", "load_robots"]

_EN = "https://www.ulta.ae/en/buy-"


class UrlListError(ValueError):
    """The saved inputs cannot give a trustworthy URL list."""


def load_robots(text: str) -> RobotsRules:
    """Rules from a saved robots.txt: plain text, or the browser's ``<pre>`` viewer page."""
    head = text.lstrip()[:64].lower()
    if head.startswith(("<!doctype", "<html")):
        unwrapped = robots_text_from_viewer(text)
        if unwrapped is None:
            raise UrlListError("robots.txt input is an HTML page, not robots.txt (a block page?)")
        text = unwrapped
    if "user-agent" not in text.lower():
        raise UrlListError("robots.txt input has no User-agent line")
    return RobotsRules(text)


def build(robots_text: str, sitemaps: list[str]) -> tuple[list[str], Counter[str]]:
    """Sorted EN product URLs and counts (locs seen, allowed, per-language, refused)."""
    robots = load_robots(robots_text)
    counts: Counter[str] = Counter()
    urls: set[str] = set()
    for document in sitemaps:
        try:
            locs = sitemap_locs(document)
        except DiscoveryError as exc:
            raise UrlListError(str(exc)) from exc
        if child_sitemaps(document, robots) and not any("/buy-" in u for u in locs):
            raise UrlListError("got a sitemap index: save product-sitemap-ae.xml instead")
        keys = discover_sitemap(document, robots)
        counts["locs"] += len(locs)
        counts["product_urls_allowed"] += len(keys)
        counts["not_product_or_refused"] += len(locs) - len(keys)
        urls.update(k.product_url for k in keys if k.product_url.startswith(_EN))
    counts["en"] = len(urls)
    if not urls:
        raise UrlListError("no robots-allowed English product URLs found")
    return sorted(urls), counts


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    robots, out, *maps = argv
    urls, counts = build(
        Path(robots).read_text(encoding="utf-8"),
        [Path(m).read_text(encoding="utf-8") for m in maps],
    )
    Path(out).write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(" ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
