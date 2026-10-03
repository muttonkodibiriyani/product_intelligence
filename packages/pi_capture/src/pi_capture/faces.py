"""Faces (faces.ae, Salesforce Commerce Cloud storefront) product-page extractor.

Pure functions over HTML text; nothing fetches. Faces publishes the facts a price-intelligence
row needs in three places that the generic extractors do not read: the ``view_item`` push on
``dataLayer`` (master id, brand, EAN, categories, size, shade slug), SFCC data attributes on the
product container (``data-pid``, ``data-ean``, availability) and rendered fragments (shade
swatches, MUSE loyalty points, tabby/tamara instalments, badges, free-gift button, gallery, VAT
line, accordion description). :func:`readings_from_faces` reads those first and lets
:func:`pi_capture.generic.readings_from_generic` fill whatever is left, so each registry key
gets exactly one reading.

Ratings and related products are rendered client-side (Bazaarvoice, Constructor) and are
recorded as ``not_shown`` so the gap is explicit rather than silent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from pi_capture.generic import (
    LOOKED_FOR as GENERIC_LOOKED_FOR,
)
from pi_capture.generic import (
    JsonObject,
    _emit_gtin,
    _emit_price,
    _Emitter,
    _minor_units,
    find_json_objects,
    microdata_items,
    readings_from_generic,
)
from pi_capture.model import Reading

__all__ = ["LOOKED_FOR", "FacesFacts", "faces_facts", "readings_from_faces"]

RETAILER = "faces"
_DL = "dataLayer.view_item.items[0]"
_SKIP_TAGS = frozenset({"script", "style", "template", "noscript"})
_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_SIZE = re.compile(r"^(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:[.,]\d+)?)\s*(?P<unit>[^\d\s].*?)$")
_THOUSANDS = re.compile(r"^[1-9]\d{0,2}(?:,\d{3})+$")  # 1,000 is a thousand; 0,750 is not
_AMBIGUOUS_THOUSANDS_UNITS = frozenset({"l", "kg"})  # 1,500 l may be 1.5 l or 1500 l
_SIZE_UNITS = {
    "ml": "ml",
    "g": "g",
    "gm": "g",
    "gr": "g",
    "l": "l",
    "kg": "kg",
    "pcs": "count",
    "pc": "count",
    "pieces": "count",
    "piece": "count",
    "count": "count",
    "مل": "ml",
    "جم": "g",
    "غ": "g",
    "لتر": "l",
    "كجم": "kg",
}
_DEPARTMENTS = {
    "WOMEN": "women",
    "WOMAN": "women",
    "FEMALE": "women",
    "MEN": "men",
    "MAN": "men",
    "MALE": "men",
    "KIDS": "kids",
    "KID": "kids",
    "CHILDREN": "kids",
    "BABY": "baby",
    "UNISEX": "unisex",
}
_CONCENTRATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:eau de parfum|edp)\b|او دو بارفان|أو دو بارفان", re.I), "edp"),
    (re.compile(r"\b(?:eau de toilette|edt)\b|او دو تواليت|أو دو تواليت", re.I), "edt"),
    (re.compile(r"\b(?:eau de cologne|edc|cologne)\b|كولونيا", re.I), "cologne"),
    (re.compile(r"\b(?:extrait(?: de parfum)?|parfum|perfume extract)\b|عطر مركز", re.I), "parfum"),
)
_SPF = re.compile(r"\bSPF\s*(\d{1,3})\b", re.I)
_VAT = re.compile(
    r"(?:incl(?:uding|\.)?\s*\d{1,2}\s*%\s*VAT|VAT\s+incl(?:uded)?"
    r"|شامل[^()]{0,30}ضريبة القيمة المضافة[^()]{0,20})",
    re.I,
)


@dataclass(slots=True)
class _El:
    tag: str
    attrs: dict[str, str]
    classes: frozenset[str]
    ancestors: frozenset[str]
    ancestor_ids: frozenset[str]
    text: str = ""
    _parts: list[str] = field(default_factory=list, repr=False)

    def has(self, *classes: str) -> bool:
        return all(c in self.classes for c in classes)

    def under(self, cls: str) -> bool:
        return cls in self.ancestors


class _Scan(HTMLParser):
    """Flat list of elements with their classes, ancestor classes and collapsed inner text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[_El] = []
        self._open: list[_El] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        a = {k: (v if v is not None else "") for k, v in attrs}
        classes = frozenset(a.get("class", "").split())
        ancestors: set[str] = set()
        ids: set[str] = set()
        for el in self._open:
            ancestors |= el.classes
            if "id" in el.attrs:
                ids.add(el.attrs["id"])
        el = _El(tag, a, classes, frozenset(ancestors), frozenset(ids))
        self.elements.append(el)
        if tag in _VOID:
            return
        self._open.append(el)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and tag not in _SKIP_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i].tag == tag:
                for el in self._open[i:]:
                    el.text = _WS.sub(" ", " ".join(el._parts)).strip()
                del self._open[i:]
                return

    def handle_data(self, data: str) -> None:
        if self._skip or not data.strip():
            return
        for el in self._open:
            el._parts.append(data)

    def close(self) -> None:
        super().close()
        for el in self._open:
            el.text = _WS.sub(" ", " ".join(el._parts)).strip()
        self._open.clear()


def _scan(html: str) -> list[_El]:
    s = _Scan()
    s.feed(html)
    s.close()
    return s.elements


def _view_item(html: str) -> JsonObject | None:
    """First ``view_item`` item on ``dataLayer``; the push-level currency fills a missing one."""
    for obj in find_json_objects(html, "ecommerce"):
        if obj.get("event") != "view_item" or not isinstance(obj.get("ecommerce"), dict):
            continue
        items = obj["ecommerce"].get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            item: JsonObject = dict(items[0])
            item.setdefault("currency", obj["ecommerce"].get("currency"))
            return item
    return None


def _str(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int | Decimal) and not isinstance(value, bool):
        return str(value)
    return None


def _first(els: list[_El], *classes: str, tag: str | None = None) -> _El | None:
    return next((e for e in els if e.has(*classes) and (tag is None or e.tag == tag)), None)


def _all(els: list[_El], *classes: str, tag: str | None = None) -> list[_El]:
    return [e for e in els if e.has(*classes) and (tag is None or e.tag == tag)]


# ------------------------------------------------------------------------------- facts


@dataclass(frozen=True, slots=True)
class FacesFacts:
    """Published availability facts that have no registry key of their own."""

    available: bool | None
    ready_to_order: bool | None
    in_stock_flag: bool | None
    out_of_stock_shown: bool | None


def _bool_attr(el: _El | None, name: str) -> bool | None:
    if el is None or name not in el.attrs:
        return None
    value = el.attrs[name].strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    return None


def faces_facts(html: str) -> FacesFacts:
    els = _scan(html)
    item = _view_item(html)
    availability = _first(els, "js-availability-container")
    oos = _first(els, "js-out-of-stock-message")
    flag = item.get("item_in_stock") if item else None
    return FacesFacts(
        available=_bool_attr(availability, "data-available"),
        ready_to_order=_bool_attr(availability, "data-ready-to-order"),
        in_stock_flag=flag if isinstance(flag, bool) else None,
        out_of_stock_shown=None if oos is None else not oos.has("d-none"),
    )


# ---------------------------------------------------------------------------- readings


def _map_identity(em: _Emitter, els: list[_El], item: Mapping[str, Any] | None) -> None:
    container = _first(els, "js-product-details")
    pid = container.attrs.get("data-pid", "").strip() if container else ""
    ean = container.attrs.get("data-ean", "").strip() if container else ""
    if item is not None:
        if (sid := _str(item.get("item_id"))) is not None:
            em.observed("style_id", sid, sid, f"{_DL}.item_id", "SFCC master product id")
            em.observed("style_id_source", sid, "captured", f"{_DL}.item_id")
        if (brand := _str(item.get("item_brand"))) is not None:
            em.observed("brand", brand, brand, f"{_DL}.item_brand")
        if (name := _str(item.get("item_name"))) is not None:
            em.observed("title", name, name, f"{_DL}.item_name")
    if pid:
        em.observed("retailer_sku", pid, pid, "div.js-product-details[data-pid]")
    if ean:
        _emit_gtin(em, ean, "div.js-product-details[data-ean]")
    elif item is not None:
        variant = _str(item.get("item_variant"))
        if variant is not None and variant != pid and variant.isdigit() and 8 <= len(variant) <= 14:
            _emit_gtin(em, variant, f"{_DL}.item_variant")
    if not em.has("brand") and (b := _first(els, "product-brand")) and b.text:
        em.observed("brand", b.text, b.text, "div.product-brand")
    if not em.has("title") and (n := _first(els, "js-name")) and n.text:
        em.observed("title", n.text, n.text, "span.js-name")


def _map_taxonomy(em: _Emitter, els: list[_El], item: Mapping[str, Any] | None) -> None:
    if item is not None:
        gender = _str(item.get("item_gender"))
        if gender is not None:
            mapped = _DEPARTMENTS.get(gender.upper())
            if mapped is None:
                em.failed("department", gender, f"{_DL}.item_gender", "outside the department enum")
            else:
                em.observed("department", gender, mapped, f"{_DL}.item_gender")
        levels = [
            c
            for k in ("item_category", "item_category2", "item_category3", "item_category4")
            if (c := _str(item.get(k))) is not None
        ]
        if levels:
            raw = " > ".join(levels)
            em.observed("category_l1..l4", raw, levels, f"{_DL}.item_category..4")
        if (colour := _str(item.get("item_color"))) is not None:
            em.observed("colour_code", colour, colour, f"{_DL}.item_color", "SFCC colour slug")
    ptype = _first(els, "product-type", tag="span")
    if ptype is not None and ptype.text:
        em.observed("product_type", ptype.text, ptype.text, "span.product-type")
    elif item is not None and (c3 := _str(item.get("item_category3"))) is not None:
        em.observed("product_type", c3, c3, f"{_DL}.item_category3")


def _map_breadcrumb(em: _Emitter, html_items: list[JsonObject]) -> None:
    for item in html_items:
        if not str(item.get("@type") or "").endswith("BreadcrumbList"):
            continue
        elements = [e for e in item.get("itemListElement", []) if isinstance(e, dict)]
        pairs: list[tuple[int, str]] = []
        for i, e in enumerate(elements):
            names = [n for n in e.get("name", []) if isinstance(n, str) and n.strip()]
            if not names:
                nested = [n for n in e.get("item", []) if isinstance(n, dict)]
                names = [n for d in nested for n in d.get("name", []) if isinstance(n, str)]
            positions = [p for p in e.get("position", []) if isinstance(p, str) and p.isdigit()]
            if names:
                pairs.append((int(positions[0]) if positions else i, names[0].strip()))
        if pairs:
            crumbs = [n for _, n in sorted(pairs, key=lambda p: p[0])]
            em.observed("breadcrumb", " > ".join(crumbs), crumbs, "microdata.BreadcrumbList")
        return


def _map_shade(em: _Emitter, els: list[_El], item: Mapping[str, Any] | None) -> None:
    swatches = _all(els, "swatch-btn", tag="button")
    if swatches:
        selected = next((s for s in swatches if s.has("selected")), None)
        if selected is not None and (title := selected.attrs.get("title", "").strip()):
            em.observed("shade_name", title, title, "button.swatch-btn.selected[title]")
        values = _all(els, "swatch-value", tag="span")
        with_image = [v for v in values if "background-image" in v.attrs.get("style", "")]
        em.observed(
            "has_swatch_image",
            f"{len(with_image)} of {len(values)} swatches carry an image",
            bool(with_image),
            "span.swatch-value[style*=background-image]",
        )
    if not em.has("shade_name") and item is not None:
        slug = _str(item.get("item_color"))
        if slug is not None:
            em.observed(
                "shade_name",
                slug,
                slug.replace("_", " "),
                f"{_DL}.item_color",
                "display name not rendered; slug with underscores replaced",
            )


def _map_size(em: _Emitter, els: list[_El], item: Mapping[str, Any] | None) -> None:
    label: str | None = None
    path = ""
    if item is not None and (s := _str(item.get("item_size"))) is not None:
        label, path = s, f"{_DL}.item_size"
    elif (sel := _first(els, "js-selected-value")) is not None and sel.text:
        label, path = sel.text.strip("()").strip(), "span.js-selected-value"
    if label is None:
        return
    em.observed("size_label", label, label, path)
    m = _SIZE.match(label)
    if m is None:
        em.failed("size_value", label, path, "no leading number")
        em.failed("size_unit", label, path, "no unit after a number")
        return
    num = m.group("num")
    note: str | None = None
    if _THOUSANDS.match(num):
        num, note = num.replace(",", ""), "comma read as a thousands separator"
    else:
        num = num.replace(",", ".")
    try:
        value = Decimal(num)
    except InvalidOperation:  # pragma: no cover - regex guarantees a number
        em.failed("size_value", label, path, "not a number")
        return
    unit = _SIZE_UNITS.get(m.group("unit").strip().lower().rstrip("."))
    if unit is None:
        em.failed("size_unit", label, path, f"unit {m.group('unit')!r} outside ml|g|l|kg|count")
        em.failed("size_value", label, path, "unit not normalised, value kept with the label")
        return
    if note is not None and unit in _AMBIGUOUS_THOUSANDS_UNITS:
        em.failed(
            "size_value",
            label,
            path,
            f"comma ambiguous with {unit}: {m.group('num')} may be a decimal or a thousand",
        )
        em.observed("size_unit", label, unit, path)
        return
    em.observed("size_value", label, value, path, note)
    em.observed("size_unit", label, unit, path)


def _currency(els: list[_El], item: Mapping[str, Any] | None) -> str | None:
    cur = _first(els, "js-gtm-site-currencycode", tag="input")
    if cur is not None and cur.attrs.get("value", "").strip():
        return cur.attrs["value"].strip()
    if item is not None:
        return _str(item.get("currency"))
    return None


_REGULAR_PATH = ".js-main-price span.strike-through span.value[content]"


def _map_prices(em: _Emitter, els: list[_El], currency: str | None) -> None:
    values = _all(els, "value", tag="span")
    main = [v for v in values if v.under("js-main-price")]  # the product's own price block
    sale = next((v for v in main if not v.under("strike-through") and v.attrs.get("content")), None)
    sale_note: str | None = None
    if sale is None and not main:
        sale = next(
            (v for v in values if v.attrs.get("content") and not v.under("strike-through")), None
        )
        sale_note = "no js-main-price block; first priced value on the page"
    sale_minor: int | None = None
    if sale is not None:
        _emit_price(
            em, "price_minor", sale.attrs["content"], currency, "span.value[content]", sale_note
        )
        sale_minor, _reason, _note = _minor_units(sale.attrs["content"], currency)
    # a struck price counts only inside the product's own price block, and only above the sale
    # price: a struck tile elsewhere on the page is another product's, and regular <= sale is
    # not a regular price
    struck = next((v for v in main if v.under("strike-through") and v.attrs.get("content")), None)
    if struck is not None:
        _map_regular(em, struck.attrs["content"], currency, sale_minor)
    vat = next(
        (
            e
            for e in els
            if e.tag in {"span", "div", "p", "small"}
            and _VAT.search(e.text or "")
            and len(e.text) < 120
        ),
        None,
    )
    if vat is not None and (m := _VAT.search(vat.text)):
        em.observed("vat_statement", vat.text, m.group(0).strip(), _el_path(vat))


def _map_regular(em: _Emitter, amount: str, currency: str | None, sale_minor: int | None) -> None:
    minor, _reason, _note = _minor_units(amount, currency)
    if minor is None:
        _emit_price(em, "regular_price_minor", amount, currency, _REGULAR_PATH)  # parse_failed
        return
    raw = f"{amount} {currency}" if currency else amount
    code = currency.strip().upper() if currency and len(currency.strip()) == 3 else None
    if sale_minor is None:
        em.failed(
            "regular_price_minor",
            raw,
            _REGULAR_PATH,
            "struck price with no readable sale price beside it",
            currency=code,
        )
        return
    if minor <= sale_minor:
        em.failed(
            "regular_price_minor",
            raw,
            _REGULAR_PATH,
            f"struck price not above the sale price ({sale_minor} minor units); "
            "not a regular price",
            currency=code,
        )
        return
    _emit_price(em, "regular_price_minor", amount, currency, _REGULAR_PATH)


def _el_path(el: _El) -> str:
    """``tag.class.class`` of the element itself, so the recorded path is where the text was."""
    return el.tag + "".join(f".{c}" for c in sorted(el.classes))


def _map_offer_extras(em: _Emitter, els: list[_El], currency: str | None) -> None:
    providers: list[str] = []
    if any(e.tag == "tamara-widget" for e in els):
        providers.append("tamara")
    if any(e.attrs.get("id") == "tabbyWidget" or e.has("tabby-container") for e in els):
        providers.append("tabby")
    promo = _first(els, "tamara-tabby-promotions")
    if providers:
        em.observed(
            "installment_provider",
            ", ".join(providers),
            sorted(providers),
            "div.tamara-tabby-promotions",
        )
    inst = _first(els, "js-instalment-price", tag="span")
    if inst is not None and inst.text:
        n = promo.attrs.get("data-num-of-installments") if promo else None
        amount = inst.text.split()[0]
        minor, reason, _note = _minor_units(amount, currency)
        raw = f"{amount} {currency}" if currency else amount
        path = "span.js-instalment-price"
        if minor is None:
            em.failed("installment_amount_minor", raw, path, reason or "could not read price")
        else:
            note = f"currency={currency.upper() if currency else ''}"
            if n:
                note += f"; {n} instalments"
            em.observed("installment_amount_minor", raw, minor, path, note)
    muse = _first(els, "muse-points-amount", tag="span")
    if muse is not None and muse.text:
        m = _DIGITS.search(muse.text)
        if m is None:
            em.failed(
                "loyalty_points", muse.text, "span.muse-points-amount", "no number in the text"
            )
        else:
            em.observed(
                "loyalty_points", muse.text, int(m.group(0)), "span.muse-points-amount", "MUSE"
            )
    badges = [
        b.attrs["data-badge-value"].strip()
        for b in els
        if b.tag == "li" and b.attrs.get("data-badge-value", "").strip()
    ]
    if badges:
        em.observed("badges", ", ".join(badges), badges, "ul.combined-badges li[data-badge-value]")
    gift = _first(els, "js-free-gift-button", tag="button")
    if gift is not None and gift.text:
        em.observed(
            "gift_with_purchase",
            gift.text,
            gift.text,
            "button.js-free-gift-button",
            "button text only; the offer terms load client-side",
        )


def _map_content(em: _Emitter, els: list[_El]) -> None:
    gallery: list[str] = []
    for img in els:
        if img.tag == "img" and img.has("js-zoom-image") and img.under("product-image-holder"):
            src = img.attrs.get("src", "").strip()
            if src and src not in gallery:
                gallery.append(src)
    if gallery:
        em.observed(
            "image_urls", "\n".join(gallery), gallery, "div.product-image-holder img.js-zoom-image"
        )
        em.observed(
            "image_count",
            str(len(gallery)),
            len(gallery),
            "div.product-image-holder img.js-zoom-image",
        )
    desc = next((e for e in els if e.attrs.get("id") == "collapseDescription"), None)
    if desc is not None and desc.text:
        em.observed("description", desc.text, desc.text, "#collapseDescription")
    haystack = " ".join(
        e.text
        for e in els
        if (e.tag == "span" and (e.has("js-name") or e.has("product-type")))
        or e.has("product-secondary-name")
    )
    for pattern, value in _CONCENTRATIONS:
        if (m := pattern.search(haystack)) is not None:
            em.observed("concentration", m.group(0), value, "span.js-name|span.product-type")
            break
    spf_source = haystack + " " + (desc.text if desc is not None else "")
    if (m := _SPF.search(spf_source)) is not None:
        em.observed("spf", m.group(0), int(m.group(1)), "span.js-name|#collapseDescription")


def _faces_readings(html: str) -> _Emitter:
    els = _scan(html)
    item = _view_item(html)
    em = _Emitter()
    _map_identity(em, els, item)
    _map_taxonomy(em, els, item)
    _map_breadcrumb(em, microdata_items(html))
    _map_shade(em, els, item)
    _map_size(em, els, item)
    currency = _currency(els, item)
    _map_prices(em, els, currency)
    _map_offer_extras(em, els, currency)
    _map_content(em, els)
    return em


# Blocks the Faces page renders client-side. They are recorded as ``not_shown`` only after the
# generic readers have had their turn: a page that does carry the value (say JSON-LD
# aggregateRating) must not come out as a false absence.
_CLIENT_SIDE: tuple[tuple[str, str], ...] = (
    ("rating_value", "Bazaarvoice ratings render client-side; not in the HTML"),
    ("rating_count", "Bazaarvoice ratings render client-side; not in the HTML"),
    ("related_products", "Constructor recommendations render client-side"),
)


_FACES_KEYS = frozenset(
    {
        "badges",
        "brand",
        "breadcrumb",
        "category_l1..l4",
        "colour_code",
        "concentration",
        "department",
        "description",
        "gift_with_purchase",
        "has_swatch_image",
        "image_count",
        "image_urls",
        "installment_amount_minor",
        "installment_provider",
        "loyalty_points",
        "product_type",
        "rating_count",
        "rating_value",
        "related_products",
        "retailer_sku",
        "shade_name",
        "size_label",
        "size_unit",
        "size_value",
        "spf",
        "style_id",
        "style_id_source",
        "title",
        "vat_statement",
    }
)
LOOKED_FOR: frozenset[str] = _FACES_KEYS | GENERIC_LOOKED_FOR
"""Every registry key ``readings_from_faces`` can yield; a capture built from it passes this as
``ProductCapture.looked_for`` so the coverage report separates "not shown" from "never read"."""


def readings_from_faces(html: str, *, locale: str, url: str | None = None) -> list[Reading]:
    """Faces-specific readings first, then the generic extractors fill every key still unread,
    then the client-side blocks are marked ``not_shown`` if nothing read them."""
    em = _faces_readings(html)
    em.extend(readings_from_generic(html, locale=locale, url=url))
    for key, note in _CLIENT_SIDE:
        em.not_shown(key, note)
    return em.readings
