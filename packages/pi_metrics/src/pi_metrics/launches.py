"""First-seen items (design §6 ``/v1/launches``).

A product is a launch at a retailer on date *d* only if it wasn't seen there before *d* and
that retailer's crawl on the previous date was complete for its category. First-seen on the
first date is never a launch. First-seen after an incomplete run is withheld and counted in a
caveat: the catalogue simply wasn't observed.
"""

from __future__ import annotations

from datetime import date

from pi_dataset import ContractModel
from pi_metrics import view
from pi_metrics.model import (
    EVERY_PROFILE,
    Caveat,
    CaveatCode,
    Metric,
    ProductFilter,
    Reason,
    Status,
)

#: The profiles launches apply to (ADR-0008 §3).
PROFILES = EVERY_PROFILE


class Launch(ContractModel):
    id: str
    name: str
    #: The context id; a retailer's sole context has the retailer's id.
    retailer: str
    first_seen: date


class Launches(ContractModel):
    items: tuple[Launch, ...]
    #: Rows before any ``limit``; ``truncated`` says the list was cut to it (pi_api).
    total: int
    truncated: bool = False


def launches(
    dataset: view.AnyDataset,
    retailers: tuple[str, ...],
    where: ProductFilter,
    since: date | None = None,
) -> Metric[Launches]:
    """First-seen items per context; ``retailers`` are context ids, empty means every context."""
    ds = view.as_v3(dataset)
    selected = view.selected_contexts(ds, retailers)
    as_of = ds.meta.dates[-1]
    off = None
    if not view.applies(ds, PROFILES):
        off = Reason.NOT_APPLICABLE
    elif not ds.meta.capabilities.history or len(ds.meta.dates) < 2:
        off = Reason.CAPABILITY_OFF
    if off is not None:
        return Metric[Launches](
            status=Status.NOT_ENOUGH_DATA,
            data=Launches(items=(), total=0),
            reason=off,
            as_of=as_of,
        )
    items, withheld = [], 0
    for product in view.products(ds, where):
        for shop in selected:
            offer = view.collected(product, shop.id)
            if offer is None:
                continue
            first = next((i for i in range(len(ds.meta.dates)) if view.seen(offer, i)), None)
            if first is None or first == 0:
                continue
            day = ds.meta.dates[first]
            if since is not None and day < since:
                continue
            if not view.complete_run(ds, shop.id, product, first - 1):
                withheld += 1
                continue
            items.append(Launch(id=product.id, name=product.name, retailer=shop.id, first_seen=day))
    items.sort(key=lambda item: (item.first_seen, item.retailer, item.id), reverse=False)
    caveats = (
        (Caveat(code=CaveatCode.LAUNCHES_WITHHELD, params={"count": str(withheld)}),)
        if withheld
        else ()
    )
    return Metric[Launches](
        status=Status.OK,
        data=Launches(items=tuple(items), total=len(items)),
        caveats=caveats,
        as_of=as_of,
    )
