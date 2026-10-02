"""Shared synthetic fixtures. No real retailer page is ever used here."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from pi_capture.model import ProductCapture, Reading

SHA = "a" * 64

PRODUCT_HTML = """<!doctype html>
<html lang="en-AE"><head><title>Radiant Foundation 240 | Example Shop</title>
<link rel="canonical" href="https://shop.example/en/p/foundation-240">
<link rel="alternate" hreflang="ar-AE" href="https://shop.example/ar/p/foundation-240">
<meta property="og:title" content="OG Foundation">
<meta property="og:image" content="https://img.example/og1.jpg">
<meta property="og:image" content="https://img.example/og2.jpg">
<meta name="description" content="Meta description">
<meta property="og:type" content="product">
<meta property="og:locale" content="en_AE">
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product",
 "name": "Radiant Foundation 240", "brand": {"@type": "Brand", "name": "Glow"},
 "description": "A buildable foundation.",
 "image": ["https://img.example/a.jpg", {"@type": "ImageObject", "url": "https://img.example/b.jpg"}],
 "sku": "SEP-11029384", "gtin13": "3614273661096", "mpn": "T3-240-30",
 "offers": {"@type": "Offer", "price": "189.00", "priceCurrency": "AED",
            "availability": "https://schema.org/InStock",
            "seller": {"@type": "Organization", "name": "Example Shop"},
            "priceSpecification": [{"@type": "UnitPriceSpecification",
                                    "priceType": "https://schema.org/ListPrice",
                                    "price": "229.00", "priceCurrency": "AED"}]},
 "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.3", "reviewCount": "214"}}
</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
  {"@type": "ListItem", "position": 2, "name": "Face"},
  {"@type": "ListItem", "position": 1, "name": "Beauty"},
  {"@type": "ListItem", "position": 3, "item": {"@id": "/c/foundation", "name": "Foundation"}}]}
</script>
</head><body><h1>Radiant Foundation 240</h1></body></html>
"""


@pytest.fixture
def product_html() -> str:
    return PRODUCT_HTML


CaptureFactory = Callable[..., ProductCapture]


def _make_capture(
    retailer: str = "shop", readings: tuple[Reading, ...] = (), **overrides: object
) -> ProductCapture:
    kwargs: dict[str, object] = {
        "source": "test",
        "retailer": retailer,
        "url": "https://shop.example/en/p/x",
        "locale": "en-AE",
        "retrieved_at": datetime(2026, 10, 2, 9, 0, tzinfo=UTC),
        "egress": "direct",
        "page_sha256": SHA,
        "readings": readings,
    }
    kwargs.update(overrides)
    return ProductCapture(**kwargs)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def make_capture() -> CaptureFactory:
    return _make_capture
