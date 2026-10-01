"""Unattended runs (ADR-0009): the run window, the in-job gap-first plan, the end-of-run status and
the unloaded-run check. Pure functions, no network; ``run.py`` and ``stale.py`` do the I/O.

- **Window.** An ``AUTO=1`` run derives its own ``PREFIX`` and ``CUTOFF`` from its start time. It
  starts only inside the UAE night, 18:00Z-02:00Z, and stops at the next 01:55Z. A Scheduler that
  fires at the wrong hour gets a run that stops before any request, with status
  ``outside_window``.
- **Plan.** Gap-first over the products the sitemaps list tonight, using what earlier runs in the
  bucket covered (``covered.json.gz``):
  1. products with no EN page read in any retained run (new products and gaps);
  2. products whose variants were last seen at different prices;
  3. the rest, the longest-unread first.
  Ties keep the main job's seeded-shuffle order, so a cutoff still leaves a fair sample. Nothing is
  guessed: a product absent from every ``covered`` file counts as unread.
- **Status.** Every run, in every mode, ends by writing ``status.json`` once. Its ``outcome`` is
  ``complete``, ``cutoff``, ``blocked``, ``rate_limited``, ``outside_window`` or ``error``.
- **Unloaded runs.** Run outputs are deleted 14 days after they are written (#124). A run with
  something to load that is not loaded and finished in pi_db by day 10 is reported, so a held
  load never silently loses its run.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

SHUFFLE_SEED = 20260930  # the main job's order (run.py, plan.py)
WINDOW_START = time(18, 0)
WINDOW_END = time(2, 0)
CUTOFF_AT = time(1, 55)  # five minutes inside the window's end
AUTO_PREFIX = "auto-"
UNLOADED_ALERT_DAYS = 10
OUTCOMES = ("complete", "cutoff", "blocked", "rate_limited", "outside_window", "error")


class OutsideWindow(Exception):  # noqa: N818
    pass


def in_window(now: datetime) -> bool:
    t = now.astimezone(UTC).time()
    return t >= WINDOW_START or t < WINDOW_END


def auto_prefix(now: datetime) -> str:
    return f"{AUTO_PREFIX}{now.astimezone(UTC):%Y%m%dT%H%MZ}"


def auto_cutoff(now: datetime) -> datetime:
    """The next 01:55Z. Raises ``OutsideWindow`` unless ``now`` is in 18:00Z-01:55Z."""
    now = now.astimezone(UTC)
    if not in_window(now):
        raise OutsideWindow(
            f"start {now:%H:%M}Z is outside {WINDOW_START:%H:%M}-{WINDOW_END:%H:%M}Z"
        )
    day = now.date() + timedelta(days=1) if now.time() >= WINDOW_START else now.date()
    cutoff = datetime.combine(day, CUTOFF_AT, tzinfo=UTC)
    if cutoff <= now:
        raise OutsideWindow(f"start {now:%H:%M}Z is after the {CUTOFF_AT:%H:%M}Z cutoff")
    return cutoff


def multi_price(details: Mapping[str, Any]) -> bool:
    """True when the page lists variants at more than one price (sale price, else list price)."""
    prices = {
        v.get("c_salesPrice") if v.get("c_salesPrice") is not None else v.get("c_price")
        for v in details.get("c_variantsInfo") or []
        if isinstance(v, Mapping)
    }
    prices.discard(None)
    return len(prices) > 1


@dataclass(frozen=True)
class Seen:
    """What the retained runs say about one product."""

    last_read: str  # ISO time of the newest EN page read
    multi_price: bool  # as of that read


def merge_covered(covered: Iterable[Mapping[str, Any]]) -> dict[str, Seen]:
    """Fold runs' ``covered.json.gz`` payloads into the newest EN read per product."""
    seen: dict[str, Seen] = {}
    for run in covered:
        for pid, entry in (run.get("pdp_en") or {}).items():
            at = str(entry.get("at") or "")
            if not at:
                continue
            if pid not in seen or at > seen[pid].last_read:
                seen[pid] = Seen(at, bool(entry.get("multi_price")))
    return seen


def gap_first(pids: Iterable[str], seen: Mapping[str, Seen]) -> tuple[list[str], dict[str, int]]:
    """The night's order and its tier sizes (see the module docstring)."""
    base = sorted(set(pids))
    random.Random(SHUFFLE_SEED).shuffle(base)  # noqa: S311 - ordering, not crypto
    rank = {pid: i for i, pid in enumerate(base)}
    unread = [p for p in base if p not in seen]
    multi = [p for p in base if p in seen and seen[p].multi_price]
    rest = sorted(
        (p for p in base if p in seen and not seen[p].multi_price),
        key=lambda p: (seen[p].last_read, rank[p]),
    )
    multi.sort(key=lambda p: (seen[p].last_read, rank[p]))
    tiers = {"unread": len(unread), "multi_price": len(multi), "rest": len(rest)}
    return unread + multi + rest, tiers


def outcome(stopped: str | None) -> str:
    """Classify run.py's ``stopped`` reason for the status file and for alerting."""
    if stopped in ("complete", "cutoff", "outside_window"):
        return stopped
    if stopped and stopped.startswith(("challenge", "blocked")):
        return "blocked"
    if stopped == "3 consecutive 429":
        return "rate_limited"
    return "error"


def loadable(counts: Mapping[str, int]) -> bool:
    """Whether a run fetched anything the loader would turn into rows."""
    return bool(counts.get("pdp_en_ok") or counts.get("pdp_ar_ok") or counts.get("trpc_http_200"))


@dataclass(frozen=True)
class RunState:
    prefix: str
    started: datetime
    counts: Mapping[str, int]


def unloaded(
    runs: Iterable[RunState],
    finished_prefixes: set[str],
    now: datetime,
    days: int = UNLOADED_ALERT_DAYS,
) -> list[RunState]:
    """Runs at least ``days`` old with something to load and no finished crawl_run in pi_db."""
    limit = now - timedelta(days=days)
    return sorted(
        (
            r
            for r in runs
            if r.started <= limit and loadable(r.counts) and r.prefix not in finished_prefixes
        ),
        key=lambda r: r.started,
    )
