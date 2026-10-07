"""Field coverage for a "similar / competing products" signal, per retailer. Read-only.

Usage::

    uv run python -m scripts.similar_coverage.coverage FILE [FILE ...] > coverage.json

Each FILE is a published ``pi.dataset`` document (v2 or v3). The report is aggregate counts
only: no product name, description, URL or price leaves this script, so its output can be
shared. Nothing is written except to stdout.

Counted per retailer (the offer key), over its collected (non-early) offers, for all offers
and for the fragrance subset (a category level naming fragrance, perfume, parfum or cologne):

- ``offers`` and ``products``;
- ``name_concentration``: a concentration (EDP, EDT, parfum, EDC, body mist) written in the
  product name, read with ``pi_match.normalise.concentration``;
- ``attribute_concentration``: a ``concentration`` product attribute;
- ``gender_cue``: a gender word in the name or category (men, women, homme, femme, unisex, …);
- ``measured_size``: a size in ml or g (fl oz and oz included);
- ``priced``: at least one observed selling price;
- ``unit_price_ready``: both priced and a measured size, so a price per ml or g can be derived;
- ``category_depth_2``: a category path with at least two levels;
- ``image``: an offer or product image;
- v3 only (``content``): ``gallery_2`` (two or more gallery images), ``description``,
  ``notes_cue`` (the description names top, heart or base notes, or "notes of"),
  ``scent_family_cue`` (the description names a scent family word: floral, woody, amber, …) and
  ``retailer_family_id`` (``content.family``).

A count that the document's schema can't carry (v3-only fields in a v2 file) is ``null``, never
0, so "not in this file" and "none found" stay apart. A retailer key found in two files fails
the run rather than silently merging them.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pi_dataset import Dataset, DatasetV3, Offer, OfferV3, Product, ProductV3, load_any
from pi_match.normalise import concentration, fold

COUNTS = (
    "offers", "products", "name_concentration", "attribute_concentration", "gender_cue",
    "measured_size", "priced", "unit_price_ready", "category_depth_2", "image",
)  # fmt: skip
#: Counts only a v3 document can carry; null for a v2 file.
CONTENT_COUNTS = (
    "gallery_2", "description", "notes_cue", "scent_family_cue", "retailer_family_id",
)  # fmt: skip
SCOPES = ("all", "fragrance")

_FRAGRANCE = re.compile(r"\b(fragrances?|perfumes?|parfums?|colognes?)\b")
_GENDER = re.compile(r"\b(men|mens|man|women|womens|woman|homme|femme|unisex|masculine|feminine)\b")
_NOTES = re.compile(r"\b((top|heart|middle|base) notes?|notes? of)\b")
_SCENT_FAMILY = re.compile(
    r"\b(floral|woody|oriental|amber|ambery|citrus|fresh|gourmand|aromatic|chypre|fougere"
    r"|musky|musk|spicy|fruity|aquatic|green|leather|powdery)\b"
)
_MEASURED_UNITS = frozenset({"ml", "g", "fl oz", "floz", "oz", "l", "kg"})

Doc = Dataset | DatasetV3
AnyProduct = Product | ProductV3
AnyOffer = Offer | OfferV3


@dataclass
class Tally:
    """Counts for one retailer and scope; ``content`` is False for a v2 file."""

    content: bool
    counts: dict[str, int] = field(default_factory=dict)
    products: set[str] = field(default_factory=set)

    def add(self, name: str, hit: bool) -> None:
        self.counts[name] = self.counts.get(name, 0) + int(hit)

    def report(self) -> dict[str, int | None]:
        out: dict[str, int | None] = {n: self.counts.get(n, 0) for n in COUNTS}
        out["products"] = len(self.products)
        for name in CONTENT_COUNTS:
            out[name] = self.counts.get(name, 0) if self.content else None
        return out


def is_fragrance(category: Sequence[str]) -> bool:
    return any(_FRAGRANCE.search(fold(level)) for level in category)


def _measured(offer: AnyOffer) -> bool:
    size = offer.size
    if size is None or size.value is None or size.unit is None:
        return False
    return fold(size.unit).replace(".", "").strip() in _MEASURED_UNITS


def _observe(tally: Tally, product: AnyProduct, offer: AnyOffer) -> None:
    text = fold(" ".join((product.name, *product.category)))
    priced = any(p is not None for p in offer.series.price)
    measured = _measured(offer)
    tally.products.add(product.id)
    tally.add("offers", True)
    tally.add("name_concentration", concentration(product.name) is not None)
    tally.add("attribute_concentration", "concentration" in product.attributes)
    tally.add("gender_cue", _GENDER.search(text) is not None)
    tally.add("measured_size", measured)
    tally.add("priced", priced)
    tally.add("unit_price_ready", priced and measured)
    tally.add("category_depth_2", len(product.category) >= 2)
    tally.add("image", offer.image is not None or product.image is not None)
    content = offer.content if isinstance(offer, OfferV3) else None
    description = fold(content.description) if content and content.description else ""
    tally.add("gallery_2", content is not None and len(content.images) >= 2)
    tally.add("description", bool(description))
    tally.add("notes_cue", _NOTES.search(description) is not None)
    tally.add("scent_family_cue", _SCENT_FAMILY.search(description) is not None)
    tally.add("retailer_family_id", content is not None and content.family is not None)


def coverage(docs: Iterable[Doc]) -> dict[str, dict[str, dict[str, int | None]]]:
    """Per retailer key and scope, the counts above. Raises on a retailer in two documents."""
    tallies: dict[str, dict[str, Tally]] = {}
    for doc in docs:
        content = isinstance(doc, DatasetV3)
        seen: dict[str, dict[str, Tally]] = {}
        for product in doc.products:
            scopes = ("all", "fragrance") if is_fragrance(product.category) else ("all",)
            for key, offer in product.offers.items():
                if offer.early:
                    continue
                by_scope = seen.setdefault(key, {s: Tally(content) for s in SCOPES})
                for scope in scopes:
                    _observe(by_scope[scope], product, offer)
        clash = sorted(set(seen) & set(tallies))
        if clash:
            msg = f"retailer {clash} is in more than one file; pass each retailer once"
            raise ValueError(msg)
        tallies.update(seen)
    return {
        key: {scope: tally.report() for scope, tally in by_scope.items()}
        for key, by_scope in sorted(tallies.items())
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    allow_test = "--allow-test" in args  # synthetic test documents only
    paths = [Path(a) for a in args if a != "--allow-test"]
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    docs = [load_any(path.read_bytes(), allow_test=allow_test) for path in paths]
    files = [
        {"schema": doc.schema_id, "dates": [str(doc.meta.dates[0]), str(doc.meta.dates[-1])]}
        for doc in docs
    ]
    report = {"files": files, "retailers": coverage(docs)}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
