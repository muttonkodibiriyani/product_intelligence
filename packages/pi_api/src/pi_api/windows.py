"""The served set's crawl windows (ADR-0013; Coordinator 01a11c70-e101, 01a11c71-37ee).

Every retailer a revision serves needs its own crawl window, and no two windows may end more
than ``MAX_GAP_DAYS`` Dubai calendar days apart, so no page shows one shop's fresh prices next to
another's stale ones as if they were one snapshot. ``PI_API_REQUIRE_ALL=1`` refuses a cold start
that breaks this, and ``publish_dataset.py`` runs the same check before a body or a roll value
is used (pi-api-deploy.md §6).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from pi_dataset import DatasetV3
from pi_dataset.compose import window_gap_days
from pi_dataset.v3 import CrawlWindow, local_date

#: The calendar the gap is counted in: the market the PI pilot serves (ruling 01a11c71-37ee).
GAP_TIME_ZONE = "Asia/Dubai"
#: The most Dubai days two served windows' ends may be apart; 8 is refused.
MAX_GAP_DAYS = 7


def window_problems(datasets: Iterable[tuple[str, DatasetV3]]) -> list[str]:
    """Why the served set ``(name, dataset)`` may not be served together; empty when it may.

    A retailer without a window is refused (unknown is never guessed), and so is a set whose
    earliest and latest window ends are more than ``MAX_GAP_DAYS`` apart."""
    problems: list[str] = []
    windows: list[tuple[str, CrawlWindow]] = []
    for name, dataset in datasets:
        for retailer in dataset.meta.retailers:
            label = f"{name}: {retailer.id}"
            if retailer.window is None:
                problems.append(f"{label} has no crawl window (ADR-0013): re-export it")
            else:
                windows.append((label, retailer.window))
    if windows:
        first, last = min(windows, key=_end_day), max(windows, key=_end_day)
        gap = window_gap_days(first[1], last[1], GAP_TIME_ZONE)
        if gap > MAX_GAP_DAYS:
            problems.append(
                f"window gap {gap} Dubai days, more than {MAX_GAP_DAYS}: {first[0]} ends "
                f"{first[1].end.isoformat()}, {last[0]} ends {last[1].end.isoformat()}"
            )
    return problems


def _end_day(item: tuple[str, CrawlWindow]) -> date:
    return local_date(item[1].end, GAP_TIME_ZONE)
