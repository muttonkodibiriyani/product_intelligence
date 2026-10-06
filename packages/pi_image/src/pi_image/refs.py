"""Image refs from a published dataset (``pi.dataset/v2`` or ``v3`` JSON).

One ref per (retailer, exporter group token): ``source`` is the offer's retailer id
(``ulta_ae``, ``sephora_me``, ``faces_ae``), ``source_key`` the product's ``id`` (the stable
listing id of ADR-0012). The image is the offer's own (v2 ``offer.image``), else the first of its
gallery (v3 ``offer.content.images``), else none. The same rule as ``pi_match.listings``.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from pi_image.model import ImageRef


def _offer_image(offer: Mapping[str, Any]) -> str | None:
    image = offer.get("image")
    if isinstance(image, str) and image:
        return image
    content = offer.get("content")
    if isinstance(content, Mapping):
        gallery = content.get("images")
        if isinstance(gallery, list) and gallery and isinstance(gallery[0], str):
            return gallery[0]
    return None


def refs_from_dataset(
    data: Mapping[str, Any], brand_key: Callable[[str], str]
) -> tuple[ImageRef, ...]:
    """Every offer's ref, sorted by (source, source_key)."""
    out: dict[tuple[str, str], ImageRef] = {}
    products: Iterable[Mapping[str, Any]] = data.get("products") or ()
    for product in products:
        key, brand = product.get("id"), product.get("brand")
        offers = product.get("offers")
        if not isinstance(key, str) or not key or not isinstance(offers, Mapping):
            continue
        for retailer, offer in sorted(offers.items()):
            if not isinstance(offer, Mapping):
                continue
            out[(retailer, key)] = ImageRef(
                source=retailer,
                source_key=key,
                brand_key=brand_key(brand) if isinstance(brand, str) and brand.strip() else None,
                image_url=_offer_image(offer),
            )
    return tuple(out[k] for k in sorted(out))
