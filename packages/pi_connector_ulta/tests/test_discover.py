import json
from pathlib import Path

import pytest

from pi_connector_ulta.discover import DiscoveryError, discover_category, discover_sitemap

FIXTURES = Path(__file__).parent / "fixtures"


def test_sitemap_discovers_only_ulta_product_urls() -> None:
    found = discover_sitemap((FIXTURES / "sitemap_SYNTHETIC.xml").read_text())
    assert [item.product_url for item in found] == [
        "https://www.ulta.ae/ar/product/glow-balm/P100",
        "https://www.ulta.ae/en/product/glow-balm/P100",
    ]


def test_category_discovers_deduplicated_sorted_items() -> None:
    found = discover_category((FIXTURES / "category_SYNTHETIC.json").read_text())
    assert [item.source_product_id for item in found] == ["P100-DUP", "P200"]


@pytest.mark.parametrize("document", ["{", "{}", '{"items": {}}'])
def test_invalid_category_raises(document: str) -> None:
    with pytest.raises(DiscoveryError):
        discover_category(document)


def test_category_ignores_malformed_and_insecure_urls() -> None:
    document = json.dumps(
        {
            "items": [
                None,
                {"url": 3},
                {"url": "http://www.ulta.ae/en/product/no"},
                {"url": "https://www.ulta.ae/en/category/makeup"},
            ]
        }
    )
    assert discover_category(document) == ()


def test_invalid_sitemap_raises() -> None:
    with pytest.raises(DiscoveryError, match="invalid sitemap"):
        discover_sitemap("<urlset>")
