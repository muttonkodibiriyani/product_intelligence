"""Parsers for ulta.ae's own first-party product JSON, as captured during one page load.

The ulta.ae storefront (Alshaya, Adobe Commerce catalog service) loads its product data as
GraphQL responses while the page renders. The runner records those response bodies in the same
page load; nothing here makes or implies an extra request (ADR-0006 Amendment 2, owner rule:
no extra renders or requests). Three payload shapes are handled:

* PDP: ``data.products`` (page locale), plus ``data.products_en`` on Arabic pages, holding one
  ``ComplexProductView`` (with ``variants``) or ``SimpleProductView``.
* PDP variant refinement: ``data.refineProduct`` (one ``SimpleProductView``).
* Category listing (PLP): ``data.getProductListingWithCategory.results[].hits``.

Semantics (DQ-02, missing is data): a price that is absent, zero or a free-gift placeholder is
``None`` with a reason, never 0. Stock comes from ``inStock`` on the variant as served.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = [
    "CatalogError",
    "PlpHit",
    "UltaProduct",
    "UltaVariant",
    "parse_pdp_payload",
    "parse_plp_payload",
]

#: A placeholder price the storefront uses for free gifts (GWP) and samples, e.g. 0.0001.
_GIFT_PRICE_CEILING = Decimal("0.01")
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
#: Values the storefront uses for "no value" (EN and AR "no size").
_EMPTY = frozenset({"NOSIZE", "NULL", "NONE", "بدون مقاس"})


class CatalogError(ValueError):
    """The payload is not a recognised ulta.ae catalog response."""


@dataclass(frozen=True, slots=True)
class Price:
    """One price as served; ``amount`` is None with a ``reason`` when there is no real price."""

    amount: Decimal | None
    reason: str | None = None
    currency: str = "AED"


@dataclass(frozen=True, slots=True)
class UltaVariant:
    """One sellable SKU (a shade or size of a configurable product, or a simple product)."""

    sku: str
    name: str
    in_stock: bool | None
    regular: Price
    final: Price
    shade: str | None
    shade_description: str | None
    size: str | None
    size_uom: str | None
    barcode: str | None
    images: tuple[str, ...]
    labels: tuple[str, ...]
    promotions: tuple[str, ...]
    member_price: Price
    free_gift: bool
    is_sale: bool
    url_key: str | None

    @property
    def promotional(self) -> bool:
        """The final price is a real price below the regular price."""
        r, f = self.regular.amount, self.final.amount
        return r is not None and f is not None and f < r

    @property
    def current(self) -> Price:
        """The price a shopper pays now: final when real, else regular, else a reason."""
        if self.final.amount is not None:
            return self.final
        if self.regular.amount is not None and self.final.reason == "not_published":
            return self.regular
        return self.final


@dataclass(frozen=True, slots=True)
class UltaProduct:
    """One product page's product, in one locale."""

    locale: str
    sku: str
    name: str
    url_key: str
    brand: str | None
    kind: str
    in_stock: bool | None
    description: str | None
    category_path: str | None
    ulta_type: str | None
    variants: tuple[UltaVariant, ...]
    raw_attributes: dict[str, str] = field(repr=False, compare=False)
    #: Locale-independent brand slug from the page's ``/shop-brands/<slug>`` link (DOM path).
    brand_key: str | None = None
    rating_average: Decimal | None = None
    rating_count: int | None = None


@dataclass(frozen=True, slots=True)
class PlpHit:
    """One product tile from a category listing response (first page only: robots ``/*?``)."""

    sku: str
    url_path: str
    locale: str
    title: str | None
    brand: str | None
    final_price: Price
    original_price: Price
    rating_average: Decimal | None
    rating_count: int | None
    sizes: tuple[str, ...]


# ---------------------------------------------------------------------------- helpers


def _loads(document: str | bytes) -> Any:
    try:
        return json.loads(document, parse_float=Decimal)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        raise CatalogError("payload is not JSON") from exc


def _attrs(item: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for attr in item.get("attributes") or []:
        if isinstance(attr, dict) and isinstance(attr.get("name"), str):
            value = attr.get("value")
            out[attr["name"]] = "" if value is None else str(value)
    return out


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _price(value: Any, *, gift: bool) -> Price:
    amount = _decimal(value)
    if amount is None:
        return Price(None, "not_published")
    if gift or amount < _GIFT_PRICE_CEILING:
        return Price(None, "not_applicable")  # free gift / sample placeholder, not a price
    return Price(amount)


def _money(node: Any, slot: str) -> Any:
    """``price.<slot>.amount.value`` from a catalog-service price object."""
    try:
        return node[slot]["amount"]["value"]
    except (KeyError, TypeError):
        return None


def _text(fragment: str | None) -> str | None:
    if not fragment:
        return None
    text = html.unescape(html.unescape(_TAG.sub("\n", fragment)))
    lines = [_SPACE.sub(" ", line).strip() for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return joined or None


def _json_attr(attrs: dict[str, str], name: str) -> Any:
    raw = attrs.get(name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _names(value: Any, key: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v[key]) for v in value if isinstance(v, dict) and v.get(key))


def _is_gift(attrs: dict[str, str]) -> bool:
    return attrs.get("is_free_sample", "").lower() == "yes"


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return None if not value or value.upper() in _EMPTY else value


def _variant(item: dict[str, Any], parent_price: Any = None) -> UltaVariant:
    attrs = _attrs(item)
    gift = _is_gift(attrs)
    price = item.get("price") or parent_price or {}
    regular = _price(_money(price, "regular"), gift=gift)
    final = _price(_money(price, "final"), gift=gift)
    # A placeholder price (e.g. 0.0001 / 0) marks a free gift or sample, never a real price.
    gift = gift or "not_applicable" in (regular.reason, final.reason)
    member = _decimal(attrs.get("member_price"))
    return UltaVariant(
        sku=str(item["sku"]),
        name=str(item.get("name") or ""),
        in_stock=item.get("inStock") if isinstance(item.get("inStock"), bool) else None,
        regular=regular,
        final=final,
        shade=_clean(attrs.get("color")),
        shade_description=_clean(attrs.get("shade_description")),
        size=_clean(attrs.get("size")),
        size_uom=_clean(attrs.get("size_uom")) if _clean(attrs.get("size")) else None,
        barcode=_clean(attrs.get("aims_barcode")),
        images=tuple(
            str(i["url"]) for i in item.get("images") or [] if isinstance(i, dict) and i.get("url")
        ),
        labels=_names(_json_attr(attrs, "product_labels"), "name"),
        promotions=_names(_json_attr(attrs, "promotions"), "label")
        or _names(_json_attr(attrs, "promotions"), "name"),
        member_price=Price(member)
        if member is not None and member > 0
        else Price(None, "not_published"),
        free_gift=gift,
        is_sale=attrs.get("is_sale") == "1",
        url_key=_clean(item.get("urlKey")) or _clean(attrs.get("end_user_url")),
    )


def _product(item: dict[str, Any], locale: str) -> UltaProduct:
    if not isinstance(item, dict) or "sku" not in item:
        raise CatalogError("product entry has no sku")
    attrs = _attrs(item)
    gtm = _json_attr(attrs, "gtm_attributes")
    kind = str(item.get("__typename") or "")
    nested = (item.get("variants") or {}).get("variants") or []
    if kind == "ComplexProductView":
        parent_price = (item.get("priceRange") or {}).get("minimum")
        variants = tuple(
            _variant(v["product"], parent_price)
            for v in nested
            if isinstance(v, dict) and isinstance(v.get("product"), dict)
        )
    elif kind == "SimpleProductView":
        variants = (_variant(item),)
    else:
        raise CatalogError(f"unsupported product type {kind!r}")
    return UltaProduct(
        locale=locale,
        sku=str(item["sku"]),
        name=str(item.get("name") or ""),
        url_key=str(item.get("urlKey") or ""),
        brand=_clean(attrs.get("brand")),
        kind=kind,
        in_stock=item.get("inStock") if isinstance(item.get("inStock"), bool) else None,
        description=_text(item.get("description")),
        category_path=(gtm.get("category") if isinstance(gtm, dict) else None) or None,
        ulta_type=_clean(attrs.get("ulta_type")),
        variants=variants,
        raw_attributes=attrs,
    )


# ---------------------------------------------------------------------------- public


def parse_pdp_payload(document: str | bytes, page_locale: str) -> list[UltaProduct]:
    """Products in one captured PDP response. ``page_locale`` is ``en`` or ``ar``.

    On an Arabic page, ``products`` is Arabic and ``products_en`` is the same product in English.
    """
    if page_locale not in {"en", "ar"}:
        raise CatalogError(f"unknown locale {page_locale!r}")
    payload = _loads(document)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise CatalogError("no data object")
    out: list[UltaProduct] = []
    for key, locale in (("products", page_locale), ("products_en", "en")):
        items = data.get(key)
        if isinstance(items, list):
            out.extend(_product(item, locale) for item in items)
    refined = data.get("refineProduct")
    if isinstance(refined, dict):
        out.append(_product(refined, page_locale))
    if not out and not any(k in data for k in ("products", "products_en", "refineProduct")):
        raise CatalogError("not a product payload")
    return out


def _localised(value: Any, locale: str) -> Any:
    if isinstance(value, dict):
        return value.get(locale)
    return value


def parse_plp_payload(document: str | bytes, page_locale: str) -> list[PlpHit]:
    """Product tiles from one captured category-listing response."""
    payload = _loads(document)
    try:
        results = payload["data"]["getProductListingWithCategory"]["results"]
    except (KeyError, TypeError) as exc:
        raise CatalogError("not a category listing payload") from exc
    hits: list[PlpHit] = []
    for result in results or []:
        for hit in (result or {}).get("hits") or []:
            if not isinstance(hit, dict) or not hit.get("sku"):
                continue
            url = _localised(hit.get("url"), page_locale)
            if not isinstance(url, str) or not url:
                continue
            count = hit.get("attr_bv_total_review_count")
            avg = _decimal(_localised(hit.get("attr_bv_average_overall_rating"), page_locale))
            count_int = (
                int(count) if isinstance(count, (int, str)) and str(count).isdigit() else None
            )
            rated = count_int is not None and count_int > 0 and avg is not None and avg > 0
            sizes = _localised(hit.get("attr_size"), page_locale)
            hits.append(
                PlpHit(
                    sku=str(hit["sku"]),
                    url_path=url,
                    locale=page_locale,
                    title=_localised(hit.get("title"), page_locale),
                    brand=_localised(hit.get("attr_product_brand"), page_locale),
                    final_price=_price(_localised(hit.get("final_price"), page_locale), gift=False),
                    original_price=_price(
                        _localised(hit.get("original_price"), page_locale), gift=False
                    ),
                    rating_average=avg if rated else None,
                    rating_count=count_int if rated else None,
                    sizes=tuple(str(s) for s in sizes) if isinstance(sizes, list) else (),
                )
            )
    return hits
