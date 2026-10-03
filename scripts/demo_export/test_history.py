from __future__ import annotations

# ruff: noqa: S101
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from pi_dataset import Dataset, RetailerStatus, dump_dataset, load_dataset
from pi_metrics import ProductFilter, Status, launches
from pi_metrics.model import CaveatCode, Reason
from scripts.demo_export.export import (
    ULTA_BLOCKED_NOTE,
    ULTA_BLOCKED_NOTE_AR,
    ListingRow,
    UltaContext,
    latest_params,
)
from scripts.demo_export.history import (
    Coverage,
    RunSpan,
    build_history_v2,
    day_bounds,
    market_day,
)
from scripts.demo_export.test_export import row

D1, D2, D3 = date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)
NOW = datetime(2026, 10, 3, 6, 0, tzinfo=UTC)
NOTE = {"en": ULTA_BLOCKED_NOTE, "ar": ULTA_BLOCKED_NOTE_AR}
EVERYTHING = ProductFilter()
SEPHORA, ULTA = "sephora_me", "ulta_ae"


def at(day: date, hour: int = 10) -> datetime:
    """``hour`` o'clock Dubai time on ``day``, as UTC."""
    return day_bounds(day)[0].astimezone(UTC) + timedelta(hours=hour)


def seen(day: date, variant: int, *, source: str = SEPHORA, price: str = "100") -> ListingRow:
    moment = at(day)
    return replace(
        row(source=source, family=variant, variant=variant, price=price, regular=None),
        observed_at=moment,
        evidence_retrieved_at=moment,
    )


def span(day: date, *, source: str = SEPHORA, status: str = "succeeded", run: int = 1) -> RunSpan:
    return RunSpan(
        source_name=source,
        context_id=1 if source == SEPHORA else 2,
        run_id=run,
        status=status,
        coverage_status="supported",
        first_at=at(day, 9),
        last_at=at(day, 12),
    )


def build(
    days: dict[date, list[ListingRow]], spans: list[RunSpan], *, ulta_blocked: bool = True
) -> Dataset:
    ds = build_history_v2(
        days,
        Coverage.of(spans),
        [],
        generated_at=NOW,
        ulta=UltaContext(
            blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC), blocked=ulta_blocked
        ),
        ulta_note=NOTE,
    )
    load_dataset(dump_dataset(ds))  # exactly what the publisher and the API do
    return ds


def launched(ds: Dataset, shop: str) -> list[tuple[str, date]]:
    metric = launches(ds, (shop,), EVERYTHING)
    assert metric.status is Status.OK
    return [(item.id, item.first_seen) for item in metric.data.items]


def withheld(ds: Dataset, shop: str) -> int:
    metric = launches(ds, (shop,), EVERYTHING)
    found = [c for c in metric.caveats if c.code is CaveatCode.LAUNCHES_WITHHELD]
    return int(found[0].params["count"]) if found else 0


def pid(variant: int, source: str = SEPHORA) -> str:
    return f"{'s' if source == SEPHORA else 'u'}-{variant}-30-ml"


def test_a_product_first_seen_on_the_second_complete_day_is_a_launch() -> None:
    ds = build(
        {D1: [seen(D1, 1)], D2: [seen(D2, 1), seen(D2, 2)]},
        [span(D1), span(D2, run=2)],
    )
    assert ds.meta.dates == (D1, D2)
    assert ds.meta.capabilities.history is True
    sephora = next(r for r in ds.meta.retailers if r.id == SEPHORA)
    assert (sephora.status, sephora.since) == (RetailerStatus.SUPPORTED, D1)
    assert ds.not_observed == tuple(w for w in ds.not_observed if w.retailer == ULTA)
    assert launched(ds, SEPHORA) == [(pid(2), D2)]


def test_a_product_seen_on_the_first_day_is_never_a_launch() -> None:
    ds = build(
        {D1: [seen(D1, 1), seen(D1, 3)], D2: [seen(D2, 1), seen(D2, 3)]},
        [span(D1), span(D2, run=2)],
    )
    assert launched(ds, SEPHORA) == []
    assert withheld(ds, SEPHORA) == 0


def test_one_day_is_not_a_history() -> None:
    ds = build({D2: [seen(D2, 1)]}, [span(D2)])
    assert ds.meta.dates == (D2,)
    assert ds.meta.capabilities.history is False
    assert launches(ds, (SEPHORA,), EVERYTHING).reason is Reason.CAPABILITY_OFF


def test_a_day_only_ulta_was_observed_gives_no_false_sephora_launches() -> None:
    # D2: Sephora not collected at all. Product 1 is back on D3 (not new); product 2 is first
    # seen on D3, after a day nobody looked: withheld, never a launch.
    days = {
        D1: [seen(D1, 1), seen(D1, 50, source=ULTA)],
        D2: [seen(D2, 50, source=ULTA)],
        D3: [seen(D3, 1), seen(D3, 2), seen(D3, 50, source=ULTA), seen(D3, 51, source=ULTA)],
    }
    spans = [
        span(D1),
        span(D1, source=ULTA, run=2),
        span(D2, source=ULTA, run=3),
        span(D3, run=4),
        span(D3, source=ULTA, run=5),
    ]
    ds = build(days, spans, ulta_blocked=False)
    assert ds.meta.dates == (D1, D2, D3)
    (window,) = [w for w in ds.not_observed if w.retailer == SEPHORA]
    assert (window.start, window.end, window.categories) == (D2, D2, None)
    assert "Not collected" in window.why["en"]
    assert launched(ds, SEPHORA) == []
    assert withheld(ds, SEPHORA) == 1
    # Ulta was complete every day: its new product is a launch (the control).
    assert launched(ds, ULTA) == [(pid(51, ULTA), D3)]


def test_a_partial_crawl_day_counts_neither_a_launch_nor_a_removal() -> None:
    # D2 only had an incremental (partial) run that saw product 3: products 1 and 2 are absent
    # that day because nobody looked, not because they left.
    days = {
        D1: [seen(D1, 1), seen(D1, 3)],
        D2: [seen(D2, 3)],
        D3: [seen(D3, 1), seen(D3, 2), seen(D3, 3)],
    }
    ds = build(days, [span(D1), span(D2, status="partial", run=2), span(D3, run=3)])
    (window,) = [w for w in ds.not_observed if w.retailer == SEPHORA]
    assert (window.start, window.end) == (D2, D2)
    assert "incomplete" in window.why["en"]
    assert launched(ds, SEPHORA) == []
    assert withheld(ds, SEPHORA) == 1


def test_a_value_is_never_carried_forward() -> None:
    days = {
        D1: [seen(D1, 1, price="90")],
        D2: [seen(D2, 3)],
        D3: [seen(D3, 1, price="95"), seen(D3, 3)],
    }
    ds = build(days, [span(D1), span(D2, status="partial", run=2), span(D3, run=3)])
    doc: dict[str, Any] = json.loads(dump_dataset(ds))
    (one,) = [p for p in doc["products"] if p["id"] == pid(1)]
    prices = [m and m["amount"] for m in one["offers"][SEPHORA]["series"]["price"]]
    assert prices == ["90.00", None, "95.00"]
    assert one["offers"][SEPHORA]["series"]["availability"][1] is None


def test_a_run_from_21_30z_falls_on_the_next_dubai_day() -> None:
    late = datetime(2026, 9, 30, 21, 30, tzinfo=UTC)  # 01:30 on 1 Oct in Dubai
    assert market_day(late) == D2
    assert day_bounds(D2) == (
        datetime(2026, 9, 30, 20, 0, tzinfo=UTC),
        datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
    )
    rows = [replace(seen(D2, 1), observed_at=late, evidence_retrieved_at=late)]
    cutoff_run = RunSpan(SEPHORA, 1, 1, "succeeded", "supported", late, late)
    ds = build({D2: rows}, [cutoff_run])
    assert ds.meta.dates == (D2,)
    assert next(r for r in ds.meta.retailers if r.id == SEPHORA).since == D2


def test_a_run_across_dubai_midnight_completes_neither_day() -> None:
    across = RunSpan(
        SEPHORA,
        1,
        1,
        "succeeded",
        "supported",
        datetime(2026, 9, 30, 19, 0, tzinfo=UTC),  # 23:00 Dubai, 30 Sep
        datetime(2026, 9, 30, 21, 30, tzinfo=UTC),  # 01:30 Dubai, 1 Oct
    )
    assert across.days == [D1, D2]
    assert across.complete_day is None
    cover = Coverage.of([across])
    assert cover.observed["s"] == {D1, D2}
    assert cover.complete["s"] == frozenset()


def test_a_retailer_with_two_contexts_is_complete_only_where_both_are() -> None:
    other = replace(span(D2, run=3), context_id=9)
    cover = Coverage.of([span(D1), span(D2, run=2), other])
    assert cover.complete["s"] == {D2}


def test_rows_filed_under_the_wrong_day_are_refused() -> None:
    with pytest.raises(ValueError, match="observed on"):
        build({D1: [seen(D2, 1)]}, [span(D1)])


def test_the_default_query_reads_no_day_window() -> None:
    assert latest_params(["sephora_me"]) == {
        "sources": ["sephora_me"],
        "day_start": None,
        "day_end": None,
    }
    start, end = day_bounds(D2)
    assert latest_params(["sephora_me"], (start, end))["day_start"] == start
