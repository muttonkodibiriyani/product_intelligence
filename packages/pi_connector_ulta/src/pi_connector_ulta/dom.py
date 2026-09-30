"""Primary ulta.ae parser: the rendered page DOM plus its schema.org JSON-LD.

robots.txt disallows ``/graphql`` for every agent, so the catalog JSON the storefront loads is
not the primary source (coordinator ruling pending; ``catalog.py`` stays behind an off-by-default
flag). Everything here comes from the HTML of one rendered page load.

What a product page (``/en|ar/buy-<slug>``) exposes, verified on real captures (2026-09-30):

* JSON-LD ``Product``: style code (``sku``), name, description, brand, one ``Offer`` (price and
  availability of the page's selected variant) and ``aggregateRating`` when reviewed.
* JSON-LD ``BreadcrumbList``: the category path.
* DOM: brand link (``/shop-brands/<slug>``, same slug in both locales), title, the selected
  variant's price (``pdp-product__price-special``; a regular/strike price when shown), one
  swatch ``<input data-sku=... value=...>`` per variant with ``disabled`` when out of stock,
  the selected variant's size and gallery images.

Not in the DOM: other variants' prices (they can differ: Kylie shades are 155 or 160), EAN,
member price and GWP promotions. Those are ``None`` with reason ``unknown`` or
``not_published``, never guessed from the selected variant.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from pi_connector_ulta.catalog import (
    _GIFT_PRICE_CEILING,
    CatalogError,
    PlpHit,
    Price,
    UltaProduct,
    UltaVariant,
    _clean,
    _decimal,
)

__all__ = ["merge_page_json", "parse_pdp_html", "parse_plp_html"]

_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ARABIC_DIGITS = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u066b\u066c", "0123456789.,"
)
_BRAND_PATH = re.compile(r"^/(?:en|ar)/shop-brands/([^/?#]+)")
_COUNT = re.compile(r"\((\d+)\)")


@dataclass(eq=False)
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: _Node | None = None
    children: list[_Node | str] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text())
        return "".join(parts)

    def iter(self) -> Any:
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.iter()

    def find_all(self, cls: str | None = None, tag: str | None = None) -> list[_Node]:
        return [
            n
            for n in self.iter()
            if (tag is None or n.tag == tag) and (cls is None or cls in n.classes())
        ]

    def find(self, cls: str | None = None, tag: str | None = None) -> _Node | None:
        found = self.find_all(cls, tag)
        return found[0] if found else None


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {k: v or "" for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(_Node(tag, {k: v or "" for k, v in attrs}, self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _tree(document: str | bytes) -> _Node:
    if isinstance(document, bytes):
        document = document.decode("utf-8", errors="replace")
    builder = _TreeBuilder()
    builder.feed(document)
    builder.close()
    return builder.root


def _squash(text: str | None) -> str | None:
    if text is None:
        return None
    text = " ".join(text.replace("\xa0", " ").split())
    return text or None


def _amount(text: str | None) -> Decimal | None:
    if not text:
        return None
    match = _NUMBER.search(text.translate(_ARABIC_DIGITS))
    return _decimal(match.group(0).replace(",", "")) if match else None


def _price_text(text: str | None) -> Price:
    amount = _amount(text)
    if amount is None:
        return Price(None, "not_published")
    if amount < _GIFT_PRICE_CEILING:
        return Price(None, "not_applicable")  # free gift / sample placeholder, not a price
    return Price(amount)


def _json_ld(root: _Node) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for script in root.find_all(tag="script"):
        if script.attrs.get("type") != "application/ld+json":
            continue
        try:
            data = json.loads(script.text(), parse_float=Decimal)
        except json.JSONDecodeError:
            continue
        items = data.get("@graph") if isinstance(data, dict) and "@graph" in data else data
        for item in items if isinstance(items, list) else [items]:
            if isinstance(item, dict):
                blocks.append(item)
    return blocks


def _of_type(blocks: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((b for b in blocks if b.get("@type") == kind), None)


def _category(breadcrumbs: dict[str, Any] | None) -> str | None:
    if not breadcrumbs:
        return None
    items = sorted(
        (i for i in breadcrumbs.get("itemListElement") or [] if isinstance(i, dict)),
        key=lambda i: int(i.get("position") or 0),
    )
    names = [str((i.get("item") or {}).get("name") or "") for i in items]
    inner = [n for n in names[1:-1] if n]  # drop Home and the product itself
    return "|".join(inner) or None


def _image(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _ld_stock(product: dict[str, Any]) -> bool | None:
    offers = product.get("offers")
    offer = offers[0] if isinstance(offers, list) and offers else offers
    availability = str((offer or {}).get("availability") or "") if isinstance(offer, dict) else ""
    if availability.endswith("InStock"):
        return True
    if availability.endswith("OutOfStock") or availability.endswith("SoldOut"):
        return False
    return None


def _ld_price(product: dict[str, Any]) -> Decimal | None:
    offers = product.get("offers")
    offer = offers[0] if isinstance(offers, list) and offers else offers
    return _decimal(offer.get("price")) if isinstance(offer, dict) else None


@dataclass(frozen=True, slots=True)
class _Swatch:
    sku: str
    dimension: str
    value: str | None
    in_stock: bool
    selected: bool


def _swatches(column: _Node) -> list[_Swatch]:
    found: dict[str, _Swatch] = {}
    for node in column.find_all(tag="input"):
        sku = node.attrs.get("data-sku")
        if not sku or sku in found:
            continue
        label = node.attrs.get("aria-label", "").lower()
        found[sku] = _Swatch(
            sku=sku,
            dimension=node.attrs.get("name", ""),
            value=_clean(node.attrs.get("value")),
            in_stock="disabled" not in node.attrs and "out of stock" not in label,
            selected="checked" in node.attrs or label.endswith("selected"),
        )
    return list(found.values())


def _size(column: _Node) -> tuple[str | None, str | None]:
    node = column.find("pdp-product__size")
    selection = node.find("pdp-swatches__field__label--selection") if node else None
    text = _squash(selection.text()) if selection else None
    if not text:
        return None, None
    value, _, uom = text.partition(" ")
    size = _clean(value)
    return size, (_clean(uom) if size else None)


def _dom_prices(column: _Node) -> tuple[Price, Price]:
    """(regular, final) shown for the selected variant; regular only when a strike price shows."""
    box = column.find("pdp-product__prices")
    if box is None:
        return Price(None, "not_published"), Price(None, "not_published")
    special = box.find("pdp-product__price-special")
    final = _price_text(special.text() if special else None)
    regular = Price(None, "not_published")
    for node in box.iter():
        slot = node.attrs.get("data-slot", "")
        cls = node.attrs.get("class", "")
        if slot == "RegularPrice" or "price-regular" in cls or "strikethrough" in cls:
            regular = _price_text(node.text())
            break
    return regular, final


def parse_pdp_html(document: str | bytes, page_locale: str) -> UltaProduct:
    """The product on one rendered ulta.ae product page."""
    if page_locale not in {"en", "ar"}:
        raise CatalogError(f"unknown locale {page_locale!r}")
    root = _tree(document)
    blocks = _json_ld(root)
    ld = _of_type(blocks, "Product")
    column = root.find("pdp-product__content-column")
    if ld is None or column is None or not ld.get("sku"):
        raise CatalogError("not a rendered product page")

    brand_node = column.find("pdp-product__subtitle")
    brand_link = brand_node.find(tag="a") if brand_node else None
    brand_path = _BRAND_PATH.match(brand_link.attrs.get("href", "")) if brand_link else None
    ld_brand = ld.get("brand")
    brand = _squash(brand_node.text() if brand_node else None) or (
        _squash(str(ld_brand.get("name") or "")) if isinstance(ld_brand, dict) else None
    )
    title = column.find("pdp-product__title", tag="h6")
    name = _squash(title.text() if title else None) or _squash(str(ld.get("name") or "")) or ""

    regular, final = _dom_prices(column)
    if final.amount is None and final.reason == "not_published":
        ld_amount = _ld_price(ld)  # the JSON-LD offer is the same selected variant
        if ld_amount is not None:
            final = _price_text(str(ld_amount))
    gallery = root.find("pdp-product__images")
    images = tuple(
        dict.fromkeys(
            _image(img.attrs["src"])
            for img in (gallery.find_all(tag="img") if gallery else [])
            if img.attrs.get("src", "").startswith("https://")
        )
    )
    size, size_uom = _size(column)
    style = str(ld["sku"])
    found = _swatches(column)
    swatches = found or [_Swatch(style, "", None, bool(_ld_stock(ld)), selected=True)]
    if len(swatches) == 1:
        swatches = [
            _Swatch(
                swatches[0].sku,
                swatches[0].dimension,
                swatches[0].value,
                swatches[0].in_stock,
                selected=True,
            )
        ]
    unknown = Price(None, "unknown")
    variants = []
    for sw in swatches:
        chosen = sw.selected
        fin = final if chosen else unknown
        reg = regular if chosen else unknown
        variants.append(
            UltaVariant(
                sku=sw.sku,
                name=name,
                in_stock=sw.in_stock if found else _ld_stock(ld),
                regular=reg,
                final=fin,
                shade=sw.value if sw.dimension == "color" else None,
                shade_description=None,
                size=(sw.value if sw.dimension == "size" else (size if chosen else None)),
                size_uom=size_uom if chosen and sw.dimension != "size" else None,
                barcode=None,
                images=images if chosen else (),
                labels=(),
                promotions=(),
                member_price=Price(None, "not_published"),
                free_gift="not_applicable" in (fin.reason, reg.reason),
                is_sale=False,
                url_key=None,
            )
        )
    raw_rating = ld.get("aggregateRating")
    rating: dict[str, Any] = raw_rating if isinstance(raw_rating, dict) else {}
    count = rating.get("reviewCount")
    url = str(ld.get("@id") or "")
    return UltaProduct(
        locale=page_locale,
        sku=style,
        name=name,
        url_key=urlsplit(url).path.rsplit("/", 1)[-1] if url else "",
        brand=brand,
        kind="dom",
        in_stock=_ld_stock(ld),
        description=_squash(str(ld.get("description") or "")),
        category_path=_category(_of_type(blocks, "BreadcrumbList")),
        ulta_type=None,
        variants=tuple(variants),
        raw_attributes={},
        brand_key=brand_path.group(1) if brand_path else None,
        rating_average=_decimal(rating.get("ratingValue")) if count else None,
        rating_count=int(count) if isinstance(count, (int, Decimal)) and count > 0 else None,
    )


def parse_plp_html(document: str | bytes, page_locale: str) -> list[PlpHit]:
    """Product tiles rendered on a category page (the tiles in the DOM, first page only)."""
    root = _tree(document)
    hits: dict[str, PlpHit] = {}
    for card in root.find_all("product-item"):
        if "card" not in card.classes():
            continue
        link = card.find("product-item-link", tag="a")
        href = link.attrs.get("href", "") if link else ""
        sku = card.attrs.get("data-id", "")
        if not sku or not href.startswith(f"/{page_locale}/buy-") or sku in hits:
            continue
        brand = card.find("product-item-brand")
        rating_node = card.find("rating-text")
        count_node = card.find("rating-count")
        count_match = _COUNT.search(count_node.text()) if count_node else None
        count = int(count_match.group(1)) if count_match else None
        avg = _amount(rating_node.text()) if rating_node else None
        rated = bool(count and avg)
        discounted = card.find("item-price-discounted")
        plain = card.find("item-price")
        slashed = card.find("item-price-original-slashed")
        shown = discounted or plain
        hits[sku] = PlpHit(
            sku=sku,
            url_path=href,
            locale=page_locale,
            title=_squash(link.attrs.get("aria-label")) if link else None,
            brand=_squash(brand.text()) if brand else None,
            final_price=_price_text(shown.text() if shown else None),
            original_price=_price_text(slashed.text() if slashed else None),
            rating_average=avg if rated else None,
            rating_count=count if rated else None,
            sizes=(),
        )
    return list(hits.values())


def merge_page_json(product: UltaProduct, page_json: UltaProduct | None) -> UltaProduct:
    """Fill DOM gaps from the page's own catalog JSON (optional path, off unless enabled).

    Only fields the DOM could not show are filled (other variants' prices, EAN, member price,
    promotions, labels); what the DOM shows wins. Variants are matched on SKU only.
    """
    if page_json is None or page_json.sku != product.sku:
        return product
    by_sku = {v.sku: v for v in page_json.variants}
    variants = []
    for v in product.variants:
        j = by_sku.get(v.sku)
        if j is None:
            variants.append(v)
            continue
        dom_priced = v.final.amount is not None or v.final.reason == "not_applicable"
        variants.append(
            replace(
                v,
                regular=v.regular if dom_priced else j.regular,
                final=v.final if dom_priced else j.final,
                shade_description=v.shade_description or j.shade_description,
                size=v.size or j.size,
                size_uom=v.size_uom or j.size_uom,
                barcode=v.barcode or j.barcode,
                images=v.images or j.images,
                labels=v.labels or j.labels,
                promotions=v.promotions or j.promotions,
                member_price=j.member_price,
                free_gift=v.free_gift or j.free_gift,
                is_sale=j.is_sale,
                url_key=v.url_key or j.url_key,
            )
        )
    return replace(
        product, variants=tuple(variants), ulta_type=product.ulta_type or page_json.ulta_type
    )
