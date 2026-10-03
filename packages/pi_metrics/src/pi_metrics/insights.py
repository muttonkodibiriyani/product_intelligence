"""Decision insights: brand price policy, price gaps by size, and size-ladder value.

Three aggregates for the Insights page, each over rules the other metrics already own:

* **Brand price policy** groups ``compare``'s counted pairs (exact, approved or locked, same
  size, one currency) by brand. A brand with at least ``MIN_COHORT`` counted pairs is labelled
  by where at least ``POLICY_SHARE`` % of them fall: ``other_cheaper``, ``base_cheaper`` or
  ``parity`` (equal price); otherwise ``mixed``. The label describes the observed prices, not
  anyone's intent.
* **Gap by size** groups the same counted pairs by the base offer's published measure
  (``90 ml``). A pair without a measure is not grouped; sizes below ``MIN_COHORT`` are counted
  in ``suppressed``.
* **Size ladders** stay inside one context: consecutive measures of one product family, where
  the larger size should cost less per unit. The family is the retailer's own
  ``content.family`` when published (``basis = family``); otherwise products with the same
  brand, name, top-level category and unit (``basis = name``), a weaker grouping the response
  says it used. A family with two offers at one measure is skipped as ambiguous. A step whose
  larger size costs more than ``HELD_OUT_PCT`` % more per unit is held out as two products
  sharing a name, and counted.

No cross-retailer number comes from an unreviewed match: when no pair is counted the pricing
parts say ``matches_unreviewed`` (or why else) and carry no rows.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from pi_dataset import ContractModel, DatasetV3, MoneyValue, ProductV3
from pi_dataset.models import RetailerStatus
from pi_metrics import view
from pi_metrics.compare import GroupBy, PairRow, compare
from pi_metrics.model import (
    EVERY_PROFILE,
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Cheaper,
    Cohort,
    Excluded,
    Metric,
    Pct,
    ProductFilter,
    Reason,
    Status,
)

#: Share of a brand's counted pairs (in %) that must agree for a policy label.
POLICY_SHARE = Decimal(80)
#: A larger size this much dearer per unit (in %) is held out as a different product.
HELD_OUT_PCT = Decimal(50)
#: The most ladder exceptions listed per context; ``not_cheaper`` counts them all.
EXCEPTIONS_LISTED = 12
PROFILES = EVERY_PROFILE


class Policy(StrEnum):
    OTHER_CHEAPER = "other_cheaper"
    BASE_CHEAPER = "base_cheaper"
    PARITY = "parity"
    MIXED = "mixed"


class BrandPolicy(ContractModel):
    brand: str
    n: int
    policy: Policy
    median_gap_pct: Pct
    base_cheaper: int
    other_cheaper: int
    equal: int


class SizeGap(ContractModel):
    value: str
    unit: str
    n: int
    median_gap_pct: Pct
    base_cheaper: int
    other_cheaper: int
    equal: int


class PairInsights(ContractModel):
    base: str
    other: str
    #: Counted pairs (exact, approved or locked, same size, priced on the date).
    n: int
    #: Pairs with a proposed (unreviewed) edge: shown so the gap to a counted answer is visible.
    unreviewed: int
    status: Status
    reason: Reason | None
    brands: tuple[BrandPolicy, ...]
    sizes: tuple[SizeGap, ...]
    #: Brands or sizes with 1..MIN_COHORT-1 counted pairs, withheld.
    suppressed_brands: int
    suppressed_sizes: int


class LadderBasis(StrEnum):
    FAMILY = "family"
    NAME = "name"


class LadderStep(ContractModel):
    family: str
    brand: str
    name: str
    smaller_id: str
    larger_id: str
    unit: str
    smaller_value: str
    larger_value: str
    smaller_price: MoneyValue
    larger_price: MoneyValue
    #: Per-unit price change from the smaller to the larger size; >= 0 means no saving.
    unit_change_pct: Pct
    basis: LadderBasis


class Ladder(ContractModel):
    retailer: str
    steps: int
    not_cheaper: int
    held_out: int
    median_saving_pct: Pct | None
    reason: Reason | None
    #: The ``not_cheaper`` steps, largest per-unit rise first, at most ``EXCEPTIONS_LISTED``.
    exceptions: tuple[LadderStep, ...]


class Insights(ContractModel):
    pricing: PairInsights
    ladders: tuple[Ladder, ...]
    policy_share_pct: Pct = POLICY_SHARE
    held_out_pct: Pct = HELD_OUT_PCT


def _split(rows: list[PairRow]) -> tuple[int, int, int]:
    cheaper = [r.gap.cheaper for r in rows if r.gap is not None]
    return cheaper.count(Cheaper.BASE), cheaper.count(Cheaper.OTHER), cheaper.count(Cheaper.EQUAL)


def _median(rows: list[PairRow]) -> Decimal:
    return statistics.median(sorted(r.gap.pct for r in rows if r.gap is not None))


def policy(base_cheaper: int, other_cheaper: int, equal: int) -> Policy:
    """The label at least ``POLICY_SHARE`` % of the pairs agree on, else ``mixed``."""
    n = base_cheaper + other_cheaper + equal
    for label, count in (
        (Policy.OTHER_CHEAPER, other_cheaper),
        (Policy.BASE_CHEAPER, base_cheaper),
        (Policy.PARITY, equal),
    ):
        if n and Decimal(count) * 100 >= POLICY_SHARE * n:
            return label
    return Policy.MIXED


def _brands(counted: list[PairRow]) -> tuple[tuple[BrandPolicy, ...], int]:
    by: defaultdict[str, list[PairRow]] = defaultdict(list)
    for row in counted:
        by[row.brand].append(row)
    out, suppressed = [], 0
    for brand, rows in by.items():
        if len(rows) < MIN_COHORT:
            suppressed += 1
            continue
        b, o, e = _split(rows)
        out.append(
            BrandPolicy(
                brand=brand,
                n=len(rows),
                policy=policy(b, o, e),
                median_gap_pct=_median(rows),
                base_cheaper=b,
                other_cheaper=o,
                equal=e,
            )
        )
    out.sort(key=lambda r: (r.median_gap_pct, -r.n, r.brand))
    return tuple(out), suppressed


def _sizes(ds: DatasetV3, counted: list[PairRow], base: str) -> tuple[tuple[SizeGap, ...], int]:
    by: defaultdict[tuple[str, Decimal], list[PairRow]] = defaultdict(list)
    for row in counted:
        size = view.product_v3(ds, row.id).offers[base].size
        if size is not None and size.value is not None and size.unit is not None:
            by[(size.unit.casefold(), Decimal(size.value).normalize())].append(row)
    out, suppressed = [], 0
    for (unit, value), rows in sorted(by.items()):
        if len(rows) < MIN_COHORT:
            suppressed += 1
            continue
        b, o, e = _split(rows)
        out.append(
            SizeGap(
                value=f"{value:f}",
                unit=unit,
                n=len(rows),
                median_gap_pct=_median(rows),
                base_cheaper=b,
                other_cheaper=o,
                equal=e,
            )
        )
    return tuple(out), suppressed


def _pricing(ds: DatasetV3, base: str, other: str, on: date | None) -> PairInsights:
    result = compare(ds, base, other, ProductFilter(), on=on, group_by=GroupBy.BRAND)
    rows = result.data.rows
    counted = [r for r in rows if r.counted and r.gap is not None]
    brands, quiet_brands = _brands(counted)
    sizes, quiet_sizes = _sizes(ds, counted, base)
    return PairInsights(
        base=base,
        other=other,
        n=len(counted),
        unreviewed=sum(1 for r in rows if r.excluded_reason is Excluded.MATCH_UNREVIEWED),
        status=result.status,
        reason=result.reason,
        brands=brands if result.status is Status.OK else (),
        sizes=sizes if result.status is Status.OK else (),
        suppressed_brands=quiet_brands,
        suppressed_sizes=quiet_sizes,
    )


type _Rung = tuple[Decimal, ProductV3, MoneyValue]


def _families(
    ds: DatasetV3, context: str, i: int
) -> dict[tuple[str, ...], tuple[LadderBasis, str, list[_Rung]]]:
    families: dict[tuple[str, ...], tuple[LadderBasis, str, list[_Rung]]] = {}
    for product in ds.products:
        offer = view.collected(product, context)
        if offer is None or offer.early or offer.size is None:
            continue
        price = view.price_on(offer, i)
        value, unit = offer.size.value, offer.size.unit
        if price is None or value is None or unit is None or Decimal(value) <= 0:
            continue
        family = offer.content.family if offer.content is not None else None
        if family is not None:
            key: tuple[str, ...] = ("family", family, unit.casefold())
            basis = LadderBasis.FAMILY
        else:
            names = (product.brand, product.name, product.category[0], unit)
            key = ("name", *(view.fold(x) for x in names))
            basis = LadderBasis.NAME
        families.setdefault(key, (basis, family or product.name, []))[2].append(
            (Decimal(value), product, price)
        )
    return families


def _ladder(ds: DatasetV3, context: str, i: int) -> Ladder:
    status = view.status(ds, context)
    if status is RetailerStatus.BLOCKED:
        return Ladder(
            retailer=context,
            steps=0,
            not_cheaper=0,
            held_out=0,
            median_saving_pct=None,
            reason=Reason.RETAILER_BLOCKED,
            exceptions=(),
        )
    steps: list[LadderStep] = []
    held_out = 0
    for basis, label, rungs in _families(ds, context, i).values():
        values = [v for v, _, _ in rungs]
        if len(values) < 2 or len(set(values)) != len(values):
            continue
        rungs.sort(key=lambda r: r[0])
        for (sv, sp, sm), (lv, lp, lm) in pairwise(rungs):
            change = (lm.decimal() / lv) / (sm.decimal() / sv) * 100 - 100
            if change > HELD_OUT_PCT:
                held_out += 1
                continue
            offer = sp.offers[context]
            steps.append(
                LadderStep(
                    family=label,
                    brand=sp.brand,
                    name=sp.name,
                    smaller_id=sp.id,
                    larger_id=lp.id,
                    unit=offer.size.unit if offer.size and offer.size.unit else "",
                    smaller_value=f"{sv.normalize():f}",
                    larger_value=f"{lv.normalize():f}",
                    smaller_price=sm,
                    larger_price=lm,
                    unit_change_pct=change,
                    basis=basis,
                )
            )
    bad = sorted((s for s in steps if s.unit_change_pct >= 0), key=_steepest)
    enough = len(steps) >= MIN_COHORT
    return Ladder(
        retailer=context,
        steps=len(steps),
        not_cheaper=len(bad),
        held_out=held_out,
        median_saving_pct=-statistics.median(sorted(s.unit_change_pct for s in steps))
        if enough
        else None,
        reason=None if enough else Reason.COHORT_TOO_SMALL,
        exceptions=tuple(bad[:EXCEPTIONS_LISTED]),
    )


def _steepest(step: LadderStep) -> tuple[Decimal, str]:
    return (-step.unit_change_pct, step.larger_id)


def insights(
    dataset: view.AnyDataset, base: str, other: str, *, on: date | None = None
) -> Metric[Insights]:
    """The pricing insights for context pair ``base``/``other`` and every context's ladder."""
    ds = view.as_v3(dataset)
    if base == other:
        msg = "the two retailers must differ"
        raise view.UnknownInput(msg)
    view.context(ds, base)
    view.context(ds, other)
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    if not view.applies(ds, PROFILES) or not ds.meta.capabilities.sizes:
        reason = Reason.NOT_APPLICABLE if not view.applies(ds, PROFILES) else Reason.CAPABILITY_OFF
        empty = PairInsights(
            base=base,
            other=other,
            n=0,
            unreviewed=0,
            status=Status.NOT_ENOUGH_DATA,
            reason=reason,
            brands=(),
            sizes=(),
            suppressed_brands=0,
            suppressed_sizes=0,
        )
        return Metric[Insights](
            status=Status.NOT_ENOUGH_DATA,
            data=Insights(pricing=empty, ladders=()),
            reason=reason,
            as_of=as_of,
        )
    pricing = _pricing(ds, base, other, on)
    ladders = tuple(_ladder(ds, c.id, i) for c in ds.meta.contexts)
    caveats = tuple(
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": c.id})
        for c in ds.meta.contexts
        if view.status(ds, c.id) is RetailerStatus.PARTIAL
    )
    ok = pricing.status is Status.OK or any(ladder.reason is None for ladder in ladders)
    return Metric[Insights](
        status=Status.OK if ok else Status.NOT_ENOUGH_DATA,
        data=Insights(pricing=pricing, ladders=ladders),
        reason=None if ok else pricing.reason,
        cohort=Cohort(description="counted exact pairs, approved or locked", n=pricing.n),
        caveats=caveats,
        as_of=as_of,
    )
