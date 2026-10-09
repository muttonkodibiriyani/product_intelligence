"""Sephora Middle East (sephora.me, Next.js storefront) product-page extractor.

Pure functions over HTML text or over the ``productDetails`` object the page ships inside its
React Server Component payload; nothing fetches. That object carries what the generic readers do
not see: the master id and slug, the variant list with each variant's own price, reduced price,
size or shade label, images and loyalty points, the breadcrumb tree, product nature and market
flags, the ingredient list, merchandising flags and the gift promotions.
:func:`readings_from_sephora` reads those first and lets
:func:`pi_capture.generic.readings_from_generic` fill whatever is left, so each registry key gets
exactly one reading. :func:`readings_from_sephora_details` serves the snapshot records that
already hold the extracted object (and, when given, the page's JSON-LD blocks).

The page shows one variant at a time: the default variant (``c_default_variant_id``) is the one
read, and a page with several says so in the note. RSC references (``"$undefined"``,
``"$83:props:offers"``) are placeholders for data the page did not inline; they are never read
as text, and a reduced price given that way is recorded as not shown.

``swatchImage`` is not proof of a swatch: across the snapshot, a size variant's
``swatchImage`` is usually one of its own gallery pack shots, whatever its file name says
(``470969_swatch.jpg``). A variant has a swatch only when the file is not one of its gallery
images. Review recency is the newest ``datePublished`` among the reviews the JSON-LD lists,
which is the page's own selection, not the full review history.
"""

from __future__ import annotations

import html as html_
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import inf
from typing import Any
from zoneinfo import ZoneInfo

from pi_capture._size import emit_size, read_size
from pi_capture.generic import (
    _PRODUCT_TYPES,
    JsonObject,
    _emit_price,
    _Emitter,
    _minor_units,
    _types,
    _walk,
    find_json_objects,
    parse_jsonld,
    readings_from_generic,
    rsc_text,
)
from pi_capture.generic import (
    LOOKED_FOR as GENERIC_LOOKED_FOR,
)
from pi_capture.model import Reading

__all__ = [
    "LOOKED_FOR",
    "product_details",
    "readings_from_sephora",
    "readings_from_sephora_details",
]

RETAILER = "sephora"
_PD = "rsc.productDetails"
_RSC_REF = re.compile(r"^\$[A-Za-z0-9_:@.-]*$")  # "$undefined", "$83:props:offers"
_TAG = re.compile(r"<[^>]+>")
_NUMBER_UNIT = re.compile(r"\d[\d.,]*\s*[^\d\s]{1,6}")  # "3 oz": a size with an unknown unit
_WS = re.compile(r"\s+")
_EXCLUSIVITY = {"EXCLUSIVE": "exclusive", "SELECTIVE": "selective", "WIDE": "wide"}
_MAX_CATEGORY_LEVELS = 4
_MARKET_ZONE = ZoneInfo("Asia/Dubai")  # a review's date is the market's calendar day


def _present(value: Any) -> bool:
    """False for ``None`` and for RSC references, which stand for data not inlined."""
    return value is not None and not (isinstance(value, str) and _RSC_REF.match(value))


def _text(value: Any) -> str | None:
    if isinstance(value, str) and _present(value) and value.strip():
        return value.strip()
    return None


def _number(value: Any) -> Decimal | None:
    """A JSON number as an exact Decimal; floats (dict path) go through their shortest text."""
    if isinstance(value, bool) or not _present(value):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float | str):
        try:
            d = Decimal(str(value).strip())
        except InvalidOperation:
            return None
        return d if d.is_finite() else None
    return None


def _items(value: Any) -> list[Mapping[str, Any]]:
    return [v for v in value if isinstance(v, Mapping)] if isinstance(value, list) else []


def _plain(markup: str) -> str:
    return _WS.sub(" ", html_.unescape(_TAG.sub(" ", markup.replace("<br", " <br")))).strip()


def _links(images: Any) -> list[str]:
    out: list[str] = []
    for img in _items(images):
        link = _text(img.get("link"))
        if link is not None and link not in out:
            out.append(link)
    return out


def _variant(details: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, int, str | None]:
    """The variant the page shows: the default one, else the first; plus how many there are."""
    variants = _items(details.get("c_variantsInfo"))
    if not variants:
        return None, 0, None
    default = _text(details.get("c_default_variant_id"))
    chosen = next((v for v in variants if _text(v.get("product_id")) == default), variants[0])
    index = variants.index(chosen)
    note = None
    if len(variants) > 1:
        which = "default" if _text(chosen.get("product_id")) == default else "first"
        note = f"{which} variant of {len(variants)} on this page"
    return chosen, index, note


def _map_identity(em: _Emitter, d: Mapping[str, Any], v: Mapping[str, Any] | None, i: int) -> None:
    if (pid := _text(d.get("id"))) is not None:
        em.observed("style_id", pid, pid, f"{_PD}.id", "Sephora master product id")
        em.observed("style_id_source", pid, "captured", f"{_PD}.id")
    if (slug := _text(d.get("c_productSlug"))) is not None:
        em.observed("listing_id", slug, slug, f"{_PD}.c_productSlug")
    if v is not None and (sku := _text(v.get("product_id"))) is not None:
        em.observed("retailer_sku", sku, sku, f"{_PD}.c_variantsInfo[{i}].product_id")


def _map_content(em: _Emitter, d: Mapping[str, Any], v: Mapping[str, Any] | None, i: int) -> None:
    if (name := _text(d.get("name"))) is not None:
        em.observed("title", name, name, f"{_PD}.name")
    brand = d.get("c_brand")
    if isinstance(brand, Mapping) and (bname := _text(brand.get("name"))) is not None:
        em.observed("brand", bname, bname, f"{_PD}.c_brand.name")
    if (desc := _text(d.get("longDescription"))) is not None:
        em.observed("description", desc, _plain(desc), f"{_PD}.longDescription", "tags stripped")
    if (inci := _text(d.get("c_ingredients"))) is not None:
        em.observed("inci_list", inci, _plain(inci), f"{_PD}.c_ingredients")
    links, path = [], f"{_PD}.images[].link"
    if v is not None:
        links, path = _links(v.get("images")), f"{_PD}.c_variantsInfo[{i}].images[].link"
    if not links:
        links, path = _links(d.get("images")), f"{_PD}.images[].link"
    if links:
        em.observed("image_urls", "\n".join(links), links, path)
        em.observed("image_count", str(len(links)), len(links), path)
    videos = d.get("c_youtubeVideos")
    if isinstance(videos, list):
        em.observed("has_video", str(len(videos)), bool(videos), f"{_PD}.c_youtubeVideos")
    _map_rating(em, d)


def _map_rating(em: _Emitter, d: Mapping[str, Any]) -> None:
    count = _number(d.get("c_bvReviewCount"))
    average = _number(d.get("c_bvAverageRating"))
    if count is not None:
        raw = str(d.get("c_bvReviewCount"))
        if count == count.to_integral_value() and count >= 0:
            em.observed("rating_count", raw, int(count), f"{_PD}.c_bvReviewCount", "Bazaarvoice")
        else:
            em.failed("rating_count", raw, f"{_PD}.c_bvReviewCount", "not a whole number")
    if count is not None and count == 0:
        em.not_shown("rating_value", "no reviews yet; a zero review count is not a rating")
    elif average is not None:
        raw = str(d.get("c_bvAverageRating"))
        em.observed("rating_value", raw, average, f"{_PD}.c_bvAverageRating", "Bazaarvoice")


def _map_classification(em: _Emitter, d: Mapping[str, Any]) -> None:
    crumbs = [n for c in _items(d.get("c_breadcrumbs")) if (n := _text(c.get("name"))) is not None]
    if crumbs:
        raw = " > ".join(crumbs)
        em.observed("breadcrumb", raw, crumbs, f"{_PD}.c_breadcrumbs[].name")
        note = None
        if len(crumbs) > _MAX_CATEGORY_LEVELS:
            note = f"{len(crumbs)} levels on the page; the first {_MAX_CATEGORY_LEVELS} kept"
        levels = crumbs[:_MAX_CATEGORY_LEVELS]
        em.observed("category_l1..l4", raw, levels, f"{_PD}.c_breadcrumbs[].name", note)
    if (nature := _text(d.get("c_productNature"))) is not None:
        em.observed("product_type", nature, nature.lower(), f"{_PD}.c_productNature")
    if (marche := _text(d.get("c_productMarche"))) is not None:
        path = f"{_PD}.c_productMarche"
        if (value := _EXCLUSIVITY.get(marche.upper())) is not None:
            em.observed("exclusivity", marche, value, path)
        else:
            em.failed("exclusivity", marche, path, "outside exclusive|selective|wide")


def _map_money(
    em: _Emitter, d: Mapping[str, Any], v: Mapping[str, Any] | None, i: int, note: str | None
) -> None:
    currency = _text(d.get("currency"))
    source: Mapping[str, Any] = v if v is not None else d
    base = f"{_PD}.c_variantsInfo[{i}]" if v is not None else _PD
    price = _number(source.get("c_price"))
    raw_sale = source.get("c_salesPrice")
    sale = _number(raw_sale)
    if isinstance(raw_sale, str) and _RSC_REF.match(raw_sale) and raw_sale != "$undefined":
        # a reference to data not inlined: the variant may be on sale, so neither the price paid
        # nor "no reduced price" is known, and the JSON-LD price must not stand in for it
        em.withhold("price_minor")
        em.withhold("regular_price_minor")
    elif sale is not None:
        _emit_price(em, "price_minor", str(sale), currency, f"{base}.c_salesPrice", note)
        _map_regular(em, price, sale, currency, f"{base}.c_price")
    elif price is not None:
        _emit_price(em, "price_minor", str(price), currency, f"{base}.c_price", note)
        em.not_shown(
            "regular_price_minor", "no reduced price; the price shown is the regular price"
        )
    elif _present(source.get("c_price")):
        em.failed("price_minor", str(source.get("c_price")), f"{base}.c_price", "not a number")
    points = _number(source.get("c_loyaltyPointPotentiallyGained"))
    if points is not None and points == points.to_integral_value():
        raw = str(source.get("c_loyaltyPointPotentiallyGained"))
        em.observed("loyalty_points", raw, int(points), f"{base}.c_loyaltyPointPotentiallyGained")


def _map_regular(
    em: _Emitter, price: Decimal | None, sale: Decimal, currency: str | None, path: str
) -> None:
    if price is None:
        em.not_shown("regular_price_minor", "reduced price shown without a regular price beside it")
        return
    code = currency.upper() if currency and len(currency) == 3 else None
    raw = f"{price} {currency}" if currency else str(price)
    sale_minor, _reason, _note = _minor_units(str(sale), currency)
    if price <= sale:
        reason = f"regular price not above the reduced price ({sale_minor} minor units)"
        em.failed("regular_price_minor", raw, path, reason, currency=code)
        return
    _emit_price(em, "regular_price_minor", str(price), currency, path)


def _map_variant_label(em: _Emitter, v: Mapping[str, Any] | None, i: int) -> None:
    if v is None:
        return
    label = _text(v.get("c_variation_attribute_name"))
    if label is None:
        return
    path = f"{_PD}.c_variantsInfo[{i}].c_variation_attribute_name"
    if _is_size(v, label):
        emit_size(em, label, path)
    else:
        em.observed("shade_name", label, label, path)


def _is_size(v: Mapping[str, Any], label: str) -> bool:
    """The page's own template flag decides; without one, a number followed by one short unit
    word is a size and anything else ("02 Rose Nude") is a shade."""
    if v.get("c_isSizeVariationTemplate") is True:
        return True
    if v.get("c_isShadeVariationTemplate") is True:
        return False
    return read_size(label).unit is not None or _NUMBER_UNIT.fullmatch(label) is not None


def _map_merch(em: _Emitter, d: Mapping[str, Any]) -> None:
    flags = [t for f in _items(d.get("c_productFlags")) if (t := _text(f.get("text1"))) is not None]
    if flags:
        em.observed("badges", ", ".join(flags), flags, f"{_PD}.c_productFlags[].text1")
    gifts: list[str] = []
    for p in _items(d.get("c_product_promotions")):
        if p.get("showBannerPDP") is False:
            continue
        parts = [t for k in ("promotionTitle", "promotionDescription") if (t := _text(p.get(k)))]
        if parts:
            gifts.append(": ".join(parts))
    if gifts:
        raw = "\n".join(gifts)
        em.observed("gift_with_purchase", raw, raw, f"{_PD}.c_product_promotions[]")
    elif isinstance(d.get("c_product_promotions"), list):
        em.not_shown("gift_with_purchase", "promotion list present and empty")
    related = (
        [s for s in d.get("recommendedProductIds", []) if isinstance(s, str) and s]
        if isinstance(d.get("recommendedProductIds"), list)
        else []
    )
    if related:
        em.observed("related_products", ", ".join(related), related, f"{_PD}.recommendedProductIds")


def _file_name(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rsplit("/", 1)[-1]


def _map_swatch(em: _Emitter, v: Mapping[str, Any] | None, i: int) -> None:
    if v is None:
        return
    swatch = _text(v.get("swatchImage"))
    if swatch is None or not _file_name(swatch):
        em.not_shown("has_swatch_image", "the shown variant has no swatch image")
        return
    gallery = {name for link in _links(v.get("images")) if (name := _file_name(link))}
    if not gallery:  # nothing to compare with: a pack shot and a chip look the same
        note = "gallery not inlined: cannot tell a swatch from the variant's own pack shot"
        em.not_shown("has_swatch_image", note)
        return
    path = f"{_PD}.c_variantsInfo[{i}].swatchImage"
    if _file_name(swatch) in gallery:
        note = "swatchImage repeats one of the variant's gallery images (a pack shot), not a swatch"
        em.observed("has_swatch_image", swatch, False, path, note)
    else:
        note = "a separate swatch file, not one of the variant's gallery images"
        em.observed("has_swatch_image", swatch, True, path, note)


def _review_day(raw: str) -> tuple[date, datetime | None] | None:
    """The Asia/Dubai day of one datePublished, with its moment when it has one. A bare date is
    the day as published; a time with no zone has no market day and reads as ``None``."""
    try:
        if len(raw) == len("2026-09-11"):
            return date.fromisoformat(raw), None
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(_MARKET_ZONE).date(), moment


def _map_reviews(em: _Emitter, blocks: Sequence[JsonObject]) -> None:
    """``review_recency``: the newest review the structured data lists, as an Asia/Dubai date.
    The first product node that lists a dated review is read; one without reviews is passed."""
    seen_product = False
    for path, node in _walk(blocks):
        if not _types(node) & _PRODUCT_TYPES:
            continue
        seen_product = True
        reviews = node.get("review")
        listed = reviews if isinstance(reviews, list) else [reviews]
        raws = [
            t for r in listed if isinstance(r, Mapping) and (t := _text(r.get("datePublished")))
        ]
        if not raws:
            continue
        days = [(*d, raw) for raw in raws if (d := _review_day(raw)) is not None]
        rpath = f"{path}.review[].datePublished"
        if not days:
            note = "no datePublished with a time zone or as a bare date"
            em.failed("review_recency", "\n".join(raws), rpath, note)
            return
        # the latest day; within it a timed review is later than a bare date
        day, _, raw = max(days, key=lambda d: (d[0], d[1].timestamp() if d[1] else -inf))
        note = f"newest of {len(raws)} reviews the page lists; Asia/Dubai date"
        if len(days) < len(raws):
            note += f"; {len(raws) - len(days)} unreadable date(s) skipped"
        em.observed("review_recency", raw, day.isoformat(), rpath, note)
        return
    if seen_product:
        em.not_shown("review_recency", "no dated review listed in the structured data")
    else:
        em.not_shown("review_recency", "no product in the structured data")


def _sephora_readings(details: Mapping[str, Any]) -> _Emitter:
    em = _Emitter()
    v, i, note = _variant(details)
    _map_identity(em, details, v, i)
    _map_content(em, details, v, i)
    _map_classification(em, details)
    _map_money(em, details, v, i, note)
    _map_variant_label(em, v, i)
    _map_swatch(em, v, i)
    _map_merch(em, details)
    return em


def product_details(html: str) -> JsonObject | None:
    """The ``productDetails`` object from the page's RSC payload, or ``None`` without one."""
    for obj in find_json_objects(rsc_text(html), "productDetails"):
        details = obj.get("productDetails")
        if isinstance(details, dict) and "id" in details:
            return details
    return None


_SEPHORA_KEYS = frozenset(
    {
        "badges",
        "brand",
        "breadcrumb",
        "category_l1..l4",
        "description",
        "exclusivity",
        "gift_with_purchase",
        "has_swatch_image",
        "has_video",
        "image_count",
        "image_urls",
        "inci_list",
        "listing_id",
        "loyalty_points",
        "price_minor",
        "product_type",
        "rating_count",
        "rating_value",
        "regular_price_minor",
        "related_products",
        "retailer_sku",
        "review_recency",
        "shade_name",
        "size_label",
        "size_unit",
        "size_value",
        "style_id",
        "style_id_source",
        "title",
    }
)
LOOKED_FOR: frozenset[str] = _SEPHORA_KEYS | GENERIC_LOOKED_FOR
"""Every registry key ``readings_from_sephora`` can yield; a capture built from it passes this as
``ProductCapture.looked_for`` so the coverage report separates "not shown" from "never read"."""


def readings_from_sephora_details(
    details: Mapping[str, Any], *, jsonld: Sequence[JsonObject] | None = None
) -> list[Reading]:
    """Readings from an already extracted ``productDetails`` object (no page, no generic pass).

    ``jsonld`` is the page's saved JSON-LD blocks; without them ``review_recency`` is not read.
    """
    em = _sephora_readings(details)
    if jsonld is not None:
        _map_reviews(em, jsonld)
    return em.readings


def readings_from_sephora(html: str, *, locale: str, url: str | None = None) -> list[Reading]:
    """Sephora readings from the RSC payload first, then the generic extractors fill the rest."""
    details = product_details(html)
    em = _Emitter() if details is None else _sephora_readings(details)
    _map_reviews(em, parse_jsonld(html)[0])
    em.extend(readings_from_generic(html, locale=locale, url=url))
    return em.readings
