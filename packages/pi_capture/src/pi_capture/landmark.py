"""Landmark Group storefront (Centrepoint, Splash, Babyshop, Home Centre, Max) product pages.

Pure functions over HTML text; nothing fetches. These shops run one Next.js storefront whose
``__NEXT_DATA__`` carries ``props.initialState`` as base64-encoded JSON. The product sits in
``productPageReducerBL.data`` with one entry per sellable variant: its own SKU, EAN
(``externalId``), size and colour option values, and a price block holding both the price the
shopper pays (``priceInfo.price``) and the regular price (``priceInfo.target.priceableFields
.basePrice``).

The page's JSON-LD shows the base price only, so on a marked-down item the generic reader would
record the regular price as the selling price. :func:`readings_from_landmark` therefore reads
prices from the variant block and emits a reading for every price key before the generic readers
run, so JSON-LD can never fill a price this module left unread.

Per-variant stock is not in the page; nothing here infers it.
"""

from __future__ import annotations

import base64
import binascii
import html as html_lib
import json
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pi_capture.generic import LOOKED_FOR as GENERIC_LOOKED_FOR
from pi_capture.generic import (
    JsonObject,
    _emit_price,
    _Emitter,
    _minor_units,
    next_data,
    readings_from_generic,
)
from pi_capture.model import Reading

__all__ = ["LOOKED_FOR", "LandmarkPageError", "landmark_product", "readings_from_landmark"]

_STATE = "__NEXT_DATA__.props.initialState"
_DATA = f"{_STATE}.productPageReducerBL.data"
_GTIN_LENGTHS = frozenset({8, 12, 13, 14})
_MAX_CATEGORY_LEVELS = 4
_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"\s+")


class LandmarkPageError(ValueError):
    """The page is not a readable Landmark product page; the reason says which part is missing."""


def landmark_product(html: str) -> JsonObject:
    """``productPageReducerBL.data`` decoded, or :class:`LandmarkPageError` naming what is absent.

    Numbers come back as :class:`~decimal.Decimal` or ``int``, never ``float``."""
    nd = next_data(html)
    if nd is None:
        raise LandmarkPageError("no __NEXT_DATA__ script")
    props = nd.get("props")
    state: Any = props.get("initialState") if isinstance(props, Mapping) else None
    if isinstance(state, str):
        try:
            state = json.loads(base64.b64decode(state, validate=True), parse_float=Decimal)
        except (binascii.Error, ValueError) as exc:
            raise LandmarkPageError(f"initialState is not base64 JSON: {exc}") from exc
    if not isinstance(state, Mapping):
        raise LandmarkPageError("no initialState object")
    reducer = state.get("productPageReducerBL")
    data = reducer.get("data") if isinstance(reducer, Mapping) else None
    if not isinstance(data, dict) or not data:
        raise LandmarkPageError("no productPageReducerBL.data")
    return data


def _str(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | Decimal):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _dig(node: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def _gs1_check_ok(digits: str) -> bool:
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def _map_gtin(em: _Emitter, raw: Any, path: str) -> None:
    text = _str(raw)
    if text is None:
        em.not_shown("gtin", "variant carries no externalId")
        return
    if not text.strip("0"):
        em.not_shown("gtin", f"externalId is {text!r}: the shop records no barcode")
    elif not text.isdigit() or len(text) not in _GTIN_LENGTHS:
        em.failed("gtin", text, path, "externalId is not an 8/12/13/14 digit barcode")
    elif not _gs1_check_ok(text):
        em.failed("gtin", text, path, "externalId fails the GS1 check digit")
    else:
        em.observed("gtin", text, text.zfill(14), path, "padded to 14 digits")


def _map_prices(em: _Emitter, price_info: Any, path: str) -> None:
    now = _dig(price_info, "price")
    amount, currency = _str(_dig(now, "amount")), _str(_dig(now, "currency"))
    if amount is None:
        em.not_shown("price_minor", "variant price block carries no price")
        em.not_shown("regular_price_minor", "variant price block carries no price")
        return
    _emit_price(em, "price_minor", amount, currency, f"{path}.price.amount")
    now_minor = _minor_units(amount, currency)[0]
    base_path = f"{path}.target.priceableFields.basePrice"
    base = _dig(price_info, "target", "priceableFields", "basePrice")
    was, was_currency = _str(_dig(base, "amount")), _str(_dig(base, "currency"))
    if was is None:
        em.not_shown("regular_price_minor", "variant price block carries no basePrice")
        return
    was_minor = _minor_units(was, was_currency)[0]
    if was_currency != currency:
        em.failed(
            "regular_price_minor",
            f"{was} {was_currency}",
            f"{base_path}.amount",
            f"basePrice currency {was_currency!r} differs from price currency {currency!r}",
            currency=was_currency if was_currency and len(was_currency) == 3 else None,
        )
    elif was_minor is not None and now_minor is not None and was_minor <= now_minor:
        # base equal to the price is a full-price item: there is no separate regular price
        em.not_shown("regular_price_minor", "basePrice not above the price; not marked down")
    else:
        _emit_price(em, "regular_price_minor", was, was_currency, f"{base_path}.amount")


def _colour_labels(data: Mapping[str, Any]) -> dict[str, str]:
    """``{option value: shopper-facing label}`` for the Color option."""
    labels: dict[str, str] = {}
    for option in data.get("options") or []:
        choice = _dig(option, "attributeChoice")
        if _str(_dig(choice, "attributeName")) != "Color":
            continue
        for allowed in _dig(choice, "allowedValues") or []:
            value, label = _str(_dig(allowed, "value")), _str(_dig(allowed, "label"))
            if value is not None and label is not None:
                labels[value] = label
    return labels


def _images(data: Mapping[str, Any], colour: str | None) -> tuple[list[str], str | None]:
    """The asset URLs for ``colour``; every asset when none is tagged with it (with a note)."""
    assets = [a for a in data.get("assets") or [] if isinstance(a, Mapping)]
    urls = [(u, a.get("tags") or []) for a in assets if (u := _str(a.get("contentUrl")))]
    if colour is not None:
        tag = f"color:{colour.lower()}"
        own = [u for u, tags in urls if isinstance(tags, list) and tag in tags]
        if own:
            return own, None
    every = [u for u, _tags in urls]
    return every, ("no asset tagged with this colour; all product assets" if every else None)


def _map_product(em: _Emitter, data: Mapping[str, Any]) -> None:
    if (title := _str(data.get("name"))) is not None:
        em.observed("title", title, title, f"{_DATA}.name")
    brand = _str(_dig(data, "brand", "displayValue"))
    if brand is not None:
        em.observed("brand", brand, brand, f"{_DATA}.brand.displayValue")
    # the last crumb is the product itself and carries no uri; the rest are the category path
    crumbs = [
        label
        for c in data.get("breadcrumbs") or []
        if _str(_dig(c, "uri")) is not None and (label := _str(_dig(c, "label"))) is not None
    ]
    if crumbs:
        raw = " > ".join(crumbs)
        em.observed("breadcrumb", raw, crumbs, f"{_DATA}.breadcrumbs[].label")
        levels = crumbs[:_MAX_CATEGORY_LEVELS]
        em.observed("category_l1..l4", " > ".join(levels), levels, f"{_DATA}.breadcrumbs[].label")
    if (desc := _str(data.get("description"))) is not None:
        text = _SPACE.sub(" ", html_lib.unescape(_TAG.sub(" ", desc))).strip()
        if text:
            em.observed("description", desc, text, f"{_DATA}.description", "markup stripped")
    if (style := _str(data.get("sku"))) is not None:
        em.observed("style_id", style, style, f"{_DATA}.sku", "Landmark product-level sku")
        em.observed("style_id_source", style, "captured", f"{_DATA}.sku")


def _variant_readings(
    data: Mapping[str, Any], variant: Mapping[str, Any], path: str, labels: Mapping[str, str]
) -> _Emitter:
    em = _Emitter()
    sku = _str(variant.get("sku"))
    if sku is None:
        em.not_shown("retailer_sku", "variant carries no sku")
    else:
        em.observed("retailer_sku", sku, sku, f"{path}.sku")
    _map_gtin(em, variant.get("externalId"), f"{path}.externalId")
    options = variant.get("optionValues")
    options = options if isinstance(options, Mapping) else {}
    if (size := _str(options.get("Size"))) is not None:
        em.observed("size_label", size, size, f"{path}.optionValues.Size")
    colour = _str(options.get("Color"))
    if colour is not None:
        em.observed("colour_code", colour, colour, f"{path}.optionValues.Color")
        if (label := labels.get(colour)) is not None:
            em.observed("colour_name", label, label, f"{_DATA}.options[Color].allowedValues.label")
    _map_prices(em, variant.get("priceInfo"), f"{path}.priceInfo")
    images, note = _images(data, colour)
    if images:
        em.observed("image_urls", "\n".join(images), images, f"{_DATA}.assets[].contentUrl", note)
        em.observed("image_count", str(len(images)), len(images), f"{_DATA}.assets[].contentUrl")
    _map_product(em, data)
    return em


def readings_from_landmark(
    html: str, *, locale: str, url: str | None = None
) -> list[list[Reading]]:
    """One reading list per sellable variant, in page order.

    A product page without variants (a single-SKU item) is read as one variant from the product
    block itself. Each list carries the variant's own readings, then the product's, then whatever
    the generic readers add for keys still unread (canonical URL, description, structured data).
    Raises :class:`LandmarkPageError` when the page has no Landmark product block."""
    data = landmark_product(html)
    generic = readings_from_generic(html, locale=locale, url=url)
    labels = _colour_labels(data)
    variants = [v for v in data.get("variants") or [] if isinstance(v, Mapping)]
    blocks: list[tuple[Mapping[str, Any], str]] = (
        [(v, f"{_DATA}.variants[{i}]") for i, v in enumerate(variants)]
        if variants
        else [(data, _DATA)]
    )
    out: list[list[Reading]] = []
    for variant, path in blocks:
        em = _variant_readings(data, variant, path, labels)
        em.extend(generic)
        out.append(em.readings)
    return out


_LANDMARK_KEYS = frozenset(
    {
        "brand",
        "breadcrumb",
        "category_l1..l4",
        "colour_code",
        "colour_name",
        "description",
        "gtin",
        "image_count",
        "image_urls",
        "price_minor",
        "regular_price_minor",
        "retailer_sku",
        "size_label",
        "style_id",
        "style_id_source",
        "title",
    }
)
LOOKED_FOR: frozenset[str] = _LANDMARK_KEYS | GENERIC_LOOKED_FOR
"""Every registry key ``readings_from_landmark`` can yield, for ``ProductCapture.looked_for``."""
