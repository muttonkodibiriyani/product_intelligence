"""Read helpers over a validated ``pi.dataset/v3`` document. No metric logic lives here.

Metrics compute on v3 (ADR-0008). A v2 document is read as ``upgrade(v2, <vertical>@1)``, the
upgrade the publisher will pin (ADR-0008 §4), so a v2 caller gets the same answers it always did.
Offers are keyed by **context** id; a retailer's sole context has the retailer's id.
"""

from __future__ import annotations

import threading
import unicodedata
import weakref
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from pi_dataset import (
    Context,
    Dataset,
    DatasetV3,
    MatchEdge,
    MoneyValue,
    NotObservedV3,
    Offer,
    OfferV3,
    ProductV3,
    Retailer,
    SizeV3,
    committed_profile,
    upgrade,
)
from pi_dataset.models import RetailerStatus
from pi_metrics.model import ProductFilter

#: Either contract; every public metric reads v2 through ``as_v3``.
AnyDataset = Dataset | DatasetV3
#: v2 predates profile versions: a v2 snapshot is version 1 of its vertical's profile.
V2_PROFILE_VERSION = 1


class UnknownInput(ValueError):  # noqa: N818 -- a request error; the API maps it to 422
    """A date, retailer or context the dataset doesn't have."""


class AmbiguousContext(UnknownInput):
    """A bare retailer id where a context id is needed, and the retailer has several contexts.

    The context-id rule (ADR-0008 §2) makes this deterministic: a retailer id names a context
    exactly when the retailer has one, so it is never resolved to a silent pick (422
    ``ambiguous_context``).
    """


@dataclass(frozen=True, slots=True)
class _Indexed:
    #: Weak: a cached document never outlives its caller's last reference to the source.
    source: weakref.ref[AnyDataset]
    #: The upgrade of a v2 source; ``None`` when the source is itself v3 (held only weakly).
    upgraded: DatasetV3 | None
    products: Mapping[str, ProductV3]
    contexts: Mapping[str, Context]

    def holds(self, ds: AnyDataset) -> bool:
        return self.source() is ds or self.upgraded is ds

    @property
    def ds(self) -> DatasetV3:
        if self.upgraded is not None:
            return self.upgraded
        source = self.source()
        assert isinstance(source, DatasetV3)  # noqa: S101 -- alive: the caller passed it in
        return source


class _Upgraded:
    """Upgraded documents, keyed by identity (``is``), never by value.

    The API upgrades each generation once, when it loads it (``pi_api.source``), so a request
    never pays for an upgrade. An entry lives only as long as its source document: when the API
    replaces a generation and drops the old one, ``weakref.finalize`` evicts its entry and the
    upgrade goes with it. ``LIMIT`` bounds the live entries; a different object is read afresh.
    """

    LIMIT = 8
    _entries: ClassVar[dict[int, _Indexed]] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, ds: AnyDataset) -> _Indexed:
        # Lock-free read: ``_entries`` is only ever replaced whole. Two threads may both upgrade
        # one new document; the later swap wins and both results are equal, so that is harmless.
        entry = cls._entries.get(id(ds))
        if entry is not None and entry.holds(ds):
            return entry
        upgraded = None if isinstance(ds, DatasetV3) else _upgrade(ds)
        v3 = ds if isinstance(ds, DatasetV3) else upgraded
        assert v3 is not None  # noqa: S101 -- one of the two branches above
        entry = _Indexed(
            source=weakref.ref(ds),
            upgraded=upgraded,
            products={p.id: p for p in v3.products},
            contexts={c.id: c for c in v3.meta.contexts},
        )
        with cls._lock:
            entries = {**cls._entries, id(ds): entry, id(v3): entry}
            # Drop entries whose source died (a finalizer may race this swap).
            entries = {k: e for k, e in entries.items() if e.source() is not None}
            while len({id(e) for e in entries.values()}) > cls.LIMIT:
                oldest = next(iter(entries.values()))
                entries = {k: e for k, e in entries.items() if e is not oldest}
            cls._entries = entries  # one reference swap: readers see a whole dict
        weakref.finalize(ds, cls._evict, entry)
        return entry

    @classmethod
    def _evict(cls, entry: _Indexed) -> None:
        # Runs when the source is collected, possibly on any thread: no lock (it could already be
        # held by this thread mid-swap); ``get`` also drops dead entries under its lock.
        cls._entries = {k: e for k, e in cls._entries.items() if e is not entry}


def _upgrade(v2: Dataset) -> DatasetV3:
    profile = committed_profile(v2.meta.vertical, V2_PROFILE_VERSION)
    if profile is None:
        msg = f"no committed profile {v2.meta.vertical}@{V2_PROFILE_VERSION} to read this v2 by"
        raise ValueError(msg)
    return upgrade(v2, profile)


def as_v3(ds: AnyDataset) -> DatasetV3:
    """``ds`` itself if it is v3, else ``upgrade(ds, <vertical>@1)`` (cached by identity).

    Raises ``UpgradeError`` (a ``ValueError``) if a v2 document can't be read as v3.
    """
    return _Upgraded.get(ds).ds


def product_v3(ds: AnyDataset, product_id: str) -> ProductV3:
    """The v3 product with this id; ``KeyError`` if there is none."""
    return _Upgraded.get(ds).products[product_id]


def applies(ds: DatasetV3, profiles: frozenset[str]) -> bool:
    """The snapshot's profile is one the metric states it applies to (ADR-0008 §3)."""
    return ds.meta.profile.name in profiles


def date_index(ds: DatasetV3, on: date | None) -> int:
    """Index into ``meta.dates``; ``None`` is the latest date."""
    if on is None:
        return len(ds.meta.dates) - 1
    try:
        return ds.meta.dates.index(on)
    except ValueError:
        msg = f"{on} is not an observation date of this dataset"
        raise UnknownInput(msg) from None


def retailer(ds: DatasetV3, retailer_id: str) -> Retailer:
    for candidate in ds.meta.retailers:
        if candidate.id == retailer_id:
            return candidate
    msg = f"unknown retailer {retailer_id!r}"
    raise UnknownInput(msg)


def selected_retailers(ds: DatasetV3, ids: tuple[str, ...]) -> tuple[Retailer, ...]:
    return tuple(retailer(ds, i) for i in ids) if ids else ds.meta.retailers


def context(ds: DatasetV3, context_id: str) -> Context:
    found = _Upgraded.get(ds).contexts.get(context_id)
    if found is None:
        several = contexts_of(ds, context_id)
        if several:
            names = ", ".join(c.id for c in several)
            msg = f"retailer {context_id!r} has several contexts; name one of: {names}"
            raise AmbiguousContext(msg)
        msg = f"unknown retailer or context {context_id!r}"
        raise UnknownInput(msg)
    return found


def contexts_of(ds: DatasetV3, retailer_id: str) -> tuple[Context, ...]:
    """The retailer's contexts in snapshot order; empty for an id that is not a retailer."""
    return tuple(c for c in ds.meta.contexts if c.retailer == retailer_id)


def selected_contexts(ds: DatasetV3, ids: tuple[str, ...]) -> tuple[Context, ...]:
    return tuple(context(ds, i) for i in ids) if ids else ds.meta.contexts


def status(ds: DatasetV3, context_id: str) -> RetailerStatus:
    """A context is never better than its retailer: the retailer's status is the context's."""
    return retailer(ds, context(ds, context_id).retailer).status


def products(ds: DatasetV3, where: ProductFilter) -> Iterator[ProductV3]:
    return (p for p in ds.products if where.matches(p))


def price_on(offer: Offer, i: int) -> MoneyValue | None:
    return offer.series.price[i]


def regular_on(offer: Offer, i: int) -> MoneyValue | None:
    return None if offer.series.regular is None else offer.series.regular[i]


def covers(window: NotObservedV3, product: ProductV3, day: date) -> bool:
    if not window.start <= day <= window.end:
        return False
    if window.categories is None:
        return True
    # Window categories are codes; ``category[1:]`` is the retailer's breadcrumb (#108).
    return product.category[0].casefold() in {c.casefold() for c in window.categories}


def not_observed(ds: DatasetV3, context_id: str, product: ProductV3, i: int) -> bool:
    """A ``notObserved`` window says this context's catalogue wasn't seen for the product.

    A window with no ``context`` covers every context of its retailer.
    """
    ctx = context(ds, context_id)
    day = ds.meta.dates[i]
    return any(
        w.retailer == ctx.retailer and w.context in (None, ctx.id) and covers(w, product, day)
        for w in ds.not_observed
    )


def complete_run(ds: DatasetV3, context_id: str, product: ProductV3, i: int) -> bool:
    """The context's crawl on date ``i`` is complete for the product's category.

    Only a ``supported`` retailer, collected since on or before the date, with no ``notObserved``
    window over the context, date and category can back an absence claim: a removal, a launch or
    an assortment gap (design §6, §7.3).
    """
    shop = retailer(ds, context(ds, context_id).retailer)
    return (
        shop.status is RetailerStatus.SUPPORTED
        and shop.since is not None
        and shop.since <= ds.meta.dates[i]
        and not not_observed(ds, context_id, product, i)
    )


def collected(product: ProductV3, context_id: str) -> OfferV3 | None:
    """The context's offer, unless it is missing or an early recon sample (never counted)."""
    offer = product.offers.get(context_id)
    return None if offer is None or offer.early else offer


def retailer_offers(ds: DatasetV3, product: ProductV3, retailer_id: str) -> list[OfferV3]:
    """Every offer the product has in any context of the retailer."""
    return [o for cid, o in product.offers.items() if context(ds, cid).retailer == retailer_id]


def identity_unclear(ds: DatasetV3, product: ProductV3, retailer_id: str) -> bool:
    """The fail-safe reading of identity rules (b) and (c) (ADR-0008 §2).

    A retailer with several offers in one product names one item only when every one of them
    carries the same ``evidence.itemKey``. An unkeyed offer next to another of its retailer, or
    two keys, make every pair involving that retailer in the product ``no_match``. The v3
    validator rejects both; this keeps a document that slipped past it from miscounting.
    """
    offers = retailer_offers(ds, product, retailer_id)
    keys = {o.evidence.item_key for o in offers}
    return len(offers) > 1 and (None in keys or len(keys) > 1)


def seen(offer: Offer, i: int) -> bool:
    """The offer was observed on date ``i``: priced, or with an observed stock state."""
    if offer.series.price[i] is not None:
        return True
    states = offer.series.availability
    return states is not None and states[i] is not None


def edge_between(product: ProductV3, a: str, b: str) -> MatchEdge | None:
    """The edge between two **retailers** (edges are never between contexts)."""
    low, high = sorted((a, b))
    return next((e for e in product.matches if (e.a, e.b) == (low, high)), None)


def fold(text: str) -> str:
    """NFKC, casefold, whitespace runs collapsed and trimmed (ADR-0008 §1). Never translates."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class SizeMatch(StrEnum):
    EQUAL = "equal"
    #: Equal measures whose published labels differ: counted, with ``size_labels_differ``.
    LABELS_DIFFER = "labels_differ"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


def same_size(  # noqa: PLR0911 -- the rule table, one return per row
    a: SizeV3 | None, b: SizeV3 | None, *, labels_comparable: bool
) -> SizeMatch:
    """The symmetric same-size rule (ADR-0008 §1); swapping ``a`` and ``b`` never changes it.

    * measure vs measure: equal iff ``Decimal(value)`` and ``fold(unit)`` are; two labels that
      differ on equal measures are ``LABELS_DIFFER``, never silent;
    * label only vs label only: equal iff ``fold(label)`` and ``system`` are and the profile says
      labels are comparable; otherwise unknown, since nothing proves them different either;
    * label only vs a measure, or a missing size: unknown. A measure is never inferred.

    Callers compare labels only inside an exact edge or one retailer's stable-key group.
    """
    if a is None or b is None:
        return SizeMatch.UNKNOWN
    if a.value is not None and b.value is not None:
        if Decimal(a.value) != Decimal(b.value) or fold(a.unit or "") != fold(b.unit or ""):
            return SizeMatch.MISMATCH
        if a.label is not None and b.label is not None and fold(a.label) != fold(b.label):
            return SizeMatch.LABELS_DIFFER
        return SizeMatch.EQUAL
    if a.value is not None or b.value is not None or not labels_comparable:
        return SizeMatch.UNKNOWN
    # Both label-only: SizeV3 guarantees a label when there is no value. Labels are never
    # translated, so "وسط" vs "Medium" proves nothing either way: unknown, never a mismatch.
    if fold(a.label or "") == fold(b.label or "") and a.system == b.system:
        return SizeMatch.EQUAL
    return SizeMatch.UNKNOWN


def market_currency(ds: DatasetV3, retailer_id: str) -> str:
    return ds.market_of(retailer_id).currency
