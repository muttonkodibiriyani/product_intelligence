"""Offer content held compressed in memory, read only by product detail (tm8 01a11763-dc85).

``Offer.content`` (description, ingredients, gallery, variants) is about half of a content-rich
snapshot's resident memory, and only product detail reads it. At load each offer's content is
replaced by a ``PackedContent``: ``captured`` and ``family`` stay resident (the family index and
insights read them), the rest is kept as zlib-compressed JSON and read back by ``unpacked``. The
file and its contract are unchanged; cards, lists and exports never read content (a card's image
is ``product.image`` / ``offer.image``).

A ``PackedContent`` without its packed body is a bug, never "not published": ``unpacked`` raises
``PackedContentError`` (a 500) rather than serve empty fields.
"""

from __future__ import annotations

import zlib
from typing import Self

from pydantic import PrivateAttr

from pi_dataset import DatasetV3, OfferContent, OfferV3, ProductV3


class PackedContentError(RuntimeError):
    """A packed offer content has no packed body (an internal error)."""


class PackedContent(OfferContent):
    """``captured`` and ``family`` resident; every field, as JSON, compressed in ``_body``."""

    _body: bytes = PrivateAttr(default=b"")

    @classmethod
    def of(cls, content: OfferContent) -> Self:
        packed = cls(captured=content.captured, family=content.family)
        packed._body = zlib.compress(content.model_dump_json().encode("utf-8"))
        return packed

    def unpacked(self) -> OfferContent:
        if not self._body:
            raise PackedContentError
        return OfferContent.model_validate_json(zlib.decompress(self._body))


def unpacked(content: OfferContent | None) -> OfferContent | None:
    """The offer's full content: a packed one read back, any other as it is."""
    return content.unpacked() if isinstance(content, PackedContent) else content


def _heavy(content: OfferContent) -> bool:
    return bool(content.description or content.ingredients or content.images or content.variants)


def _offer(offer: OfferV3) -> OfferV3:
    content = offer.content
    if content is None or isinstance(content, PackedContent) or not _heavy(content):
        return offer
    return offer.model_copy(update={"content": PackedContent.of(content)})


def _product(product: ProductV3) -> ProductV3:
    offers = {cid: _offer(o) for cid, o in product.offers.items()}
    if all(offers[cid] is o for cid, o in product.offers.items()):
        return product
    return product.model_copy(update={"offers": offers})


def packed(ds: DatasetV3) -> DatasetV3:
    """``ds`` with every offer's content packed (an offer with nothing heavy is kept as is)."""
    return ds.model_copy(update={"products": tuple(_product(p) for p in ds.products)})
