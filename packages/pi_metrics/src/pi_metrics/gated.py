"""Gated ML models: what each one would need, counted from the snapshot (docs/design/ml-layer.md).

There are no ML models yet. This module only says, honestly, why each one is locked: the
answer is always ``state = "needs_data"`` with the inputs it needs and how many the snapshot
has. The type has no field that could carry a prediction, and there is no other state; a model
that becomes ready adds its own reviewed state and endpoint (ml-layer.md §4).

``have`` is counted from the dataset where the dataset can show it (history snapshots,
retailers with collected prices). Inputs the platform has no source for yet (internal cost and
sales, ANL-14; analyst labels; a passing backtest) are ``0``; never estimated.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pi_dataset import ContractModel, DatasetV3
from pi_dataset.models import RetailerStatus
from pi_metrics import view

#: The ML layer's version of the thresholds below; bump when a ``required`` changes.
GATES_VERSION = "2026-10-01.1"


class ModelId(StrEnum):
    PRICE_CHANGE_DETECTION = "price_change_detection"
    ELASTICITY = "elasticity"
    FORECAST = "forecast"
    OPTIMAL_PRICE = "optimal_price"


class NeedKind(StrEnum):
    #: Daily snapshots in the dataset's date series (``meta.dates``).
    HISTORY_SNAPSHOTS = "history_snapshots"
    #: Supported retailers in the market with at least one collected price.
    RETAILERS = "retailers"
    #: Internal unit cost at product-location-day grain (ANL-14). No source yet.
    INTERNAL_COST = "internal_cost"
    #: Internal sales at product-location-day grain, in days of history (ANL-14). No source yet.
    INTERNAL_SALES = "internal_sales"
    #: Analyst dispositions on flagged movements (ANL-13). No source yet.
    ANALYST_LABELS = "analyst_labels"
    #: A recorded backtest that beats the naive baseline (ANL-15). None yet.
    BACKTEST = "backtest"
    #: A credible experiment or causal control design for the period (ANL-16). None yet.
    EXPERIMENT = "experiment"
    #: Another gated model this one builds on, in ``ready`` state. None is.
    UPSTREAM_MODEL = "upstream_model"


class Need(ContractModel):
    kind: NeedKind
    required: int
    have: int
    #: For ``upstream_model``: which model.
    model: ModelId | None = None


class Gated(ContractModel):
    """A locked model card. ``needs_data`` is the only state (ml-layer.md §4)."""

    state: Literal["needs_data"] = "needs_data"
    model: ModelId
    #: Requirement IDs this model answers (traceability.csv); KPI IDs are a TODO (ml-layer.md §6).
    requirements: tuple[str, ...]
    needs: tuple[Need, ...]
    gates_version: str = GATES_VERSION


#: (kind, required, upstream) per model; ml-layer.md §3 gives the reason for each number.
_GATES: dict[ModelId, tuple[tuple[str, ...], tuple[tuple[NeedKind, int, ModelId | None], ...]]] = {
    ModelId.PRICE_CHANGE_DETECTION: (
        ("ANL-06", "ANL-13"),
        (
            (NeedKind.HISTORY_SNAPSHOTS, 28, None),
            (NeedKind.ANALYST_LABELS, 200, None),
            (NeedKind.BACKTEST, 1, None),
        ),
    ),
    ModelId.ELASTICITY: (
        ("ANL-14", "ANL-16"),
        (
            (NeedKind.HISTORY_SNAPSHOTS, 365, None),
            (NeedKind.RETAILERS, 2, None),
            (NeedKind.INTERNAL_SALES, 365, None),
            (NeedKind.EXPERIMENT, 1, None),
            (NeedKind.BACKTEST, 1, None),
        ),
    ),
    ModelId.FORECAST: (
        ("ANL-15",),
        (
            (NeedKind.HISTORY_SNAPSHOTS, 90, None),
            (NeedKind.BACKTEST, 1, None),
        ),
    ),
    ModelId.OPTIMAL_PRICE: (
        ("ANL-14", "ANL-17"),
        (
            (NeedKind.UPSTREAM_MODEL, 1, ModelId.ELASTICITY),
            (NeedKind.INTERNAL_COST, 1, None),
            (NeedKind.INTERNAL_SALES, 365, None),
            (NeedKind.BACKTEST, 1, None),
        ),
    ),
}


def _have(ds: DatasetV3, kind: NeedKind) -> int:
    if kind is NeedKind.HISTORY_SNAPSHOTS:
        return len(ds.meta.dates)
    if kind is NeedKind.RETAILERS:
        priced = {
            view.context(ds, cid).retailer
            for product in ds.products
            for cid, offer in product.offers.items()
            if not offer.early and any(p is not None for p in offer.series.price)
        }
        return sum(
            1
            for shop in ds.meta.retailers
            if shop.id in priced and shop.status is RetailerStatus.SUPPORTED
        )
    # No source on the platform yet (module docstring): zero, never an estimate.
    return 0


def gated(dataset: view.AnyDataset, model: ModelId) -> Gated:
    """The locked card for ``model``, its needs counted from ``dataset``."""
    ds = view.as_v3(dataset)
    requirements, gates = _GATES[model]
    return Gated(
        model=model,
        requirements=requirements,
        needs=tuple(
            Need(kind=kind, required=required, have=_have(ds, kind), model=upstream)
            for kind, required, upstream in gates
        ),
    )


def all_gated(dataset: view.AnyDataset) -> tuple[Gated, ...]:
    return tuple(gated(dataset, model) for model in ModelId)
