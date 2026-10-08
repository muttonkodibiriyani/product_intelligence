"""The served set's window guard (ADR-0013; rulings 01a11c71-37ee, 01a11cad-17da, review
5461045335): no window is refused, the gap is counted in the market's time zone (8 days refused,
7 pass), and a set in more than one time zone is refused."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pi_api.app import app_from_env
from pi_api.windows import MAX_GAP_DAYS, check_windows, window_problems
from pi_dataset import DatasetV3, committed_profile, dump_dataset, upgrade
from pi_dataset.examples import ae_pilot

NORTH, SOUTH = "example_north_ae", "example_south_ae"
#: ulta_ae tonight (Coordinator 01a11cc0-86a1): the whole retailer, blocked.
BLOCKED = {
    "retailer": SOUTH,
    "context": None,
    "categories": None,
    "start": "2026-10-01",
    "end": "2026-10-08",
    "why": {"en": "Blocked (p0-20261008-ulta-probe).", "ar": "محجوب."},
}
FRESH = {"start": "2026-10-08T00:00:00Z", "end": "2026-10-08T10:00:00Z", "runId": "fresh"}


def windowed(
    end: str | None,
    *,
    cutoff: str = "2026-10-08T20:00:00Z",
    zone: str = "Asia/Dubai",
    withheld: dict[str, Any] | None = None,
) -> DatasetV3:
    """The ae-pilot example as the exporter writes it: each retailer with its own keys and
    (unless ``end`` is None) a one-day window ending at ``end``; its AE market in ``zone``.
    ``withheld`` is a notObserved entry for ``SOUTH``, which then has no window."""
    profile = committed_profile("beauty", 1)
    assert profile is not None
    d: dict[str, Any] = json.loads(dump_dataset(upgrade(ae_pilot(), profile)))
    meta = d["meta"]
    meta["cutoff"], meta["generatedAt"] = cutoff, cutoff
    meta["markets"][0]["timeZone"] = zone
    for r in meta["retailers"]:
        r["fields"], r["capabilities"] = dict(meta["fields"]), dict(meta["capabilities"])
        if end is not None and not (withheld is not None and r["id"] == SOUTH):
            r["window"] = {"start": end, "end": end, "runId": f"run-{end}"}
    if withheld is not None:
        d["notObserved"] = [{**BLOCKED, **withheld}]
    return DatasetV3.model_validate(d)


def test_seven_dubai_days_pass_and_eight_are_refused_at_the_20z_boundary() -> None:
    assert MAX_GAP_DAYS == 7
    fresh = ("fresh", windowed(FRESH["end"]))
    # 2026-09-30T20:00Z is already 10-01 in Dubai: 7 days before 10-08.
    seven = ("seven", windowed("2026-09-30T20:00:00Z"))
    assert window_problems([fresh, seven]) == []
    # One minute earlier is 09-30 in Dubai: 8 days.
    eight = ("eight", windowed("2026-09-30T19:59:00Z"))
    [problem] = window_problems([fresh, eight])
    assert problem.startswith("window gap 8 days in Asia/Dubai, more than 7")
    assert "eight: example_" in problem
    assert "fresh: example_" in problem
    assert window_problems([eight, fresh]) == [problem]  # order-free


def test_the_market_time_zone_moves_the_boundary() -> None:
    # Riyadh (UTC+3) turns its day at 21:00Z, an hour after Dubai: 20:00Z on 09-30 is still
    # 09-30 there, so the set that is 7 Dubai days apart is 8 Riyadh days apart.
    def riyadh(end: str) -> DatasetV3:
        return windowed(end, zone="Asia/Riyadh")

    fresh = ("fresh", riyadh(FRESH["end"]))
    [problem] = window_problems([fresh, ("dubai-seven", riyadh("2026-09-30T20:00:00Z"))])
    assert problem.startswith("window gap 8 days in Asia/Riyadh, more than 7")
    assert window_problems([fresh, ("seven", riyadh("2026-09-30T21:00:00Z"))]) == []


def test_a_set_in_more_than_one_time_zone_is_refused() -> None:
    same_day = "2026-10-08T10:00:00Z"
    mixed = [("ae", windowed(same_day)), ("sa", windowed(same_day, zone="Asia/Riyadh"))]
    assert window_problems(mixed) == ["windows in more than one time zone: Asia/Dubai, Asia/Riyadh"]


def test_a_retailer_without_a_window_is_refused() -> None:
    problems = window_problems([("old", windowed(None)), ("fresh", windowed(FRESH["end"]))])
    assert problems == [
        f"old: {r} has no crawl window (ADR-0013): re-export it, or withhold it with a "
        "notObserved entry for the whole retailer"
        for r in ("example_north_ae", "example_south_ae")
    ]
    assert window_problems([]) == []


def test_require_all_refuses_a_cold_start_over_the_gap(tmp_path: Path) -> None:
    a, b = "datasets/ae/a/v/1.json", "datasets/ae/b/v/2.json"
    for path, ds in ((a, windowed(FRESH["end"])), (b, windowed("2026-09-30T19:59:00Z"))):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(dump_dataset(ds))
    served = {
        "PI_API_FIREBASE_PROJECT": "p",
        "PI_API_LOCAL_DIR": str(tmp_path),
        "PI_API_ALLOW_TEST": "1",
        "PI_API_DATASETS": f"{a},{b}",
    }
    assert app_from_env(served) is not None  # without the flag the API still starts
    with pytest.raises(RuntimeError, match="PI_API_REQUIRE_ALL: crawl windows: window gap 8"):
        app_from_env({**served, "PI_API_REQUIRE_ALL": "1"})
    (tmp_path / b).write_bytes(dump_dataset(windowed("2026-09-30T20:00:00Z")))
    assert app_from_env({**served, "PI_API_REQUIRE_ALL": "1"}) is not None


def test_a_withheld_retailer_passes_and_the_others_keep_the_gap() -> None:
    """Coordinator 01a11cc0-86a1: a retailer disclosed as not observed for the whole retailer
    to the set's last window day, with no window, is withheld; the rest are still checked."""
    fresh = windowed(FRESH["end"], withheld={})
    check = check_windows([("beauty", fresh)])
    assert check.problems == []
    assert check.withheld == [
        f"beauty: {SOUTH} withheld, not observed until 2026-10-08: "
        "Blocked (p0-20261008-ulta-probe)."
    ]
    # The other retailers keep the 7-day rule: north 8 days stale in another body is refused.
    eight = ("old", windowed("2026-09-30T19:59:00Z"))
    [problem] = window_problems([("beauty", fresh), eight])
    assert problem.startswith("window gap 8 days in Asia/Dubai, more than 7")


def test_withholding_never_excuses_a_window_or_a_stale_disclosure() -> None:
    # A retailer that has a window is counted, disclosure or not: a stale window is refused.
    stale = windowed("2026-09-30T19:59:00Z")
    stale = stale.model_copy(update={"not_observed": windowed(None, withheld={}).not_observed})
    [problem] = window_problems([("fresh", windowed(FRESH["end"])), ("stale", stale)])
    assert problem.startswith("window gap 8 days")
    # Disclosed only until 10-07 while the set runs to 10-08: refused.
    short = windowed(FRESH["end"], withheld={"end": "2026-10-07"})
    assert window_problems([("b", short)]) == [
        f"b: {SOUTH} is withheld only until 2026-10-07, before the set's last window day 2026-10-08"
    ]
    # Part of the retailer (a category) is not the whole retailer: no window is refused.
    part = windowed(FRESH["end"], withheld={"categories": ["skincare"]})
    [problem] = window_problems([("b", part)])
    assert problem.startswith(f"b: {SOUTH} has no crawl window (ADR-0013)")
