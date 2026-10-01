"""Assortment gaps: present at one retailer, absent at another (design §6, §7.3).

An absence claim needs a complete crawl at the "missing at" retailer (``view.complete_run``).
A product that retailer didn't observe is never reported absent; it is counted in a caveat.
Grouping is not identity, so a product with no offer at ``missing_at`` may still be sold there
under another product id. Rows are therefore ``unmatched`` unless the dataset's matching stage
is ``reviewed``, and only then ``missing``.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from enum import StrEnum

from pi_dataset import ContractModel
from pi_dataset.models import RetailerStatus
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

REVIEWED_STAGE = "reviewed"
#: The profiles assortment gaps apply to (ADR-0008 §3).
PROFILES = EVERY_PROFILE


class GapLabel(StrEnum):
    MISSING = "missing"
    UNMATCHED = "unmatched"


class GapItem(ContractModel):
    id: str
    brand: str
    name: str
    category: tuple[str, ...]
    label: GapLabel


class BrandCount(ContractModel):
    brand: str
    count: int


class AssortmentGaps(ContractModel):
    missing_at: str
    present_at: str
    total: int
    by_brand: tuple[BrandCount, ...]
    items: tuple[GapItem, ...]


def assortment_gaps(
    dataset: view.AnyDataset,
    missing_at: str,
    present_at: str,
    where: ProductFilter,
    on: date | None = None,
) -> Metric[AssortmentGaps]:
    """Products offered at context ``present_at`` and absent at context ``missing_at``."""
    ds = view.as_v3(dataset)
    if missing_at == present_at:
        msg = "missingAt and presentAt must be different retailers"
        raise view.UnknownInput(msg)
    status = view.status(ds, missing_at)
    view.context(ds, present_at)
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    empty = AssortmentGaps(
        missing_at=missing_at, present_at=present_at, total=0, by_brand=(), items=()
    )
    if not view.applies(ds, PROFILES):
        return Metric[AssortmentGaps](
            status=Status.NOT_ENOUGH_DATA, data=empty, reason=Reason.NOT_APPLICABLE, as_of=as_of
        )
    if status is not RetailerStatus.SUPPORTED:
        # pending and retired retailers have no complete crawl either: partial, not absent.
        return Metric[AssortmentGaps](
            status=Status.NOT_ENOUGH_DATA,
            data=empty,
            reason=Reason.RETAILER_BLOCKED
            if status is RetailerStatus.BLOCKED
            else Reason.RETAILER_PARTIAL,
            as_of=as_of,
        )
    label = GapLabel.MISSING if ds.meta.match_stage == REVIEWED_STAGE else GapLabel.UNMATCHED
    items, unobserved = [], 0
    for product in view.products(ds, where):
        offer = view.collected(product, present_at)
        if offer is None or not view.seen(offer, i) or missing_at in product.offers:
            continue
        if not view.complete_run(ds, missing_at, product, i):
            unobserved += 1
            continue
        items.append(
            GapItem(
                id=product.id,
                brand=product.brand,
                name=product.name,
                category=product.category,
                label=label,
            )
        )
    brands = Counter(item.brand for item in items)
    caveats = (
        (Caveat(code=CaveatCode.NOT_OBSERVED_EXCLUDED, params={"count": str(unobserved)}),)
        if unobserved
        else ()
    )
    return Metric[AssortmentGaps](
        status=Status.OK,
        data=AssortmentGaps(
            missing_at=missing_at,
            present_at=present_at,
            total=len(items),
            by_brand=tuple(
                BrandCount(brand=b, count=c)
                for b, c in sorted(brands.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            items=tuple(items),
        ),
        caveats=caveats,
        as_of=as_of,
    )
