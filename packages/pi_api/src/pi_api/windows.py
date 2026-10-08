"""The served set's crawl windows (ADR-0013; Coordinator 01a11c70-e101, 01a11c71-37ee).

Every retailer a revision serves needs its own crawl window, and no two windows may end more
than ``MAX_GAP_DAYS`` calendar days apart in their market's time zone (``meta.markets`` by the
retailer's country), so no page shows one shop's fresh prices next to another's stale ones as if
they were one snapshot. A set whose windows are in more than one time zone has no one calendar to
count in, so it is refused.

A retailer is WITHHELD, not refused, when it has no window and its body discloses it as not
observed: a ``notObserved[]`` entry for the whole retailer (no context, no categories) that runs
to the set's last window day (Coordinator 01a11cc0-86a1: ulta_ae, blocked). It takes no part in
the gap. A retailer with a window is always counted, so a stale window is refused, never
excused, and nothing here widens ``MAX_GAP_DAYS``. A set where no retailer has a window is
refused: there is no fresh window to withhold beside, and an old disclosure must not pass for one
(review 5461198455).

``PI_API_REQUIRE_ALL=1`` refuses a cold start that breaks this, and ``publish_dataset.py``
runs the same check before a roll value is used (pi-api-deploy.md §6).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from pi_dataset import DatasetV3
from pi_dataset.compose import window_gap_days
from pi_dataset.v3 import CrawlWindow, NotObservedV3, local_date

#: The most calendar days two served windows' ends may be apart; 8 is refused.
MAX_GAP_DAYS = 7


@dataclass(frozen=True)
class WindowCheck:
    """``problems``: why the set may not be served together (empty when it may);
    ``withheld``: the retailers it serves as disclosed not observed, one line each."""

    problems: list[str] = field(default_factory=list)
    withheld: list[str] = field(default_factory=list)


def window_problems(datasets: Iterable[tuple[str, DatasetV3]]) -> list[str]:
    """``check_windows(datasets).problems``."""
    return check_windows(datasets).problems


def check_windows(datasets: Iterable[tuple[str, DatasetV3]]) -> WindowCheck:
    """The window guard over the served set ``(name, dataset)``.

    A retailer without a market for its country is refused, and so is one without a window
    unless it is withheld (module docstring); unknown is never guessed. So is a set in more
    than one time zone or whose earliest and latest window ends are more than ``MAX_GAP_DAYS``
    apart."""
    check = WindowCheck()
    windows: list[tuple[str, CrawlWindow, str]] = []
    bare: list[tuple[str, tuple[NotObservedV3, ...]]] = []
    for name, dataset in datasets:
        zones = {m.country: m.time_zone for m in dataset.meta.markets}
        for retailer in dataset.meta.retailers:
            label = f"{name}: {retailer.id}"
            if retailer.country not in zones:
                check.problems.append(f"{label} has no market for {retailer.country}")
            elif retailer.window is None:
                whole = tuple(
                    n
                    for n in dataset.not_observed
                    if n.retailer == retailer.id and n.context is None and n.categories is None
                )
                bare.append((label, whole))
            else:
                windows.append((label, retailer.window, zones[retailer.country]))
    found = sorted({zone for _, _, zone in windows})
    if len(found) > 1:
        check.problems.append(f"windows in more than one time zone: {', '.join(found)}")
    last: date | None = None
    if len(found) == 1:
        [zone] = found
        first, latest = min(windows, key=_end_day), max(windows, key=_end_day)
        last = _end_day(latest)
        gap = window_gap_days(first[1], latest[1], zone)
        if gap > MAX_GAP_DAYS:
            check.problems.append(
                f"window gap {gap} days in {zone}, more than {MAX_GAP_DAYS}: {first[0]} ends "
                f"{first[1].end.isoformat()}, {latest[0]} ends {latest[1].end.isoformat()}"
            )
    if bare and not windows:
        check.problems.append(
            "no retailer in the served set has a crawl window (ADR-0013): a retailer can only "
            "be withheld beside a windowed one"
        )
    _judge_withheld(check, bare, last)
    return check


def _judge_withheld(
    check: WindowCheck, bare: list[tuple[str, tuple[NotObservedV3, ...]]], last: date | None
) -> None:
    """Each windowless retailer: withheld when disclosed for the whole retailer to ``last``,
    the set's last window day; refused otherwise, and never withheld when there is none."""
    for label, whole in bare:
        if not whole:
            check.problems.append(
                f"{label} has no crawl window (ADR-0013): re-export it, or withhold it with a "
                "notObserved entry for the whole retailer"
            )
            continue
        if last is None:
            continue  # refused by the caller (no window, or more than one time zone)
        until = max(n.end for n in whole)
        if until < last:
            check.problems.append(
                f"{label} is withheld only until {until}, before the set's last window day {last}"
            )
            continue
        why = next(n for n in whole if n.end == until).why
        text = why.get("en") or next(iter(why.values()))
        check.withheld.append(f"{label} withheld, not observed until {until}: {text}")


def _end_day(item: tuple[str, CrawlWindow, str]) -> date:
    return local_date(item[1].end, item[2])
