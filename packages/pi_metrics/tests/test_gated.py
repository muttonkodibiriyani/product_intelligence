"""Gated ML models answer ``needs_data`` only, with needs counted from the snapshot."""

from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from metrics_fixture import metrics_dataset, with_dates
from pi_metrics.gated import Gated, ModelId, NeedKind, all_gated, gated

#: Kinds the platform has no source for yet: always zero, never estimated.
NO_SOURCE = {
    NeedKind.INTERNAL_COST,
    NeedKind.INTERNAL_SALES,
    NeedKind.ANALYST_LABELS,
    NeedKind.BACKTEST,
    NeedKind.EXPERIMENT,
    NeedKind.UPSTREAM_MODEL,
}


def test_every_model_is_locked_with_an_unmet_need() -> None:
    cards = all_gated(metrics_dataset())
    assert [c.model for c in cards] == list(ModelId)
    for card in cards:
        assert card.state == "needs_data"
        assert card.requirements
        assert any(n.have < n.required for n in card.needs), card.model
        # A recorded backtest is a gate for every model; there is none.
        assert any(n.kind is NeedKind.BACKTEST and n.have == 0 for n in card.needs)


def test_have_is_counted_from_the_snapshot() -> None:
    card = gated(metrics_dataset(), ModelId.ELASTICITY)
    have = {n.kind: n.have for n in card.needs}
    # Three dates; shop_a and shop_b are supported with prices (shop_c partial, shop_d blocked).
    assert have[NeedKind.HISTORY_SNAPSHOTS] == 3
    assert have[NeedKind.RETAILERS] == 2
    assert all(have[k] == 0 for k in have if k in NO_SOURCE)
    assert gated(with_dates(metrics_dataset(), 1), ModelId.FORECAST).needs[0].have == 1


def test_optimal_price_builds_on_elasticity() -> None:
    card = gated(metrics_dataset(), ModelId.OPTIMAL_PRICE)
    upstream = next(n for n in card.needs if n.kind is NeedKind.UPSTREAM_MODEL)
    assert (upstream.model, upstream.have) == (ModelId.ELASTICITY, 0)


def test_needs_data_is_the_only_state() -> None:
    assert typing.get_args(Gated.model_fields["state"].annotation) == ("needs_data",)
    with pytest.raises(ValidationError):
        Gated(state="ready", model=ModelId.FORECAST, requirements=(), needs=())  # type: ignore[arg-type]


def test_wire_shape() -> None:
    wire = gated(metrics_dataset(), ModelId.FORECAST).model_dump(mode="json", by_alias=True)
    assert wire == {
        "state": "needs_data",
        "model": "forecast",
        "requirements": ["ANL-15"],
        "needs": [
            {"kind": "history_snapshots", "required": 90, "have": 3, "model": None},
            {"kind": "backtest", "required": 1, "have": 0, "model": None},
        ],
        "gatesVersion": "2026-10-01.1",
    }
