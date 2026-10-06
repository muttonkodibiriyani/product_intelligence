"""Bloomingdale's UAE (bloomingdales.ae, Salesforce Commerce Cloud headless) product-page reader,
beauty only.

Pure functions over HTML text; nothing fetches. The page embeds the SCAPI product record at
``"productData":`` (about 5 MB into the page): the merchandise hierarchy (``c_rms_div``,
``c_rms_dept``, ``c_rms_class``, ``c_rms_subclass``, ``c_rms_group`` for gender), the price block
``c_price`` (``sales`` and, on a markdown, ``list``), ``c_size``, ``c_barcode``, the image set and
``inventory.orderable``. :func:`readings_from_bloomingdales` reads those first and lets
:func:`pi_capture.generic.readings_from_generic` fill whatever is left (JSON-LD among it: the
description and the breadcrumb come from there).

Scope: the capture is for beauty. ``c_rms_div`` other than ``Beauty``, or ``c_rms_dept`` ``Home``
(home fragrance and candles), raises :class:`OutOfScopePage`; ``c_isBeauty`` is not used, it is
false on beauty pages too. A page with no ``productData`` raises :class:`NoProductObject`.

Stock: ``inventory.orderable`` is carried as a second ``structured_data`` block beside the JSON-LD
offer; the feed takes availability only when both agree. Promotions are internal ids
(``productPromotions[].promotionId``, e.g. one GWP id on every page), not shopper-facing labels,
so no badge is read from them. The page HTML carries no ratings; they are ``not_shown``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pi_capture.faces import _CONCENTRATIONS, _emit_size
from pi_capture.generic import LOOKED_FOR as GENERIC_LOOKED_FOR
from pi_capture.generic import (
    JsonObject,
    _emit_gtin,
    _emit_price,
    _Emitter,
    _minor_units,
    readings_from_generic,
)
from pi_capture.model import Reading
from pi_capture.page_json import (
    DEPARTMENTS,
    NoProductObject,
    OutOfScopePage,
    object_after,
    stock_flag,
)

__all__ = ["LOOKED_FOR", "readings_from_bloomingdales"]

_PD = "productData"


def _str(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)
    return None


def bloomingdales_product(html: str) -> JsonObject:
    """The ``productData`` object if the page is an in-scope beauty product, else why not."""
    pd = object_after(html, _PD)
    if pd is None:
        raise NoProductObject("no productData object")
    division = _str(pd.get("c_rms_div"))
    if division != "Beauty":
        raise OutOfScopePage(f"c_rms_div {division!r}, not Beauty")
    if _str(pd.get("c_rms_dept")) == "Home":
        raise OutOfScopePage("c_rms_dept Home (home fragrance and candles are excluded)")
    return pd


def _map_identity(em: _Emitter, pd: Mapping[str, Any]) -> None:
    if (sku := _str(pd.get("id"))) is not None:
        em.observed("retailer_sku", sku, sku, f"{_PD}.id")
    master = pd.get("master")
    if isinstance(master, Mapping) and (mid := _str(master.get("masterId"))) is not None:
        em.observed("style_id", mid, mid, f"{_PD}.master.masterId")
        em.observed("style_id_source", mid, "captured", f"{_PD}.master.masterId")
    if (brand := _str(pd.get("c_brand"))) is not None:
        em.observed("brand", brand, brand, f"{_PD}.c_brand")
    if (title := _str(pd.get("name"))) is not None:
        em.observed("title", title, title, f"{_PD}.name")
    if (barcode := _str(pd.get("c_barcode"))) is not None:
        _emit_gtin(em, barcode, f"{_PD}.c_barcode")


def _map_taxonomy(em: _Emitter, pd: Mapping[str, Any]) -> None:
    if (gender := _str(pd.get("c_rms_group"))) is not None:
        if (mapped := DEPARTMENTS.get(gender.upper())) is None:
            em.failed("department", gender, f"{_PD}.c_rms_group", "outside the department enum")
        else:
            em.observed("department", gender, mapped, f"{_PD}.c_rms_group")
    levels = [
        v
        for k in ("c_rms_div", "c_rms_dept", "c_rms_class", "c_rms_subclass")
        if (v := _str(pd.get(k))) is not None
    ]
    if levels:
        em.observed("category_l1..l4", " > ".join(levels), levels, f"{_PD}.c_rms_div..subclass")
    if (sub := _str(pd.get("c_rms_subclass"))) is not None:
        em.observed("product_type", sub, sub, f"{_PD}.c_rms_subclass")


def _price_part(pd: Mapping[str, Any], part: str) -> tuple[str | None, str | None]:
    block = pd.get("c_price")
    node = block.get(part) if isinstance(block, Mapping) else None
    if not isinstance(node, Mapping):
        return None, None
    return _str(node.get("value")), _str(node.get("currency"))


def _map_prices(em: _Emitter, pd: Mapping[str, Any]) -> None:
    price, currency = _price_part(pd, "sales")
    if price is None:
        return
    _emit_price(em, "price_minor", price, currency, f"{_PD}.c_price.sales.value")
    struck, struck_currency = _price_part(pd, "list")
    if struck is None:
        return
    path = f"{_PD}.c_price.list.value"
    sale, _r, _n = _minor_units(price, currency)
    regular, _r, _n = _minor_units(struck, struck_currency)
    if sale is None or regular is None or struck_currency != currency or regular <= sale:
        em.failed(
            "regular_price_minor",
            f"{struck} {struck_currency}" if struck_currency else struck,
            path,
            "list price not above a readable sale price in the same currency; not a regular price",
            currency=struck_currency if struck_currency and len(struck_currency) == 3 else None,
        )
        return
    _emit_price(em, "regular_price_minor", struck, struck_currency, path)


def _map_content(em: _Emitter, pd: Mapping[str, Any]) -> None:
    for key in ("c_size", "c_liquidSize"):
        if (size := _str(pd.get(key))) is not None:
            _emit_size(em, size, f"{_PD}.{key}")
            break
    images = pd.get("c_images")
    xlarge = images.get("xlarge") if isinstance(images, Mapping) else None
    gallery: list[str] = []
    for image in xlarge or []:
        url = _str(image.get("url")) if isinstance(image, Mapping) else None
        if url is not None and url not in gallery:
            gallery.append(url)
    if gallery:
        em.observed("image_urls", "\n".join(gallery), gallery, f"{_PD}.c_images.xlarge[].url")
        em.observed("image_count", str(len(gallery)), len(gallery), f"{_PD}.c_images.xlarge[].url")
    haystack = " ".join(t for k in ("name", "c_rms_subclass") if (t := _str(pd.get(k))))
    for pattern, value in _CONCENTRATIONS:
        if (m := pattern.search(haystack)) is not None:
            em.observed("concentration", m.group(0), value, f"{_PD}.name|c_rms_subclass")
            break


def readings_from_bloomingdales(html: str, *, locale: str, url: str | None = None) -> list[Reading]:
    """Bloomingdale's readings first, then the generic readers fill every key still unread, then
    ratings are marked ``not_shown``; ``inventory.orderable`` is appended as its own
    ``structured_data`` block. Raises :class:`NoProductObject` or :class:`OutOfScopePage`."""
    pd = bloomingdales_product(html)
    em = _Emitter()
    _map_identity(em, pd)
    _map_taxonomy(em, pd)
    _map_prices(em, pd)
    _map_content(em, pd)
    em.extend(readings_from_generic(html, locale=locale, url=url))
    for key in ("rating_value", "rating_count"):
        em.not_shown(key, "Bloomingdale's UAE product pages carry no ratings in the HTML")
    inventory = pd.get("inventory")
    flag = stock_flag(
        inventory.get("orderable") if isinstance(inventory, Mapping) else None,
        f"{_PD}.inventory.orderable",
        "SCAPI inventory orderable flag; cross-checked with the JSON-LD availability",
    )
    if flag is not None:
        em.readings.append(flag)
    return em.readings


LOOKED_FOR: frozenset[str] = (
    frozenset(
        {
            "category_l1..l4",
            "concentration",
            "department",
            "product_type",
            "size_label",
            "size_unit",
            "size_value",
            "style_id",
            "style_id_source",
        }
    )
    | GENERIC_LOOKED_FOR
)
"""Every registry key ``readings_from_bloomingdales`` can yield."""
