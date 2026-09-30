from pathlib import Path

import pytest

from pi_connector_ulta.discover import (
    DiscoveryError,
    child_sitemaps,
    discover_category,
    discover_category_json,
    discover_sitemap,
    locale_url,
    sitemap_locs,
)
from pi_fetch.pacing import RobotsRules

FIXTURES = Path(__file__).parent / "fixtures"
ROBOTS = RobotsRules((FIXTURES / "ulta_ae_robots.txt").read_text())


def _sitemap(*locs: str) -> str:
    urls = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'


def test_sitemap_index_from_webkit_viewer_lists_product_sitemaps_first() -> None:
    document = (FIXTURES / "ulta_ae_sitemap_index_webkit_view.html").read_text()
    children = child_sitemaps(document, ROBOTS)
    assert len(children) == 3
    assert "product-sitemap" in children[0]


def test_product_sitemap_keeps_only_robots_allowed_product_pages() -> None:
    document = _sitemap(
        "https://www.ulta.ae/en/buy-skin-tint-blurring-elixir",
        "https://www.ulta.ae/ar/buy-skin-tint-blurring-elixir/",
        "https://www.ulta.ae/en/buy-skin-tint-blurring-elixir",  # duplicate
        "https://www.ulta.ae/en/buy-x?colour=red",  # query: robots /*?
        "https://www.ulta.ae/en/shop-makeup-nails",  # category, not a product
        "http://www.ulta.ae/en/buy-insecure",
        "https://www.ulta.com.kw/en/buy-other-market",
    )
    assert [k.product_url for k in discover_sitemap(document, ROBOTS)] == [
        "https://www.ulta.ae/ar/buy-skin-tint-blurring-elixir",
        "https://www.ulta.ae/en/buy-skin-tint-blurring-elixir",
    ]


def test_no_robots_rule_can_open_a_disallowed_path() -> None:
    assert not ROBOTS.allows("https://www.ulta.ae/en/buy-x?page=2")
    assert discover_sitemap(_sitemap("https://www.ulta.ae/en/buy-x?page=2"), ROBOTS) == ()


def test_category_dom_tiles_become_listing_keys() -> None:
    document = (FIXTURES / "ulta_ae_plp_en_makeup.html").read_text()
    keys = discover_category(document, "en", ROBOTS)
    assert len(keys) == 4
    assert all(k.product_url.startswith("https://www.ulta.ae/en/buy-") for k in keys)
    assert {"PF0000091796", "345192816"} <= {k.source_product_id for k in keys}


def test_category_json_path_rejects_non_listing_payload() -> None:
    with pytest.raises(DiscoveryError):
        discover_category_json('{"data": {}}', "en", ROBOTS)


def test_locale_url_switches_storefront() -> None:
    assert (
        locale_url("https://www.ulta.ae/en/buy-signature-lip-pencil", "ar")
        == "https://www.ulta.ae/ar/buy-signature-lip-pencil"
    )
    with pytest.raises(DiscoveryError):
        locale_url("https://www.ulta.ae/en/shop-makeup-nails", "ar")


@pytest.mark.parametrize("document", ["<urlset>", "<html><body>hello</body></html>"])
def test_invalid_sitemap_raises(document: str) -> None:
    with pytest.raises(DiscoveryError):
        sitemap_locs(document)
