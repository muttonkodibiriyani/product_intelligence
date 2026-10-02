"""Ulta UAE catalogue connector (offline parsing and discovery only)."""

from pi_connector_ulta.catalog import CatalogError, PlpHit, UltaProduct, UltaVariant
from pi_connector_ulta.connector import UltaConnector
from pi_connector_ulta.discover import ListingKey, discover_category, discover_sitemap
from pi_connector_ulta.dom import merge_page_json, parse_pdp_html, parse_plp_html
from pi_connector_ulta.models import ProductRecord
from pi_connector_ulta.parse import ParseError, parse_product_html, parse_product_json

__all__ = [
    "CatalogError",
    "ListingKey",
    "ParseError",
    "PlpHit",
    "ProductRecord",
    "UltaConnector",
    "UltaProduct",
    "UltaVariant",
    "discover_category",
    "discover_sitemap",
    "merge_page_json",
    "parse_pdp_html",
    "parse_plp_html",
    "parse_product_html",
    "parse_product_json",
]
