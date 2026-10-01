"""Per-source snapshots composed into one same-scope view (ADR-0010).

Each source (a retailer id) is assigned one snapshot file. :func:`only` takes from a file just
the assigned sources: their retailer entries, contexts, offers, ``notObserved`` windows and the
match edges between two of them. :func:`compose` joins those slices into one ``DatasetV3``:

* every slice has the same scope, vertical, profile and attribute set, and a market shared by
  two slices has one currency and time zone, else :class:`CompositionError`;
* the dates are the union of the slices'; a source's series are null on a date its file lacks
  (not observed that day, never carried forward);
* a product id in two slices is one product: its offers are the union (a source's contexts are
  its own, so offers never collide), its product fields come from the first slice that has it,
  and the merge is reported in :attr:`Composed.merged_ids`;
* a match edge is kept only from a file that holds both of its retailers' offers, so no edge is
  ever made across two files;
* ``capabilities`` are or-ed, a ``fields`` status that differs between slices is ``partial``,
  ``cutoff`` and ``generatedAt`` are the latest. Each source keeps its own in
  :class:`SourceInfo`.

Pure functions; nothing here reads or writes storage.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from pi_dataset.models import (
    Capabilities,
    ContractModel,
    FieldStatus,
    MarketInfo,
    MatchEdge,
    Producer,
)
from pi_dataset.v3 import DatasetV3, MetaV3, OfferV3, ProductV3

#: The ``meta.producer`` of a composed view; each source's own is in its file.
PRODUCER = Producer(name="pi_dataset.compose", version="1")


class CompositionError(ValueError):
    """The slices can't be one view (scope, profile or market mismatch, a missing source)."""


class SourceInfo(ContractModel):
    """One source of a view, as its own file has it."""

    #: The retailer id.
    source: str
    cutoff: datetime
    generated_at: datetime
    #: The source's own latest observation date; the view's dates may run later.
    last_date: date
    match_stage: str
    capabilities: Capabilities
    fields: dict[str, FieldStatus]
    #: Products with an offer of this source.
    products: int


@dataclass(frozen=True)
class Composed:
    dataset: DatasetV3
    sources: tuple[SourceInfo, ...]
    #: Product ids found in more than one slice, merged into one product (sorted).
    merged_ids: tuple[str, ...]


def source_infos(ds: DatasetV3) -> tuple[SourceInfo, ...]:
    """One entry per retailer of ``ds``, each with the file's own meta."""
    retailer_of = {c.id: c.retailer for c in ds.meta.contexts}
    products: dict[str, int] = {r.id: 0 for r in ds.meta.retailers}
    for product in ds.products:
        for retailer in {retailer_of[cid] for cid in product.offers}:
            products[retailer] += 1
    m = ds.meta
    return tuple(
        SourceInfo(
            source=r.id,
            cutoff=m.cutoff,
            generated_at=m.generated_at,
            last_date=m.dates[-1],
            match_stage=m.match_stage,
            capabilities=m.capabilities,
            fields=dict(m.fields),
            products=products[r.id],
        )
        for r in m.retailers
    )


def only(ds: DatasetV3, sources: Iterable[str]) -> DatasetV3:
    """``ds`` cut down to ``sources``; any other retailer in the file is left out."""
    keep = frozenset(sources)
    missing = sorted(keep - {r.id for r in ds.meta.retailers})
    if missing:
        msg = f"the file has no retailer {missing}"
        raise CompositionError(msg)
    contexts = tuple(c for c in ds.meta.contexts if c.retailer in keep)
    kept_contexts = {c.id for c in contexts}
    retailer_of = {c.id: c.retailer for c in contexts}
    products = []
    for product in ds.products:
        offers = {cid: o for cid, o in product.offers.items() if cid in kept_contexts}
        if not offers:
            continue
        offered = {retailer_of[cid] for cid in offers}
        matches = tuple(e for e in product.matches if {e.a, e.b} <= offered)
        products.append(product.model_copy(update={"offers": offers, "matches": matches}))
    if not products:
        msg = f"no product has an offer of {sorted(keep)}"
        raise CompositionError(msg)
    meta = ds.meta.model_copy(
        update={
            "retailers": tuple(r for r in ds.meta.retailers if r.id in keep),
            "contexts": contexts,
        }
    )
    return DatasetV3(
        schema_id="pi.dataset/v3",
        meta=meta,
        products=tuple(products),
        not_observed=tuple(w for w in ds.not_observed if w.retailer in keep),
    )


def compose(slices: Sequence[DatasetV3]) -> Composed:
    """The slices as one view; see the module docstring for the rules."""
    if not slices:
        msg = "nothing to compose"
        raise CompositionError(msg)
    first = slices[0].meta
    for s in slices[1:]:
        _check_same_scope(first, s.meta)
    retailers = [r for s in slices for r in s.meta.retailers]
    dup = sorted({r.id for r in retailers if sum(x.id == r.id for x in retailers) > 1})
    if dup:
        msg = f"retailer {dup} is in more than one slice"
        raise CompositionError(msg)
    dates = tuple(sorted({d for s in slices for d in s.meta.dates}))
    products: dict[str, ProductV3] = {}
    merged: set[str] = set()
    for s in slices:
        index = [dates.index(d) for d in s.meta.dates]
        for product in s.products:
            offers = {cid: _reindexed(o, index, len(dates)) for cid, o in product.offers.items()}
            held = products.get(product.id)
            if held is None:
                products[product.id] = product.model_copy(update={"offers": offers})
                continue
            merged.add(product.id)
            products[product.id] = held.model_copy(
                update={
                    "offers": {**held.offers, **offers},
                    "matches": _union(held.matches, product.matches),
                }
            )
    metas = [s.meta for s in slices]
    meta = first.model_copy(
        update={
            "cutoff": max(m.cutoff for m in metas),
            "generated_at": max(m.generated_at for m in metas),
            "markets": _markets(metas),
            "retailers": tuple(retailers),
            "dates": dates,
            "match_stage": "+".join(dict.fromkeys(m.match_stage for m in metas)),
            "capabilities": _capabilities(metas),
            "fields": _fields(metas),
            "producer": PRODUCER,
            "test": any(m.test for m in metas),
            "contexts": tuple(c for m in metas for c in m.contexts),
        }
    )
    dataset = DatasetV3(
        schema_id="pi.dataset/v3",
        meta=meta,
        products=tuple(products.values()),
        not_observed=tuple(w for s in slices for w in s.not_observed),
    )
    return Composed(
        dataset=dataset,
        sources=tuple(i for s in slices for i in source_infos(s)),
        merged_ids=tuple(sorted(merged)),
    )


def _check_same_scope(a: MetaV3, b: MetaV3) -> None:
    for name in ("kind", "scope", "vertical", "profile", "attribute_set"):
        if getattr(a, name) != getattr(b, name):
            msg = f"slices differ in meta.{name}"
            raise CompositionError(msg)


def _markets(metas: Sequence[MetaV3]) -> tuple[MarketInfo, ...]:
    by_country: dict[str, MarketInfo] = {}
    for market in (m for meta in metas for m in meta.markets):
        held = by_country.get(market.country)
        if held is None:
            by_country[market.country] = market
        elif (held.currency, held.time_zone) != (market.currency, market.time_zone):
            msg = f"market {market.country} has another currency or time zone in another slice"
            raise CompositionError(msg)
        else:
            locales = tuple(dict.fromkeys((*held.locales, *market.locales)))
            by_country[market.country] = held.model_copy(update={"locales": locales})
    return tuple(by_country.values())


def _capabilities(metas: Sequence[MetaV3]) -> Capabilities:
    names = Capabilities.model_fields
    return Capabilities(**{n: any(getattr(m.capabilities, n) for m in metas) for n in names})


def _fields(metas: Sequence[MetaV3]) -> dict[str, FieldStatus]:
    keys = dict.fromkeys(k for m in metas for k in m.fields)
    out: dict[str, FieldStatus] = {}
    for key in keys:
        states = {m.fields.get(key, FieldStatus.NOT_COLLECTED) for m in metas}
        out[key] = states.pop() if len(states) == 1 else FieldStatus.PARTIAL
    return out


def _union(a: tuple[MatchEdge, ...], b: tuple[MatchEdge, ...]) -> tuple[MatchEdge, ...]:
    held = {(e.a, e.b) for e in a}
    return (*a, *(e for e in b if (e.a, e.b) not in held))


def _reindexed(offer: OfferV3, index: list[int], n: int) -> OfferV3:
    """The offer's series on ``n`` dates, entry ``k`` moved to ``index[k]``; null elsewhere."""
    if index == list(range(n)):
        return offer

    def spread[T](values: tuple[T | None, ...] | None) -> tuple[T | None, ...] | None:
        if values is None:
            return None
        out: list[T | None] = [None] * n
        for k, value in zip(index, values, strict=True):
            out[k] = value
        return tuple(out)

    s = offer.series
    series = s.model_copy(
        update={
            "price": spread(s.price),
            "regular": spread(s.regular),
            "availability": spread(s.availability),
        }
    )
    return offer.model_copy(update={"series": series})
