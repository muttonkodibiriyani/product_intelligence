"""Old product ids still find their product (owner requirement, task 01a0f907).

A product's id changes when the export pairs it with the other shop or splits a pair. The API
serves only the current file, so it reads the old ids out of the current ones (no stored
history, and the file is never changed):

* A listing on its own has the token ``<retailer key>-<family>-<size>-<unit>``; a pair has
  ``m-<ulta token>-<sephora token>``; the id is ``product_id(token)``
  (``scripts/demo_export/v2.py``, ``product_id``, ``pair_token`` and ``GroupKey.stable_token``).
* So an unhashed pair id holds both of its members' tokens. Each member's own id is an alias of
  the pair (pairing), and an old pair id names the members to look up now (split, re-pair).

An exact id always wins. Nothing is ever guessed: an alias that two products claim is dropped,
and an old pair id whose split is ambiguous finds nothing. A pair whose own id is hashed hides
its members' tokens, and one whose id reads more than one way names no members for sure: links
to their old ids stay not found, and ``opaque_pairs`` counts them.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from pi_dataset import DatasetV3, ProductV3, RetailerStatus

#: The export's id grammar: a token that fits is the id, anything else is hashed.
PRODUCT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
#: A pair's two tokens, Ulta's then Sephora's (register keys ``u`` and ``s``), each
#: ``<key>-<family>-<size>-<unit>``: the family may hold ``-``; size and unit can't.
ULTA_TOKEN = re.compile(r"^u-.+-[^-]+-[^-]+$")
SEPHORA_TOKEN = re.compile(r"^s-.+-[^-]+-[^-]+$")
PAIR = "m-"


def product_id(token: str) -> str:
    """The id the export gives ``token``."""
    if PRODUCT_ID.fullmatch(token):
        return token
    return "p-" + hashlib.sha256(token.encode()).hexdigest()[:24]


def halves(pair_id: str) -> Iterator[tuple[str, str]]:
    """Every way ``pair_id`` reads as ``m-<token>-<token>`` (none for any other id)."""
    if not pair_id.startswith(PAIR):
        return
    body = pair_id[len(PAIR) :]
    for at, char in enumerate(body):
        left, right = body[:at], body[at + 1 :]
        if char == "-" and ULTA_TOKEN.fullmatch(left) and SEPHORA_TOKEN.fullmatch(right):
            yield left, right


@dataclass(frozen=True)
class ProductIds:
    """The current products by id, and the old ids that read as one of them."""

    by_id: Mapping[str, ProductV3]
    #: Old member id -> the current pair holding it.
    aliases: Mapping[str, str]
    #: Product ids whose retailers support an absence claim: a split puts them first.
    supported: frozenset[str]
    #: Aliases two current products claim: dropped, so they find nothing.
    dropped: int
    #: Products at two or more retailers whose id reads as no pair (hashed) or as more than one
    #: (a family holding ``-s-``): their members' old ids can't be derived, so they register no
    #: aliases. The load log reports this; closing it needs the export.
    opaque_pairs: int


def product_ids(ds: DatasetV3, merged: Mapping[str, str] | None = None) -> ProductIds:
    """``merged``: old ids of products a match file joined -> the product holding them now."""
    by_id = {p.id: p for p in ds.products}
    retailer = {c.id: c.retailer for c in ds.meta.contexts}
    status = {r.id: r.status for r in ds.meta.retailers}
    claims: defaultdict[str, set[str]] = defaultdict(set)
    opaque = 0
    for p in ds.products:
        split = list(halves(p.id))
        if len(split) == 1:  # more than one reading: which members it holds is a guess
            ((left, right),) = split
            claims[product_id(left)].add(p.id)
            claims[product_id(right)].add(p.id)
        elif len({retailer[c] for c in p.offers}) > 1:
            opaque += 1
    for alias, owner in (merged or {}).items():
        claims[alias].add(owner)
    old = {alias: owners for alias, owners in claims.items() if alias not in by_id}
    return ProductIds(
        by_id=by_id,
        aliases={alias: next(iter(owners)) for alias, owners in old.items() if len(owners) == 1},
        supported=frozenset(
            p.id
            for p in ds.products
            if any(status[retailer[c]] is RetailerStatus.SUPPORTED for c in p.offers)
        ),
        dropped=sum(len(owners) > 1 for owners in old.values()),
        opaque_pairs=opaque,
    )


def _current(ids: ProductIds, old: str) -> str | None:
    if old in ids.by_id:
        return old
    return ids.aliases.get(old)


def resolve(ids: ProductIds, requested: str) -> tuple[ProductV3, ...]:
    """The current products ``requested`` names: itself, its pair, or a split pair's halves
    (supported retailers first, then the old id's order). Empty when nothing matches."""
    current = _current(ids, requested)
    if current is not None:
        return (ids.by_id[current],)
    found: set[tuple[str, ...]] = set()
    best = 0
    for left, right in halves(requested):
        hits = [h for h in (_current(ids, product_id(left)), _current(ids, product_id(right))) if h]
        if len(hits) > best:
            found, best = set(), len(hits)
        if hits and len(hits) == best:
            found.add(tuple(dict.fromkeys(hits)))
    if len(found) != 1:
        return ()
    (members,) = found
    ordered = sorted(members, key=lambda pid: pid not in ids.supported)
    return tuple(ids.by_id[pid] for pid in ordered)
