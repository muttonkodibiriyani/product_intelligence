"""Rule-based pair price suggestions (pi_metrics.pair_pricing)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from metrics_fixture import (
    A,
    B,
    C,
    D,
    edge,
    metrics_dataset,
    offer,
    product,
    rebuild,
    with_saudi_shop,
)
from pi_dataset import Dataset
from pi_metrics import Reason, Status, UnknownInput
from pi_metrics.model import ProductFilter
from pi_metrics.pair_pricing import (
    STALE_DAYS,
    NoSuggestion,
    PairAim,
    PairOutcome,
    PairRationaleCode,
    SideBasis,
    SuggestionRow,
    price_suggestions,
    undercut,
)
from pi_metrics.pricing import RULE_LABEL, Ending, Guardrails

ALL = ProductFilter()
RAILS = Guardrails()
AS_OF = date(2026, 9, 30)


def rows(ds: Dataset, subject: str = A, rival: str = B, **kw: object) -> dict[str, SuggestionRow]:
    metric = price_suggestions(ds, subject, rival, ALL, **kw)  # type: ignore[arg-type]
    return {r.id: r for r in metric.data.rows}


def two_shops(a: list[str | None], b: list[str | None], *, ages: tuple[int, int, int]) -> Dataset:
    """One exact approved a-b pair; dates are ``AS_OF`` minus ``ages`` days."""
    ds = metrics_dataset()
    pair = product("q01", {A: offer(A, a), B: offer(B, b)}, [edge(A, B)])
    dates = tuple(AS_OF - timedelta(days=n) for n in ages)
    return rebuild(ds.model_copy(update={"products": (pair,), "not_observed": ()}), dates=dates)


# ---- the pure rule ----------------------------------------------------------------------------


def codes(steps: list) -> list[PairRationaleCode]:  # type: ignore[type-arg]
    return [s.code for s in steps]


def test_beat_lands_just_below_the_rival() -> None:
    outcome, price, reaches, steps = undercut(
        Decimal("110.00"), Decimal("100.00"), aim=PairAim.BEAT, guardrails=RAILS, currency="AED"
    )
    assert (outcome, price, reaches) == (PairOutcome.SUGGESTED, Decimal("99.50"), True)
    assert codes(steps)[-1] is PairRationaleCode.BEATS_RIVAL
    assert steps[0].params == {"subject": "110.00", "rival": "100.00", "gapPct": "-9.1"}


def test_match_may_land_on_the_rival() -> None:
    outcome, price, reaches, _ = undercut(
        Decimal("110.00"), Decimal("100.00"), aim=PairAim.MATCH, guardrails=RAILS, currency="AED"
    )
    assert (outcome, price, reaches) == (PairOutcome.SUGGESTED, Decimal("100.00"), True)


def test_clamp_stops_short_of_the_rival() -> None:
    outcome, price, reaches, steps = undercut(
        Decimal("100.00"), Decimal("50.00"), aim=PairAim.BEAT, guardrails=RAILS, currency="AED"
    )
    assert (outcome, price, reaches) == (PairOutcome.SUGGESTED, Decimal("90.00"), False)
    assert PairRationaleCode.CLAMPED in codes(steps)
    assert codes(steps)[-1] is PairRationaleCode.SHORT_OF_RIVAL


@pytest.mark.parametrize(("current", "aim"), [("90.00", PairAim.BEAT), ("100.00", PairAim.MATCH)])
def test_already_competitive_never_raises(current: str, aim: PairAim) -> None:
    outcome, price, reaches, steps = undercut(
        Decimal(current), Decimal("100.00"), aim=aim, guardrails=RAILS, currency="AED"
    )
    assert (outcome, price, reaches) == (PairOutcome.ALREADY_COMPETITIVE, None, True)
    assert codes(steps) == [PairRationaleCode.CURRENT_GAP, PairRationaleCode.ALREADY_COMPETITIVE]


def test_equal_price_is_not_beaten() -> None:
    outcome, price, _, _ = undercut(
        Decimal("100.00"), Decimal("100.00"), aim=PairAim.BEAT, guardrails=RAILS, currency="AED"
    )
    assert (outcome, price) == (PairOutcome.SUGGESTED, Decimal("99.00"))


def test_below_min_change() -> None:
    rails = Guardrails(
        max_change_pct=Decimal(2), min_change_pct=Decimal("1.5"), endings=(Ending.WHOLE,)
    )
    outcome, price, reaches, steps = undercut(
        Decimal("100.40"), Decimal("90.00"), aim=PairAim.BEAT, guardrails=rails, currency="AED"
    )
    assert (outcome, price, reaches) == (PairOutcome.BELOW_MIN_CHANGE, None, False)
    assert codes(steps)[-1] is PairRationaleCode.BELOW_MIN_CHANGE


def test_no_allowed_price() -> None:
    rails = Guardrails(max_change_pct=Decimal("0.5"), endings=(Ending.WHOLE,))
    outcome, price, _, steps = undercut(
        Decimal("100.60"), Decimal("90.00"), aim=PairAim.BEAT, guardrails=rails, currency="AED"
    )
    assert (outcome, price) == (PairOutcome.NO_ALLOWED_PRICE, None)
    assert codes(steps)[-1] is PairRationaleCode.NO_ALLOWED_PRICE


# ---- the fixture ------------------------------------------------------------------------------


def test_fixture_outcomes_and_reasons() -> None:
    metric = price_suggestions(metrics_dataset(), A, B, ALL)
    assert metric.status is Status.OK
    assert metric.as_of == AS_OF
    data = metric.data
    assert (data.label, data.stale_days, data.aim) == (RULE_LABEL, STALE_DAYS, PairAim.BEAT)
    assert [r.id for r in data.rows][:6] == ["p03", "p06", "p02", "p04", "p01", "p05"]
    got = {r.id: (r.outcome, r.suggested and r.suggested.amount, r.reason) for r in data.rows}
    assert got == {
        "p01": (PairOutcome.ALREADY_COMPETITIVE, None, None),
        "p02": (PairOutcome.SUGGESTED, "99.00", None),
        "p03": (PairOutcome.SUGGESTED, "99.50", None),
        "p04": (PairOutcome.ALREADY_COMPETITIVE, None, None),
        "p05": (PairOutcome.ALREADY_COMPETITIVE, None, None),
        "p06": (PairOutcome.SUGGESTED, "99.50", None),
        "p07": (None, None, NoSuggestion.MATCH_UNREVIEWED),
        "p08": (None, None, NoSuggestion.MATCH_REJECTED),
        "p09": (None, None, NoSuggestion.MATCH_NOT_EXACT),
        "p10": (None, None, NoSuggestion.SIZE_MISMATCH),
        "p11": (None, None, NoSuggestion.UNPRICED),
        "p12": (None, None, NoSuggestion.NOT_OFFERED),
        "p13": (None, None, NoSuggestion.EARLY),
        "p16": (None, None, NoSuggestion.NO_MATCH),
    }
    assert data.outcomes == {"already_competitive": 3, "suggested": 3}
    assert sum(data.reasons.values()) == 8
    assert data.total == len(data.rows) == 14
    assert metric.cohort is not None
    assert metric.cohort.n == 6


def test_row_inputs_are_exact() -> None:
    row = rows(metrics_dataset())["p03"]
    assert row.subject.price is not None
    assert row.subject.price.amount == "110.00"
    assert row.rival.price is not None
    assert row.rival.price.amount == "100.00"
    assert (row.subject.observed_on, row.rival.observed_on) == (AS_OF, AS_OF)
    assert row.subject.basis is SideBasis.OBSERVED
    assert row.match is not None
    assert row.match.confidence == "0.95"
    assert row.gap is not None
    assert row.gap.amount.amount == "-10.00"
    assert row.change_pct is not None
    assert row.change_pct == (Decimal("99.50") - Decimal("110.00")) / Decimal("110.00") * 100


def test_already_competitive_keeps_the_gap_as_data() -> None:
    row = rows(metrics_dataset())["p01"]
    assert row.gap is not None
    assert row.gap.amount.amount == "10.00"
    assert row.suggested is None
    assert row.change_pct is None


def test_blocked_rival_withholds_every_row() -> None:
    metric = price_suggestions(metrics_dataset(), A, D, ALL)
    assert (metric.status, metric.reason) == (Status.NOT_ENOUGH_DATA, Reason.RETAILER_BLOCKED)
    assert {r.reason for r in metric.data.rows} == {NoSuggestion.RETAILER_BLOCKED}
    assert not metric.data.outcomes


def test_partial_rival_withholds_every_row() -> None:
    metric = price_suggestions(metrics_dataset(), A, C, ALL)
    assert (metric.status, metric.reason) == (Status.NOT_ENOUGH_DATA, Reason.RETAILER_PARTIAL)
    assert {r.reason for r in metric.data.rows} == {NoSuggestion.RETAILER_PARTIAL}


def test_mixed_currency_withholds_every_row() -> None:
    metric = price_suggestions(with_saudi_shop(metrics_dataset()), A, "shop_e", ALL)
    assert (metric.status, metric.reason) == (Status.NOT_ENOUGH_DATA, Reason.CURRENCY_MISMATCH)
    assert {r.reason for r in metric.data.rows} == {NoSuggestion.CURRENCY_MISMATCH}
    assert all(r.gap is None for r in metric.data.rows)


def test_same_retailer_is_refused() -> None:
    with pytest.raises(UnknownInput):
        price_suggestions(metrics_dataset(), A, A, ALL)


def test_aim_and_guardrails_are_echoed() -> None:
    rails = Guardrails(max_change_pct=Decimal(5))
    metric = price_suggestions(metrics_dataset(), A, B, ALL, aim=PairAim.MATCH, guardrails=rails)
    assert (metric.data.aim, metric.data.guardrails) == (PairAim.MATCH, rails)
    # p03 at 110.00 can only come down 5%: 104.50, short of the rival's 100.00.
    p03 = {r.id: r for r in metric.data.rows}["p03"]
    assert p03.suggested is not None
    assert p03.suggested.amount == "104.50"
    assert p03.reaches_rival is False


# ---- staleness and one-off imports ------------------------------------------------------------


def test_rival_observed_eight_days_ago_is_stale() -> None:
    ds = two_shops(["110.00"] * 3, ["100.00", None, None], ages=(8, 1, 0))
    row = rows(ds)["q01"]
    assert row.reason is NoSuggestion.STALE_OBSERVATION
    assert (row.rival.observed_on, row.rival.age_days) == (AS_OF - timedelta(days=8), 8)


def test_rival_observed_seven_days_ago_is_not_stale() -> None:
    ds = two_shops(["110.00"] * 3, ["100.00", None, None], ages=(7, 1, 0))
    row = rows(ds)["q01"]
    assert (row.outcome, row.rival.age_days) == (PairOutcome.SUGGESTED, 7)


def test_stale_crawled_subject_is_stale() -> None:
    ds = two_shops(["110.00", None, None], ["100.00"] * 3, ages=(8, 1, 0))
    assert rows(ds)["q01"].reason is NoSuggestion.STALE_OBSERVATION


def test_imported_subject_with_a_fresh_rival_is_suggested() -> None:
    imported_on = AS_OF - timedelta(days=20)
    ds = two_shops(["110.00"] * 3, ["100.00"] * 3, ages=(8, 1, 0))
    row = rows(ds, imported={A: imported_on})["q01"]
    assert row.outcome is PairOutcome.SUGGESTED
    assert row.subject.basis is SideBasis.IMPORTED_SNAPSHOT
    assert (row.subject.observed_on, row.subject.age_days) == (imported_on, 20)
    assert row.rival.basis is SideBasis.OBSERVED


def test_imported_subject_with_a_stale_rival_is_stale() -> None:
    ds = two_shops(["110.00"] * 3, ["100.00", None, None], ages=(8, 1, 0))
    row = rows(ds, imported={A: AS_OF - timedelta(days=20)})["q01"]
    assert row.reason is NoSuggestion.STALE_OBSERVATION


def test_imported_rival_is_never_exempt() -> None:
    ds = two_shops(["110.00"] * 3, ["100.00"] * 3, ages=(2, 1, 0))
    metric = price_suggestions(ds, A, B, ALL, imported={B: AS_OF})
    assert (metric.status, metric.reason) == (Status.NOT_ENOUGH_DATA, Reason.RETAILER_PARTIAL)
    (row,) = metric.data.rows
    assert row.reason is NoSuggestion.STALE_OBSERVATION
    assert row.outcome is None
