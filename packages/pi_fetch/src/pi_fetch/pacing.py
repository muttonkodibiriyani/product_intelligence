"""Politeness: per-host pacing, the off-peak window and robots tagging for the audit log.

``HostPacer`` spaces request starts to one host by at least ``min_interval_s`` (never under one
second, so ≤ 1 req/s) plus random jitter, and honours a server's ``Retry-After`` by deferring the
host's next request. It never retries anything itself.
"""

import random
import threading
import time
import urllib.robotparser
from collections.abc import Callable
from datetime import datetime, timedelta
from datetime import time as dtime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from pi_core import PiModel

#: Floor for the per-host interval: at most one request per second per host.
MIN_INTERVAL_FLOOR_S = 1.0
#: Longest ``Retry-After`` honoured; beyond it the run should stop the host, not wait.
MAX_DEFER_S = 3600.0


class HostPacer:
    """Blocks until a host may be requested again. Thread-safe; clock and sleep injectable."""

    def __init__(
        self,
        *,
        min_interval_s: float = MIN_INTERVAL_FLOOR_S,
        jitter_s: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if min_interval_s < MIN_INTERVAL_FLOOR_S:
            msg = f"min_interval_s must be at least {MIN_INTERVAL_FLOOR_S}s (≤ 1 req/s per host)"
            raise ValueError(msg)
        if jitter_s < 0:
            msg = "jitter_s must not be negative"
            raise ValueError(msg)
        self._min_interval = min_interval_s
        self._jitter = jitter_s
        self._clock = clock
        self._sleep = sleep
        # Jitter only spreads timing; it is not a security use of randomness.
        self._rng = rng or random.Random()  # noqa: S311
        self._next_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> float:
        """Reserve the next slot for ``host`` and sleep until it. Returns the seconds slept."""
        host = host.lower()
        with self._lock:
            now = self._clock()
            start = max(now, self._next_at.get(host, now))
            gap = self._min_interval + self._rng.uniform(0, self._jitter)
            self._next_at[host] = start + gap
        delay = start - now
        if delay > 0:
            self._sleep(delay)
        return delay

    def defer(self, host: str, seconds: float) -> None:
        """Push the host's next slot back by ``seconds`` (a server's ``Retry-After``)."""
        seconds = min(max(seconds, 0.0), MAX_DEFER_S)
        host = host.lower()
        with self._lock:
            now = self._clock()
            self._next_at[host] = max(self._next_at.get(host, now), now + seconds)


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a ``Retry-After`` header in delta-seconds form; None when absent or a date."""
    if value is None or not value.strip().isdigit():
        return None
    return float(value.strip())


class OffPeakWindow(PiModel):
    """Local-time window a context is collected in (ADR-0005: UAE night). May wrap midnight."""

    start: dtime
    end: dtime
    time_zone: str = Field(default="Asia/Dubai")

    @field_validator("time_zone")
    @classmethod
    def _check_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown time zone {value!r}"
            raise ValueError(msg) from exc
        return value

    def contains(self, at: datetime) -> bool:
        """True when the aware instant ``at`` falls inside the window."""
        local = at.astimezone(ZoneInfo(self.time_zone)).time()
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end

    def seconds_until_open(self, at: datetime) -> float:
        """0 inside the window, else seconds until it next opens."""
        if self.contains(at):
            return 0.0
        local = at.astimezone(ZoneInfo(self.time_zone))
        opens = local.replace(
            hour=self.start.hour, minute=self.start.minute, second=0, microsecond=0
        )
        if opens <= local:
            opens += timedelta(days=1)
        return (opens - local).total_seconds()


class RobotsTag(StrEnum):
    """Whether robots.txt allows a URL. Recorded for audit (ADR-0005 robots deviation)."""

    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    UNKNOWN = "unknown"


class RobotsTagger:
    """Tags URLs against robots.txt texts obtained at rung 0. Tagging only: it never blocks."""

    def __init__(self, user_agent: str = "*") -> None:
        self._user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def add(self, host: str, robots_txt: str) -> None:
        """Register the robots.txt text for ``host``."""
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(robots_txt.splitlines())
        self._parsers[host.lower()] = parser

    def tag(self, host: str, url: str) -> RobotsTag:
        """ALLOWED / DISALLOWED per the host's robots.txt, UNKNOWN when none was registered."""
        parser = self._parsers.get(host.lower())
        if parser is None:
            return RobotsTag.UNKNOWN
        allowed = parser.can_fetch(self._user_agent, url)
        return RobotsTag.ALLOWED if allowed else RobotsTag.DISALLOWED
