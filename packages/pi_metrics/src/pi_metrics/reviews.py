"""Rating summary per retailer (design §6 ``/v1/reviews-summary``).

``avgRating`` is the count-weighted mean of the products' published averages, on the retailer's
own scale (never rescaled). If a retailer publishes several scales, only its most common scale is
used and the rest are counted in a caveat. Products with no ratings (count 0) are not averaged.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from pi_core import PiModel
from pi_dataset import Dataset, Rating
from pi_dataset.models import FieldStatus
from pi_metrics import view
from pi_metrics.model import (
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Metric,
    ProductFilter,
    RatingValue,
    Reason,
    Status,
)


class RetailerReviews(PiModel):
    retailer: str
    n: int
    avg_rating: RatingValue | None
    rating_count: int
    scale: str | None
    reason: Reason | None


class ReviewsSummary(PiModel):
    retailers: tuple[RetailerReviews, ...]


def _summary(retailer: str, ratings: list[Rating]) -> tuple[RetailerReviews, int]:
    scales = Counter(Decimal(r.scale) for r in ratings)
    scale = min(scales, key=lambda s: (-scales[s], s)) if scales else None
    used = [r for r in ratings if Decimal(r.scale) == scale]
    count = sum(r.count for r in used)
    enough = len(used) >= MIN_COHORT
    average = (
        sum((Decimal(r.average) * r.count for r in used), Decimal(0)) / count if enough else None
    )
    return (
        RetailerReviews(
            retailer=retailer,
            n=len(used),
            avg_rating=average,
            rating_count=count,
            scale=None if scale is None else str(scale),
            reason=None if enough else Reason.COHORT_TOO_SMALL,
        ),
        len(ratings) - len(used),
    )


def reviews_summary(
    ds: Dataset, retailers: tuple[str, ...], where: ProductFilter
) -> Metric[ReviewsSummary]:
    selected = view.selected_retailers(ds, retailers)
    as_of = ds.meta.dates[-1]
    off = None
    if not ds.meta.capabilities.ratings:
        off = Reason.CAPABILITY_OFF
    elif ds.meta.fields.get("rating", FieldStatus.NOT_COLLECTED) is FieldStatus.NOT_COLLECTED:
        off = Reason.FIELD_NOT_COLLECTED
    if off is not None:
        return Metric[ReviewsSummary](
            status=Status.NOT_ENOUGH_DATA,
            data=ReviewsSummary(retailers=()),
            reason=off,
            as_of=as_of,
        )
    rows, caveats = [], []
    for shop in selected:
        ratings = [
            offer.rating
            for product in view.products(ds, where)
            if (offer := view.collected(product, shop.id)) is not None
            and offer.rating is not None
            and offer.rating.count > 0
        ]
        row, dropped = _summary(shop.id, ratings)
        rows.append(row)
        if dropped:
            caveats.append(
                Caveat(
                    code=CaveatCode.RATING_SCALE_MIXED,
                    params={"retailer": shop.id, "count": str(dropped)},
                )
            )
    reason = next((r.reason for r in rows if r.reason is not None), None)
    return Metric[ReviewsSummary](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=ReviewsSummary(retailers=tuple(rows)),
        reason=reason,
        caveats=tuple(caveats),
        as_of=as_of,
    )
