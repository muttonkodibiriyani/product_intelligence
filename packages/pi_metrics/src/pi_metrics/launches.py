"""First-seen items (design §6 ``/v1/launches``).

A product is a launch at a retailer on date *d* only if it wasn't seen there before *d* and
that retailer's crawl on the previous date was complete for its category. First-seen on the
first date is never a launch. First-seen after an incomplete run is withheld and counted in a
caveat: the catalogue simply wasn't observed.
"""

from __future__ import annotations

from datetime import date

from pi_dataset import ContractModel, Dataset
from pi_metrics import view
from pi_metrics.model import Caveat, CaveatCode, Metric, ProductFilter, Reason, Status


class Launch(ContractModel):
    id: str
    name: str
    retailer: str
    first_seen: date


class Launches(ContractModel):
    items: tuple[Launch, ...]


def launches(
    ds: Dataset,
    retailers: tuple[str, ...],
    where: ProductFilter,
    since: date | None = None,
) -> Metric[Launches]:
    selected = view.selected_retailers(ds, retailers)
    as_of = ds.meta.dates[-1]
    if not ds.meta.capabilities.history or len(ds.meta.dates) < 2:
        return Metric[Launches](
            status=Status.NOT_ENOUGH_DATA,
            data=Launches(items=()),
            reason=Reason.CAPABILITY_OFF,
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
        status=Status.OK, data=Launches(items=tuple(items)), caveats=caveats, as_of=as_of
    )
