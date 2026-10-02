"""Per-source snapshots composed into one same-scope view (ADR-0010).

Each source (a retailer id) is assigned one snapshot file. :func:`only` takes from a file just
the assigned sources: their retailer entries, contexts, offers, ``notObserved`` windows and the
match edges between two of them. :func:`compose` joins those slices into one ``DatasetV3``:

* every slice has the same scope, vertical, profile and attribute set, and a market shared by
  two slices has one currency and time zone, else :class:`CompositionError`;
* the dates are the union of the slices'; a source's series are null on a date its file lacks,
  and a retailer-wide ``notObserved`` window covers each run of such dates, so the date never
  backs an absence claim (a launch, a removal or a gap) and is never carried forward;
* a product id in two slices is one product: its offers are the union (a source's contexts are
  its own, so offers never collide), and the merge is reported in :attr:`Composed.merged_ids`.
  Merging by id assumes canonical, source-disjoint ids: the exporter derives one id per product
  token, whichever source offers it. No source owns a product id, so its product fields (brand,
  name, category, ...) come from the slice that sorts first by its smallest retailer id, whatever
  the order the slices are given in;
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
from pi_dataset.v3 import DatasetV3, MetaV3, NotObservedV3, OfferV3, ProductV3

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
    """One entry per retailer of ``ds``, each with the file's own meta, except ``cutoff``: the
    latest ``capturedAt`` of the retailer's own offers (the file's cutoff if it has none), so a
    file holding several retailers never gives one of them another's later capture."""
    retailer_of = {c.id: c.retailer for c in ds.meta.contexts}
    products: dict[str, int] = {r.id: 0 for r in ds.meta.retailers}
    latest: dict[str, datetime] = {}
    for product in ds.products:
        for retailer in {retailer_of[cid] for cid in product.offers}:
            products[retailer] += 1
        for cid, offer in product.offers.items():
            at, retailer = offer.evidence.captured_at, retailer_of[cid]
            latest[retailer] = max(latest.get(retailer, at), at)
    m = ds.meta
    return tuple(
        SourceInfo(
            source=r.id,
            cutoff=latest.get(r.id, m.cutoff),
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
    slices = sorted(slices, key=lambda s: min(r.id for r in s.meta.retailers))
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
        not_observed=tuple(w for s in slices for w in (*s.not_observed, *_outside(s.meta, dates))),
    )
    return Composed(
        dataset=dataset,
        sources=tuple(i for s in slices for i in source_infos(s)),
        merged_ids=tuple(sorted(merged)),
    )


@dataclass(frozen=True)
class Latest:
    """A view for latest-date reads, with each stale source read at its own last date."""

    dataset: DatasetV3
    #: The sources whose own last date is before the view's, in view order.
    stale: tuple[SourceInfo, ...]


def latest(composed: Composed) -> Latest:
    """``composed`` as of each source's own latest observation (ADR-0010).

    A stale source's file ends before the view's last date, so its series are null there and a
    retailer-wide window covers them. For latest-date reads (a comparison, promotions, the
    summary, current prices) the stale source is read at its own last date instead: the value of
    every series of its offers on that date is put on the view's last date, and the view's last
    date is under exactly the ``notObserved`` windows that cover the source's last date. Callers
    say so with a ``stale_source`` caveat. History, launches and assortment gaps read the view
    itself: a stale value never backs a trend or an absence claim.
    """
    ds = composed.dataset
    dates = ds.meta.dates
    stale = tuple(s for s in composed.sources if s.last_date < dates[-1])
    if not stale:
        return Latest(ds, ())
    at = {s.source: dates.index(s.last_date) for s in stale}
    by_context = {c.id: at[c.retailer] for c in ds.meta.contexts if c.retailer in at}
    products = tuple(_restamped(p, by_context) for p in ds.products)
    windows = [w for old in ds.not_observed for w in _rewindowed(old, dates, at.get(old.retailer))]
    dataset = ds.model_copy(update={"products": products, "not_observed": tuple(windows)})
    return Latest(dataset, stale)


def _restamped(product: ProductV3, at: dict[str, int]) -> ProductV3:
    if not at.keys() & product.offers.keys():
        return product
    offers = {
        cid: offer if cid not in at else _offer_at(offer, at[cid])
        for cid, offer in product.offers.items()
    }
    return product.model_copy(update={"offers": offers})


def _offer_at(offer: OfferV3, k: int) -> OfferV3:
    def at_last[T](values: tuple[T, ...] | None) -> tuple[T, ...] | None:
        return None if values is None else (*values[:-1], values[k])

    s = offer.series
    series = s.model_copy(
        update={
            "price": at_last(s.price),
            "regular": at_last(s.regular),
            "availability": at_last(s.availability),
        }
    )
    return offer.model_copy(update={"series": series})


def _rewindowed(w: NotObservedV3, dates: tuple[date, ...], k: int | None) -> list[NotObservedV3]:
    """``w`` off the view's last date, and on it again if it covers the source's own last date."""
    if k is None:
        return [w]
    last, before = dates[-1], dates[-2]
    kept = [w]
    if w.end >= last:
        kept = [] if w.start > before else [w.model_copy(update={"end": before})]
    if w.start <= dates[k] <= w.end:
        kept.append(w.model_copy(update={"start": last, "end": last}))
    return kept


def _outside(meta: MetaV3, dates: tuple[date, ...]) -> list[NotObservedV3]:
    """Retailer-wide windows over each run of view dates that the slice's file lacks."""
    own = set(meta.dates)
    runs: list[list[date]] = []
    for k, day in enumerate(dates):
        if day in own:
            continue
        if runs and dates[k - 1] == runs[-1][-1]:
            runs[-1].append(day)
        else:
            runs.append([day])
    first, last = meta.dates[0], meta.dates[-1]
    why = {
        "en": f"Not in this source's file, which covers {first} to {last}.",
        "ar": f"خارج تواريخ ملف هذا المصدر ({first} إلى {last}).",
    }
    return [
        NotObservedV3(
            retailer=r.id, start=run[0], end=run[-1], categories=None, why=why, context=None
        )
        for r in meta.retailers
        for run in runs
    ]


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
