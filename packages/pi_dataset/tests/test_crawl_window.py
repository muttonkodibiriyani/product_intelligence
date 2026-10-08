"""``CrawlWindow`` (ADR-0013): one run, at most four market calendar days, and the gap helper."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from pi_dataset import CrawlWindow, DatasetV3, committed_profile, dump_dataset, upgrade
from pi_dataset.compose import window_gap_days
from pi_dataset.examples import ae_pilot

DUBAI = "Asia/Dubai"


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def window(start: str, end: str, run: str = "7") -> CrawlWindow:
    return CrawlWindow(start=at(start), end=at(end), run_id=run)


def test_dubai_midnight_is_20_00_utc() -> None:
    """19:59Z on 10-08 is still the 8th in Dubai; 20:00Z is the 9th."""
    assert window("2026-10-08T00:00", "2026-10-08T19:59").days(DUBAI) == 1
    assert window("2026-10-08T00:00", "2026-10-08T20:00").days(DUBAI) == 2


def test_window_days_count_dubai_calendar_days_not_utc_ones() -> None:
    # 4 UTC days (03..06), but 02T20:00Z is Dubai 10-03 and 06T20:00Z is Dubai 10-07: 5 days.
    assert window("2026-10-03T00:00", "2026-10-06T20:00").days(DUBAI) == 5
    # 5 UTC days (02..06), but 02T20:00Z is already Dubai 10-03 and 06T19:59Z is Dubai 10-06: 4.
    assert window("2026-10-02T20:00", "2026-10-06T19:59").days(DUBAI) == 4


def test_a_window_ends_after_it_starts() -> None:
    with pytest.raises(ValidationError, match="is after end"):
        window("2026-10-02T00:00", "2026-10-01T00:00")
    assert window("2026-10-02T00:00", "2026-10-02T00:00").days(DUBAI) == 1


def test_window_gap_days_is_the_distance_between_the_dubai_end_dates() -> None:
    a = window("2026-10-08T00:00", "2026-10-08T19:59")
    b = window("2026-10-08T00:00", "2026-10-08T20:00")
    assert window_gap_days(a, b, DUBAI) == window_gap_days(b, a, DUBAI) == 1
    # Same Dubai day, 23h59m apart in time: 0 days.
    early = window("2026-10-07T20:00", "2026-10-07T20:00")
    assert window_gap_days(early, a, DUBAI) == 0
    seven = window("2026-10-01T00:00", "2026-10-01T10:00")
    assert window_gap_days(seven, a, DUBAI) == 7


def _doc_with(window_doc: dict[str, Any] | None) -> dict[str, Any]:
    profile = committed_profile("beauty", 1)
    assert profile is not None
    d: dict[str, Any] = json.loads(dump_dataset(upgrade(ae_pilot(), profile)))
    d["meta"]["cutoff"] = "2026-10-06T20:00:00Z"
    d["meta"]["generatedAt"] = "2026-10-06T21:00:00Z"
    if window_doc is not None:
        d["meta"]["retailers"][0]["window"] = window_doc
    return d


def test_a_snapshot_spans_at_most_four_dubai_days() -> None:
    four = {"start": "2026-10-02T20:00:00Z", "end": "2026-10-06T19:59:00Z", "runId": "7"}
    DatasetV3.model_validate(_doc_with(four))
    five = four | {"end": "2026-10-06T20:00:00Z"}
    with pytest.raises(ValidationError, match="spans 5 days in Asia/Dubai, more than 4"):
        DatasetV3.model_validate(_doc_with(five))


def test_a_window_never_ends_after_the_cutoff() -> None:
    late = {"start": "2026-10-06T00:00:00Z", "end": "2026-10-06T20:00:01Z", "runId": "7"}
    with pytest.raises(ValidationError, match=r"end is after meta\.cutoff"):
        DatasetV3.model_validate(_doc_with(late))


def test_the_keys_are_optional_and_camel_case_on_the_wire() -> None:
    ds = DatasetV3.model_validate(_doc_with(None))
    assert ds.meta.retailers[0].window is None
    w = window("2026-10-05T00:00", "2026-10-06T00:00", run="8")
    assert w.model_dump(mode="json", by_alias=True) == {
        "start": "2026-10-05T00:00:00Z",
        "end": "2026-10-06T00:00:00Z",
        "runId": "8",
    }
