"""Stock state counts and shares per retailer (design §6 ``/v1/availability``).

Every ``AvailabilityState`` is counted. Shares use only the observed stock states
(``is_known``: in, low and out of stock) as the denominator. ``not_deliverable`` and ``removed``
are counted outside it, like the unobserved states. A day without an observation is
``not_observed``, never out of stock. ``removed`` stands only after a complete crawl; otherwise
it is reported as ``not_observed`` with a caveat.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pi_core import AvailabilityState
from pi_dataset import ContractModel, Dataset
from pi_dataset.models import RetailerStatus
from pi_metrics import view
from pi_metrics.model import (
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Metric,
    Pct,
    ProductFilter,
    Reason,
    Status,
)

DENOMINATOR = "offers in an observed stock state (in_stock, low_stock, out_of_stock)"


class RetailerAvailability(ContractModel):
    retailer: str
    counts: dict[AvailabilityState, int]
    denominator: int
    out_of_stock_share: Pct | None
    low_stock_share: Pct | None
    reason: Reason | None


class Availability(ContractModel):
    retailers: tuple[RetailerAvailability, ...]
    denominator: str = DENOMINATOR


def availability(
    ds: Dataset,
    retailers: tuple[str, ...],
    where: ProductFilter,
    on: date | None = None,
) -> Metric[Availability]:
    selected = view.selected_retailers(ds, retailers)
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    if not ds.meta.capabilities.stock:
        return Metric[Availability](
            status=Status.NOT_ENOUGH_DATA,
            data=Availability(retailers=()),
            reason=Reason.CAPABILITY_OFF,
            as_of=as_of,
        )
    rows, caveats = [], []
    for shop in selected:
        counts = dict.fromkeys(AvailabilityState, 0)
        unconfirmed = 0
        for product in view.products(ds, where):
            offer = view.collected(product, shop.id)
            if offer is None:
                continue
            states = offer.series.availability
            state = (states[i] if states is not None else None) or AvailabilityState.NOT_OBSERVED
            if state is AvailabilityState.REMOVED and not view.complete_run(
                ds, shop.id, product, i
            ):
                state = AvailabilityState.NOT_OBSERVED
                unconfirmed += 1
            counts[state] += 1
        if unconfirmed:
            caveats.append(
                Caveat(
                    code=CaveatCode.REMOVED_UNCONFIRMED,
                    params={"retailer": shop.id, "count": str(unconfirmed)},
                )
            )
        known = sum(n for state, n in counts.items() if state.is_known)
        reason = {
            RetailerStatus.BLOCKED: Reason.RETAILER_BLOCKED,
            RetailerStatus.PARTIAL: Reason.RETAILER_PARTIAL,
        }.get(shop.status)
        if reason is None and known < MIN_COHORT:
            reason = Reason.COHORT_TOO_SMALL
        rows.append(
            RetailerAvailability(
                retailer=shop.id,
                counts=counts,
                denominator=known,
                out_of_stock_share=None
                if reason
                else Decimal(counts[AvailabilityState.OUT_OF_STOCK]) / known * 100,
                low_stock_share=None
                if reason
                else Decimal(counts[AvailabilityState.LOW_STOCK]) / known * 100,
                reason=reason,
            )
        )
    reason = next((r.reason for r in rows if r.reason is not None), None)
    return Metric[Availability](
        status=Status.OK if reason is None else Status.NOT_ENOUGH_DATA,
        data=Availability(retailers=tuple(rows)),
        reason=reason,
        caveats=tuple(caveats),
        as_of=as_of,
    )
