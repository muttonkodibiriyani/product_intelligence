"""One comparable item per (product, retailer offer), read from a published dataset.

Everything here is parsed from what the file carries (name, category, size, price, attributes);
nothing is guessed. A value that can't be read is ``None`` and stays absent downstream.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pi_dataset import Dataset, DatasetV3, Offer, OfferV3, Product, ProductV3
from pi_match.normalise import (
    Concentration,
    Form,
    ItemKind,
    concentration,
    fold,
    form,
    item_kind,
    normalise_brand,
)
from pi_match.unit_price import BasePrice, Basis, derive_unit_price

Doc = Dataset | DatasetV3
AnyProduct = Product | ProductV3
AnyOffer = Offer | OfferV3


class Department(StrEnum):
    """The top-level category bucket; candidates never cross it."""

    FRAGRANCE = "fragrance"
    MAKEUP = "makeup"
    SKINCARE = "skincare"
    HAIR = "hair"
    BODY = "body"


class Gender(StrEnum):
    WOMEN = "women"
    MEN = "men"
    UNISEX = "unisex"


#: Checked in this order on each category level, top level first; the first level that names a
#: department decides ("Fragrance > Hair Mist" is fragrance, "Hair > Hair Oil" is hair).
_DEPARTMENTS = (
    (Department.FRAGRANCE, re.compile(r"\b(fragrances?|perfumes?|parfums?|colognes?)\b")),
    (Department.MAKEUP, re.compile(r"\b(make ?up|cosmetics|lips?|eyes?|face|nails?|brows?)\b")),
    (Department.SKINCARE, re.compile(r"\b(skin ?care|skin|serums?|moisturi[sz]ers?|cleansers?)\b")),
    (Department.HAIR, re.compile(r"\b(hair ?care|hair|shampoos?|conditioners?)\b")),
    (Department.BODY, re.compile(r"\b(body|bath|shower|hand ?care)\b")),
)
_GENDERS = (
    (Gender.UNISEX, re.compile(r"\bunisex\b")),
    (Gender.WOMEN, re.compile(r"\b(women|womens|woman|femme|for her|ladies)\b")),
    (Gender.MEN, re.compile(r"\b(men|mens|man|homme|for him|gentlemen)\b")),
)
#: Price per 100 ml or 100 g only; a price per unit compares pieces, not products.
_MEASURED = frozenset({Basis.PER_100_ML, Basis.PER_100_G})


@dataclass(frozen=True, slots=True)
class Item:
    """One product as one retailer sells it."""

    product: str
    retailer: str
    brand: str
    department: Department | None
    kind: ItemKind
    form: Form | None
    concentration: Concentration | None
    gender: Gender | None
    unit_price: BasePrice | None
    currency: str
    #: What the text model reads: the name and category path (and the v3 description, if any).
    text: str


def department(category: Sequence[str]) -> Department | None:
    for level in category:
        folded = fold(level)
        for value, pattern in _DEPARTMENTS:
            if pattern.search(folded):
                return value
    return None


def gender(text: str) -> Gender | None:
    """The one gender ``text`` names; none, or two different ones, give None."""
    folded = fold(text)
    if _GENDERS[0][1].search(folded):
        return Gender.UNISEX
    found = {value for value, pattern in _GENDERS[1:] if pattern.search(folded)}
    return found.pop() if len(found) == 1 else None


def _attribute(product: AnyProduct, key: str) -> str | None:
    value = product.attributes.get(key)
    return fold(value) if isinstance(value, str) and value.strip() else None


def _latest_price(offer: AnyOffer) -> Decimal | None:
    for price in reversed(offer.series.price):
        if price is not None:
            return Decimal(price.amount)
    return None


def _unit_price(offer: AnyOffer) -> BasePrice | None:
    size = offer.size
    if size is None:
        return None
    found = derive_unit_price(_latest_price(offer), f"{size.value} {size.unit}")
    return found if found is not None and found.basis in _MEASURED else None


def _text(product: AnyProduct, offer: AnyOffer) -> str:
    parts = [product.name, " / ".join(product.category)]
    content = offer.content if isinstance(offer, OfferV3) else None
    if content is not None and content.description:
        parts.append(content.description)
    return "\n".join(parts)


def item(product: AnyProduct, retailer: str, offer: AnyOffer) -> Item:
    words = " ".join((product.name, *product.category))
    named = _attribute(product, "concentration")
    return Item(
        product=product.id,
        retailer=retailer,
        brand=normalise_brand(product.brand),
        department=department(product.category),
        kind=item_kind(product.name),
        form=form(product.name),
        concentration=concentration(named) if named else concentration(product.name),
        gender=gender(_attribute(product, "gender") or words),
        unit_price=_unit_price(offer),
        currency=offer.currency,
        text=_text(product, offer),
    )


def items(docs: Iterable[Doc]) -> tuple[Item, ...]:
    """Every collected (non-early) offer as an item, in file order."""
    return tuple(
        item(product, retailer, offer)
        for doc in docs
        for product in doc.products
        for retailer, offer in product.offers.items()
        if not offer.early
    )
