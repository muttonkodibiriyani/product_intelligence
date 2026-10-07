"""Ounass (ounass.ae) product-page reader, beauty only.

Pure functions over HTML text; nothing fetches. The page renders the whole product into one JSON
object at ``"pdp":``: division/department/class, the shopper price in AED with the struck price
(``slashedPriceInAED``), the barcode, gender, one badge, the gallery, the description and an
``outOfStock`` flag. :func:`readings_from_ounass` reads those first and lets
:func:`pi_capture.generic.readings_from_generic` fill whatever is left (the JSON-LD block among
it).

Scope: the capture is for beauty. A page whose ``division`` is not ``Beauty``, or whose
``department`` is ``Home`` (home fragrance and candles), raises :class:`OutOfScopePage`; a page
with no ``pdp`` object raises :class:`NoProductObject`. The Ounass capture is partial (the run
stopped before every planned page was fetched), so a page not read says nothing about the
product: no removal and no stock-out is ever inferred from absence.

Stock: ``outOfStock`` is carried as a second ``structured_data`` block beside the JSON-LD offer;
the feed takes availability only when both agree. An out-of-stock page stays a row, published as
out of stock. Ounass shows no ratings in the page; they are recorded as ``not_shown``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pi_capture._page_attrs import emit_bullets, emit_hex, emit_inci
from pi_capture._size import emit_size
from pi_capture.faces import _CONCENTRATIONS
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

__all__ = ["LOOKED_FOR", "readings_from_ounass"]

_PDP = "pdp"
_CURRENCY = "AED"  # the ``...InAED`` fields; the page's own display currency may differ
_IMAGE_SCHEME = "https:"
_NO_SIZE = "NO SIZE"
# "Barbiere Beard Wash, 200ml": the size sits in the name when the selector says NO SIZE
_NAME_SIZE = re.compile(r"(\d+(?:[.,]\d+)?\s?(?:ml|g|kg|l|oz))\s*$", re.I)


def _str(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)
    return None


def ounass_product(html: str) -> JsonObject:
    """The ``pdp`` object if the page is an in-scope beauty product, else the reason why not."""
    pdp = object_after(html, _PDP)
    if pdp is None:
        raise NoProductObject("no pdp object")
    division = _str(pdp.get("division"))
    if division != "Beauty":
        raise OutOfScopePage(f"division {division!r}, not Beauty")
    if _str(pdp.get("department")) == "Home":
        raise OutOfScopePage("department Home (home fragrance and candles are excluded)")
    return pdp


def _map_identity(em: _Emitter, pdp: Mapping[str, Any]) -> None:
    if (sku := _str(pdp.get("styleColorId"))) is not None:
        em.observed("retailer_sku", sku, sku, f"{_PDP}.styleColorId", "style and colour id")
    if (parent := _str(pdp.get("parentSku"))) is not None:
        em.observed("style_id", parent, parent, f"{_PDP}.parentSku")
        em.observed("style_id_source", parent, "captured", f"{_PDP}.parentSku")
    if (brand := _str(pdp.get("designerCategoryEnglishName"))) is not None:
        em.observed("brand", brand, brand, f"{_PDP}.designerCategoryEnglishName")
    for key in ("nameInEnglish", "name"):
        if (title := _str(pdp.get(key))) is not None:
            em.observed("title", title, title, f"{_PDP}.{key}")
            break
    if (barcode := _str(pdp.get("barcode"))) is not None:
        _emit_gtin(em, barcode, f"{_PDP}.barcode")


def _map_taxonomy(em: _Emitter, pdp: Mapping[str, Any]) -> None:
    if (gender := _str(pdp.get("gender"))) is not None:
        if (mapped := DEPARTMENTS.get(gender.upper())) is None:
            em.failed("department", gender, f"{_PDP}.gender", "outside the department enum")
        else:
            em.observed("department", gender, mapped, f"{_PDP}.gender")
    levels = [
        v
        for k in ("division", "department", "class", "subClass")
        if (v := _str(pdp.get(k))) is not None
    ]
    if levels:
        em.observed("category_l1..l4", " > ".join(levels), levels, f"{_PDP}.division..subClass")
    if (sub := _str(pdp.get("subClass"))) is not None:
        em.observed("product_type", sub, sub, f"{_PDP}.subClass")
    crumbs = [
        n
        for c in pdp.get("breadcrumbs") or []
        if isinstance(c, Mapping) and (n := _str(c.get("name"))) is not None
    ]
    if crumbs:
        em.observed("breadcrumb", " > ".join(crumbs), crumbs, f"{_PDP}.breadcrumbs")


def _map_prices(em: _Emitter, pdp: Mapping[str, Any]) -> None:
    price = _str(pdp.get("priceInAED"))
    if price is None:
        return
    _emit_price(em, "price_minor", price, _CURRENCY, f"{_PDP}.priceInAED")
    struck = _str(pdp.get("slashedPriceInAED"))
    if struck is None:
        return
    sale, _r, _n = _minor_units(price, _CURRENCY)
    regular, _r, _n = _minor_units(struck, _CURRENCY)
    path = f"{_PDP}.slashedPriceInAED"
    if sale is None or regular is None or regular <= sale:
        em.failed(
            "regular_price_minor",
            f"{struck} {_CURRENCY}",
            path,
            "struck price not above a readable sale price; not a regular price",
            currency=_CURRENCY,
        )
        return
    _emit_price(em, "regular_price_minor", struck, _CURRENCY, path)


def _map_size(em: _Emitter, pdp: Mapping[str, Any], title: str | None) -> None:
    sizes = [s for s in pdp.get("sizes") or [] if isinstance(s, Mapping)]
    codes = [c for s in sizes if (c := _str(s.get("sizeCode"))) not in (None, _NO_SIZE)]
    if len(sizes) == 1 and len(codes) == 1:
        emit_size(em, codes[0], f"{_PDP}.sizes[0].sizeCode")
    elif len(sizes) <= 1 and title and (m := _NAME_SIZE.search(title)) is not None:
        emit_size(em, m.group(1), f"{_PDP}.nameInEnglish (size at the end of the name)")


def _map_merch(em: _Emitter, pdp: Mapping[str, Any]) -> None:
    badge = pdp.get("badge")
    label = _str(badge.get("valueEn")) if isinstance(badge, Mapping) else None
    if label is not None:
        em.observed("badges", label, [label], f"{_PDP}.badge.valueEn")
        if label.upper() == "GIFT WITH PURCHASE":
            em.observed("gift_with_purchase", label, label, f"{_PDP}.badge.valueEn")


def _map_colour(em: _Emitter, pdp: Mapping[str, Any]) -> None:
    """Shade name, swatch colour and colour id of the page's own colour; only on a product sold
    in colours (``colors`` listed), where ``colorId`` is the page's colour and not the single
    no-colour id every other product carries."""
    selected = pdp.get("selectedColor")
    if not pdp.get("colors") or not isinstance(selected, Mapping):
        return
    if (label := _str(selected.get("label"))) is not None:
        em.observed("shade_name", label, label, f"{_PDP}.selectedColor.label")
    emit_hex(em, selected.get("hex"), f"{_PDP}.selectedColor.hex")
    if (code := _str(pdp.get("colorId"))) is not None:
        em.observed("colour_code", code, code, f"{_PDP}.colorId")


def _map_tabs(em: _Emitter, pdp: Mapping[str, Any]) -> None:
    for tab in pdp.get("contentTabs") or []:
        if not isinstance(tab, Mapping) or not isinstance(body := tab.get("html"), str):
            continue
        tab_id = tab.get("tabId")
        if tab_id == "ingredients":
            emit_inci(em, body, f"{_PDP}.contentTabs[ingredients].html")
        elif tab_id == "keyDetails":
            emit_bullets(em, body, f"{_PDP}.contentTabs[keyDetails].html")


def _flag(value: Any) -> bool | None:
    if value in (1, "1", True):
        return True
    if value in (0, "0", False):
        return False
    return None


def _map_offer(em: _Emitter, pdp: Mapping[str, Any]) -> None:
    """Merchandising class and the shopper-facing offer extras: loyalty points and instalments.
    Shipping and returns are site policy (the same delivery tab on every page), not read here."""
    if _flag(pdp.get("isClearance")):
        em.observed("lifecycle_class", "isClearance=1", "clearance", f"{_PDP}.isClearance")
    elif (season := _str(pdp.get("season"))) is not None:
        if season.lower() == "continuity":
            em.observed("lifecycle_class", season, "core", f"{_PDP}.season", "Continuity = core")
        else:
            em.failed("lifecycle_class", season, f"{_PDP}.season", "season not mapped")
    if _flag(pdp.get("exclusive")):
        em.observed("exclusivity", "exclusive=1", "exclusive", f"{_PDP}.exclusive")
    points = pdp.get("amberPoints")
    if isinstance(points, int) and not isinstance(points, bool) and points >= 0:
        em.observed("loyalty_points", str(points), points, f"{_PDP}.amberPoints", "Amber points")
    banner = pdp.get("bnplPromoBanner")
    options = banner.get("options") if isinstance(banner, Mapping) else None
    providers = [
        key
        for o in options or []
        if isinstance(o, Mapping)
        and o.get("isAmountWithinLimits") is True
        and (key := _str(o.get("key"))) is not None
    ]
    if providers:
        em.observed(
            "installment_provider",
            ", ".join(providers),
            providers,
            f"{_PDP}.bnplPromoBanner.options[].key",
            "providers whose limits cover this price",
        )


def _map_content(em: _Emitter, pdp: Mapping[str, Any], title: str | None) -> None:
    gallery: list[str] = []
    for image in pdp.get("images") or []:
        src = _str(image.get("oneX")) if isinstance(image, Mapping) else None
        if src is None:
            continue
        url = _IMAGE_SCHEME + src if src.startswith("//") else src
        if url not in gallery:
            gallery.append(url)
    if gallery:
        em.observed("image_urls", "\n".join(gallery), gallery, f"{_PDP}.images[].oneX")
        em.observed("image_count", str(len(gallery)), len(gallery), f"{_PDP}.images[].oneX")
    if (desc := _str(pdp.get("descriptionText"))) is not None:
        em.observed("description", desc, desc, f"{_PDP}.descriptionText")
    haystack = " ".join(t for t in (title, _str(pdp.get("subClass"))) if t)
    for pattern, value in _CONCENTRATIONS:
        if (m := pattern.search(haystack)) is not None:
            em.observed("concentration", m.group(0), value, f"{_PDP}.nameInEnglish|subClass")
            break


def readings_from_ounass(html: str, *, locale: str, url: str | None = None) -> list[Reading]:
    """Ounass readings first, then the generic readers fill every key still unread, then ratings
    are marked ``not_shown``; the ``outOfStock`` flag is appended as its own ``structured_data``
    block. Raises :class:`NoProductObject` or :class:`OutOfScopePage`."""
    pdp = ounass_product(html)
    em = _Emitter()
    _map_identity(em, pdp)
    title = next((r.value for r in em.readings if r.key == "title"), None)
    title = title if isinstance(title, str) else None
    _map_taxonomy(em, pdp)
    _map_prices(em, pdp)
    _map_size(em, pdp, title)
    _map_merch(em, pdp)
    _map_content(em, pdp, title)
    _map_colour(em, pdp)
    _map_tabs(em, pdp)
    _map_offer(em, pdp)
    em.extend(readings_from_generic(html, locale=locale, url=url))
    for key in ("rating_value", "rating_count"):
        em.not_shown(key, "Ounass product pages show no ratings")
    flag = stock_flag(
        pdp,
        "outOfStock",
        f"{_PDP}.outOfStock",
        "pdp outOfStock flag, inverted; cross-checked with the JSON-LD availability",
        negate=True,
    )
    if flag is not None:
        em.readings.append(flag)
    return em.readings


LOOKED_FOR: frozenset[str] = (
    frozenset(
        {
            "badges",
            "breadcrumb",
            "bullets",
            "category_l1..l4",
            "colour_code",
            "colour_hex",
            "concentration",
            "department",
            "exclusivity",
            "gift_with_purchase",
            "inci_list",
            "installment_provider",
            "lifecycle_class",
            "loyalty_points",
            "product_type",
            "shade_name",
            "size_label",
            "size_unit",
            "size_value",
            "style_id",
            "style_id_source",
        }
    )
    | GENERIC_LOOKED_FOR
)
"""Every registry key ``readings_from_ounass`` can yield."""
