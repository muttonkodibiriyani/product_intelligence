"""Ulta UAE catalogue connector (offline parsing and discovery only)."""

from pi_connector_ulta.connector import UltaConnector
from pi_connector_ulta.discover import ListingKey, discover_category, discover_sitemap
from pi_connector_ulta.models import ProductRecord
from pi_connector_ulta.parse import ParseError, parse_product_html, parse_product_json

__all__ = [
    "ListingKey",
    "ParseError",
    "ProductRecord",
    "UltaConnector",
    "discover_category",
    "discover_sitemap",
    "parse_product_html",
    "parse_product_json",
]
