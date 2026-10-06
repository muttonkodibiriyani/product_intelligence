"""Helpers shared by readers whose storefront embeds the product as one JSON object.

Ounass (``"pdp":``) and Bloomingdale's UAE (``"productData":``) both render the whole product
record into the page. These helpers decode that object, carry the page's own stock flag as a
second ``structured_data`` block (the feed takes availability only when every stock statement on
the page agrees) and say when a readable product page is outside the capture's scope.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pi_capture.generic import _DECODER, JsonObject
from pi_capture.model import Reading
from pi_capture.registry import get as get_attribute

__all__ = ["DEPARTMENTS", "NoProductObject", "OutOfScopePage", "object_after", "stock_flag"]

DEPARTMENTS = {
    "WOMEN": "women",
    "WOMENS": "women",
    "MEN": "men",
    "MENS": "men",
    "KIDS": "kids",
    "BABY": "baby",
    "UNISEX": "unisex",
}


class NoProductObject(ValueError):  # noqa: N818 - a page state, not a failure
    """The page carries no product object to read: not a product page, or not one this reader
    knows."""


class OutOfScopePage(ValueError):  # noqa: N818 - a page state, not a failure
    """A readable product page outside what the capture is for (say, not beauty); the reason
    says which field put it out."""


def object_after(html: str, key: str) -> JsonObject | None:
    """The JSON object right after the first ``"key":`` in the page, numbers as ``Decimal``/``int``;
    ``None`` when the key is absent or what follows does not decode to an object."""
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*', html)
    if m is None:
        return None
    try:
        obj, _end = _DECODER.raw_decode(html, m.end())
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def stock_flag(
    node: Any, key: str, path: str, note: str, *, negate: bool = False
) -> Reading | None:
    """The page's own stock flag ``node[key]`` as a ``structured_data`` block, in the shape the
    feed reads (``item_in_stock``; ``negate`` for an out-of-stock flag). ``None`` when the key is
    absent. A value that is present but not a boolean is kept as stated, so the feed reads the
    page's stock as unknown instead of letting the JSON-LD speak alone."""
    if not isinstance(node, Mapping) or key not in node:
        return None
    value = node[key]
    if isinstance(value, bool):
        flag: Any = value != negate
        raw = "true" if flag else "false"
    else:
        flag, raw = value, "null" if value is None else str(value)
        note = f"{note}; not a boolean, so the page's stock is unknown"
    return Reading(
        "structured_data",
        get_attribute("structured_data").level,
        "observed",
        raw,
        {"item_in_stock": flag},
        path,
        note,
    )
