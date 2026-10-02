"""Fixed-basket price index (design §6 ``/v1/index``, §7.6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pi_dataset import ContractModel, DatasetV3
from pi_metrics import view
from pi_metrics.compare import (
    COHORT_DESCRIPTION,
    PROFILES,
    LabelPair,
    pair_block,
    pair_caveats,
    pair_row,
    pair_with_labels,
)
from pi_metrics.model import (
    MIN_COHORT,
    Cohort,
    IndexValue,
    Metric,
    ProductFilter,
    Reason,
    Status,
)

INDEX_DEFINITION = (
    "index = sum(other price) / sum(base price) x 100 over a fixed basket: the pairs counted on "
    "the first date of the window and still counted on each date. Above 100 means other is "
    "dearer than base. A point with n < 5 is null; there is no interpolation."
)


class IndexPoint(ContractModel):
    date: date
    index: IndexValue | None
    n: int
    reason: Reason | None


class PriceIndex(ContractModel):
    base: str
    other: str
    points: tuple[IndexPoint, ...]
    trend_available: bool
    definition: str = INDEX_DEFINITION


def _window(ds: DatasetV3, start: date | None, end: date | None) -> list[int]:
    if start is not None and end is not None and start > end:
        msg = f"from {start} is after to {end}"
        raise view.UnknownInput(msg)
    window = [
        i
        for i, day in enumerate(ds.meta.dates)
        if (start is None or day >= start) and (end is None or day <= end)
    ]
    if not window:
        msg = "no observation dates in the requested window"
        raise view.UnknownInput(msg)
    return window


def price_index(  # noqa: PLR0913 -- the endpoint filters; window bounds are keyword-only
    dataset: view.AnyDataset,
    base: str,
    other: str,
    where: ProductFilter,
    *,
    start: date | None = None,
    end: date | None = None,
) -> Metric[PriceIndex]:
    """One point per date of the window. Needs ``capabilities.history`` for more than one date.

    ``base`` and ``other`` are context ids, paired as in ``compare``.
    """
    ds = view.as_v3(dataset)
    if base == other:
        msg = "base and other must be different retailers or contexts"
        raise view.UnknownInput(msg)
    view.context(ds, base)
    view.context(ds, other)
    window = _window(ds, start, end)
    as_of = ds.meta.dates[window[-1]]
    off = None
    if not view.applies(ds, PROFILES):
        off = Reason.NOT_APPLICABLE
    elif len(window) > 1 and not ds.meta.capabilities.history:
        off = Reason.CAPABILITY_OFF
    if off is not None:
        return Metric[PriceIndex](
            status=Status.NOT_ENOUGH_DATA,
            data=PriceIndex(base=base, other=other, points=(), trend_available=False),
            reason=off,
            as_of=as_of,
        )
    blocked = pair_block(ds, base, other)
    if blocked is not None:
        return Metric[PriceIndex](
            status=Status.NOT_ENOUGH_DATA,
            data=PriceIndex(base=base, other=other, points=(), trend_available=False),
            reason=blocked,
            as_of=as_of,
        )
    candidates = [p for p in view.products(ds, where) if base in p.offers and other in p.offers]
    basket, labels = [], list[LabelPair]()
    for product in candidates:
        row, pair_labels = pair_with_labels(ds, product, base, other, window[0])
        if row.counted:
            basket.append(product)
            labels += [pair_labels] if pair_labels else []
    points = []
    for i in window:
        rows = [pair_row(ds, p, base, other, i) for p in basket]
        counted = [r for r in rows if r.counted and r.base_price and r.other_price]
        n = len(counted)
        index = None
        if n >= MIN_COHORT:
            base_sum = sum((r.base_price.decimal() for r in counted if r.base_price), Decimal(0))
            other_sum = sum((r.other_price.decimal() for r in counted if r.other_price), Decimal(0))
            index = other_sum / base_sum * 100
        points.append(
            IndexPoint(
                date=ds.meta.dates[i],
                index=index,
                n=n,
                reason=None if index is not None else Reason.COHORT_TOO_SMALL,
            )
        )
    first_n = len(basket)
    return Metric[PriceIndex](
        status=Status.OK if first_n >= MIN_COHORT else Status.NOT_ENOUGH_DATA,
        data=PriceIndex(
            base=base, other=other, points=tuple(points), trend_available=len(points) > 1
        ),
        reason=None if first_n >= MIN_COHORT else Reason.COHORT_TOO_SMALL,
        cohort=Cohort(description=f"fixed basket: {COHORT_DESCRIPTION}", n=first_n),
        caveats=tuple(pair_caveats(ds, base, other, labels)),
        as_of=as_of,
    )
