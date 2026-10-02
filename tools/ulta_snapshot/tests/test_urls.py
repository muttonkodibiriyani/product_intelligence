"""Offline URL-list builder: robots-allowed EN product URLs from saved files."""

from __future__ import annotations

import html
from pathlib import Path

import pytest
from ulta_snapshot.urls import UrlListError, build, main

FIXTURES = Path(__file__).parents[3] / "packages/pi_connector_ulta/tests/fixtures"
ROBOTS = (FIXTURES / "ulta_ae_robots.txt").read_text()
B = "https://www.ulta.ae"
SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{B}/en/buy-glow-balm</loc></url>
  <url><loc>{B}/en/buy-glow-balm/</loc></url>
  <url><loc>{B}/ar/buy-glow-balm</loc></url>
  <url><loc>{B}/en/buy-lip-tint</loc></url>
  <url><loc>{B}/en/buy-lip-tint?colour=red</loc></url>
  <url><loc>{B}/en/makeup</loc></url>
  <url><loc>http://www.ulta.ae/en/buy-plain-http</loc></url>
  <url><loc>https://outside.example/en/buy-nope</loc></url>
</urlset>"""


def test_only_allowed_english_product_urls_deduplicated() -> None:
    urls, counts = build(ROBOTS, [SITEMAP])
    assert urls == [f"{B}/en/buy-glow-balm", f"{B}/en/buy-lip-tint"]
    assert counts["en"] == 2
    assert counts["locs"] == 8


def test_browser_viewer_pages_are_accepted() -> None:
    viewer = f"<html><head></head><body><pre>{html.escape(ROBOTS)}</pre></body></html>"
    urls, _ = build(viewer, [SITEMAP])
    assert len(urls) == 2


def test_block_page_as_robots_fails_closed() -> None:
    block = (
        Path(__file__).parents[3] / "docs/recon/samples/probe/ulta_ae_cf_challenge_webkit_head.html"
    )
    with pytest.raises(UrlListError, match="HTML page"):
        build(block.read_text(), [SITEMAP])


def test_sitemap_index_is_refused() -> None:
    index = (FIXTURES / "ulta_ae_sitemap_index_webkit_view.html").read_text()
    with pytest.raises(UrlListError, match="index"):
        build(ROBOTS, [index])


def test_cli_writes_sorted_list(tmp_path: Path) -> None:
    (tmp_path / "robots.txt").write_text(ROBOTS)
    (tmp_path / "sm.xml").write_text(SITEMAP)
    out = tmp_path / "full_en.txt"
    assert main([str(tmp_path / "robots.txt"), str(out), str(tmp_path / "sm.xml")]) == 0
    assert out.read_text().splitlines() == [f"{B}/en/buy-glow-balm", f"{B}/en/buy-lip-tint"]
