"""Listings for matching, read from a published dataset file (``pi.dataset/v2`` or ``v3`` JSON).

A listing is one retailer's offer of a product, identified by the exporter's group token
(``<slot>-<retailer product id>-<size>-<unit>``, ADR-0012 §1):

- an offer of a one-offer product: the product id (a hashed ``p-`` id is still stable: it is a
  hash of the token);
- an offer of a several-offer product: that retailer's half of ``m-<token>-<token>``, read only
  when exactly one split fits the retailers' slots. Otherwise the offer is unkeyed and counted,
  never guessed.

Early (recon) offers are not listings. The dataset has no GTIN field, and ``sku`` is never read
as one. The file is only read.
"""

from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from pi_match.model import ProductRecord


class ListingError(ValueError):
    """The file does not hold the requested retailer, or holds one token twice."""


def _retailer_of(meta: Mapping[str, Any]) -> dict[str, str]:
    """Offer key -> retailer id: v3 offers are keyed by context, v2 offers by retailer."""
    contexts = meta.get("contexts")
    if contexts is None:
        return {r["id"]: r["id"] for r in meta.get("retailers", ())}
    return {c["id"]: c["retailer"] for c in contexts}


def _offers(product: Mapping[str, Any], retailer_of: Mapping[str, str]) -> dict[str, Any]:
    return {
        retailer_of[key]: offer
        for key, offer in product.get("offers", {}).items()
        if offer is not None and key in retailer_of
    }


def _slots(products: Sequence[tuple[str, Collection[str]]]) -> dict[str, str]:
    """retailer -> its token slot, learned from one-offer products (``f-...`` -> ``f``).

    A retailer whose one-offer ids disagree on the slot gets none, and so does a slot letter
    that two retailers share: it cannot say which retailer a token belongs to.
    """
    seen: dict[str, set[str]] = defaultdict(set)
    for pid, retailers in products:
        if len(retailers) == 1 and len(pid) > 2 and pid[1] == "-" and not pid.startswith("m-"):
            seen[next(iter(retailers))].add(pid[0])
    single = {r: next(iter(s)) for r, s in seen.items() if len(s) == 1}
    claims = Counter(single.values())
    return {r: slot for r, slot in single.items() if claims[slot] == 1}


def listing_tokens(products: Sequence[tuple[str, Collection[str]]]) -> dict[tuple[str, str], str]:
    """``(product id, retailer)`` -> the listing token, for ``(product id, its retailers)``.

    A one-retailer product's token is its id; a several-retailer product's is that retailer's
    half of ``m-<token>-<token>`` when exactly one split names exactly its retailers. Any other
    offer has no token (it is never guessed).
    """
    slots = _slots(products)
    out: dict[tuple[str, str], str] = {}
    for pid, retailers in products:
        if len(retailers) == 1:
            out[(pid, next(iter(retailers)))] = pid
            continue
        split = split_pair_id(pid, slots)
        if split is not None and set(split) == set(retailers):
            out.update({(pid, r): t for r, t in split.items()})
    return out


def split_pair_id(pid: str, slots: Mapping[str, str]) -> dict[str, str] | None:
    """``m-<a>-<b>`` -> {retailer: token} when exactly one split fits two retailers' slots."""
    if not pid.startswith("m-"):
        return None
    rest = pid[2:]
    by_slot = {slot: retailer for retailer, slot in slots.items()}
    found: list[dict[str, str]] = []
    for i, char in enumerate(rest):
        if char != "-":
            continue
        left, right = rest[:i], rest[i + 1 :]
        if len(left) < 3 or len(right) < 3 or left[1] != "-" or right[1] != "-":
            continue
        ra, rb = by_slot.get(left[0]), by_slot.get(right[0])
        if ra is not None and rb is not None and ra != rb:
            found.append({ra: left, rb: right})
    return found[0] if len(found) == 1 else None


def _size_text(offer: Mapping[str, Any]) -> str | None:
    size = offer.get("size")
    if not size or size.get("value") in (None, "") or not size.get("unit"):
        return None
    return f"{size['value']} {size['unit']}"


def _image(offer: Mapping[str, Any]) -> str | None:
    """The offer's primary image: v2 ``image``, else the first of v3 ``content.images``."""
    if offer.get("image"):
        return str(offer["image"])
    images = (offer.get("content") or {}).get("images") or ()
    return str(images[0]) if images else None


def listings(data: Mapping[str, Any], retailer: str) -> tuple[tuple[ProductRecord, ...], int]:
    """``retailer``'s listings in ``data``, ordered by token, and how many offers had no token."""
    meta = data["meta"]
    retailer_of = _retailer_of(meta)
    if retailer not in set(retailer_of.values()):
        msg = f"the file has no retailer {retailer}"
        raise ListingError(msg)
    products: Sequence[Mapping[str, Any]] = data["products"]
    offered = [_offers(product, retailer_of) for product in products]
    tokens = listing_tokens([(p["id"], o.keys()) for p, o in zip(products, offered, strict=True)])
    records: list[ProductRecord] = []
    unkeyed = 0
    for product, offers in zip(products, offered, strict=True):
        offer = offers.get(retailer)
        if offer is None or offer.get("early"):
            continue
        token = tokens.get((product["id"], retailer))
        if token is None:
            unkeyed += 1
            continue
        category = product.get("category") or ()
        records.append(
            ProductRecord(
                source=retailer,
                source_key=token,
                brand=product["brand"],
                name=product["name"],
                url=offer.get("url"),
                image_url=_image(offer),
                size=_size_text(offer),
                # No GTIN: ``sku`` is the retailer's own id (Ulta, Sephora), not a barcode, and
                # an internal id read as a GTIN could equal another retailer's by chance.
                category=category[0] if category else None,
            )
        )
    twice = sorted(t for t, n in Counter(r.source_key for r in records).items() if n > 1)
    if twice:
        msg = f"{retailer}: token listed twice: {twice[:5]}"
        raise ListingError(msg)
    return tuple(sorted(records, key=lambda r: r.source_key)), unkeyed
