"""Politeness: per-host pacing, the off-peak window and robots tagging for the audit log.

``HostPacer`` spaces request starts to one host by at least ``min_interval_s`` (never under one
second, so ≤ 1 req/s; a source may configure a longer interval, e.g. 5 s) plus random jitter.
After a 429 it backs the host off: the server's ``Retry-After`` (seconds or HTTP-date) or an
exponential default, whichever is longer. It never retries anything itself.

``RobotsTagger`` evaluates robots.txt. The fetcher obeys it by default and only tags (audit)
for a source configured ``tag_only`` (ADR-0005 override).
"""

import random
import re
import string
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator

from pi_core import PiModel

#: Floor for the per-host interval: at most one request per second per host.
MIN_INTERVAL_FLOOR_S = 1.0
#: Longest ``Retry-After`` honoured; beyond it the run should stop the host, not wait.
MAX_DEFER_S = 3600.0
#: First back-off after a 429 without a usable ``Retry-After``; doubles per consecutive 429.
BACKOFF_BASE_S = 60.0


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
        self._strikes: dict[str, int] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval_s: float | None = None) -> float:
        """Reserve the next slot for ``host`` and sleep until it. Returns the seconds slept.

        ``min_interval_s`` lengthens the gap after this request (a source's page interval); it
        can never shorten it below the pacer's own interval.
        """
        host = host.lower()
        interval = max(self._min_interval, min_interval_s or 0.0)
        with self._lock:
            now = self._clock()
            start = max(now, self._next_at.get(host, now))
            gap = interval + self._rng.uniform(0, self._jitter)
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

    def back_off(self, host: str, retry_after_s: float | None) -> tuple[float, bool]:
        """Defer ``host`` after a 429: the longer of ``Retry-After`` and an exponential default.

        Returns the deferral and whether it was clipped to ``MAX_DEFER_S`` (the run should then
        stop the host rather than wait).
        """
        host = host.lower()
        with self._lock:
            strikes = self._strikes.get(host, 0) + 1
            self._strikes[host] = strikes
        wanted = max(retry_after_s or 0.0, BACKOFF_BASE_S * 2 ** (strikes - 1))
        self.defer(host, wanted)
        return min(wanted, MAX_DEFER_S), wanted > MAX_DEFER_S

    def succeeded(self, host: str) -> None:
        """A non-429 response: the host's back-off starts over."""
        with self._lock:
            self._strikes.pop(host.lower(), None)


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` value (delta-seconds or HTTP-date); None if absent
    or unparseable. A date in the past gives 0."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class OffPeakWindow(PiModel):
    """Local-time window a context is collected in (ADR-0005: UAE night). May wrap midnight."""

    start: dtime
    end: dtime
    #: IANA zone of the context (``SourceContext.time_zone``); required, there is no default.
    time_zone: str

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


class RobotsMode(StrEnum):
    """Per source: obey robots.txt (default), or only tag it (Sephora, ADR-0005 override)."""

    OBEY = "obey"
    TAG_ONLY = "tag_only"


class RobotsRefusedError(Exception):
    """robots.txt disallows the URL, or could not be read, and the source obeys it. Not sent."""

    def __init__(self, url: str, tag: RobotsTag) -> None:
        reason = "disallowed by" if tag is RobotsTag.DISALLOWED else "no readable"
        super().__init__(f"{url}: {reason} robots.txt; not fetched")
        self.url = url
        self.tag = tag


@dataclass(frozen=True)
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]


_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
#: Printable ASCII stays as is; space and non-ASCII are UTF-8 percent-encoded.
_PRINTABLE = "".join(chr(c) for c in range(0x21, 0x7F))


def _normalise(value: str) -> str:
    """RFC 9309 §2.2.2 comparison form for a path or pattern. Non-ASCII is percent-encoded,
    escapes are upper-cased, and escaped unreserved characters are decoded."""

    def fix(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else f"%{match.group(1).upper()}"

    return _ESCAPE.sub(fix, quote(value, safe=_PRINTABLE))


def _rule(allow: bool, pattern: str) -> _Rule:
    """An RFC 9309 path pattern: ``*`` matches any run of characters, a final ``$`` anchors the
    end, and everything else is a literal prefix match (after ``_normalise``)."""
    pattern = _normalise(pattern)
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return _Rule(allow, pattern, re.compile(regex + ("$" if anchored else ""), re.DOTALL))


class RobotsRules:
    """One host's robots.txt, evaluated per RFC 9309 (not ``urllib.robotparser``, which has no
    wildcards and uses first match).

    The groups for the most specific matching user-agent token are merged, else the ``*`` groups.
    The longest matching pattern wins, and Allow wins a tie. No match, or no group, means allowed.
    ``/robots.txt`` itself is always allowed.
    """

    def __init__(self, robots_txt: str, user_agent: str = "*") -> None:
        groups: list[tuple[list[str], list[_Rule]]] = []
        agents: list[str] = []
        rules: list[_Rule] = []
        for raw_line in robots_txt.removeprefix("\ufeff").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if rules:
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
            elif key in {"allow", "disallow"} and agents and value:
                rules.append(_rule(key == "allow", value))
        if agents:
            groups.append((agents, rules))
        product = user_agent.lower()
        mine = [r for names, group in groups if product != "*" and product in names for r in group]
        self._rules = mine or [r for names, group in groups if "*" in names for r in group]

    def allows(self, url: str) -> bool:
        """True when ``url`` (path plus query) may be fetched."""
        parts = urlsplit(url)
        target = _normalise((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        if parts.path == "/robots.txt":
            return True
        best: _Rule | None = None
        for rule in self._rules:
            if rule.regex.match(target) is None:
                continue
            if best is None or (len(rule.pattern), rule.allow) > (len(best.pattern), best.allow):
                best = rule
        return best is None or best.allow


def product_token(user_agent: str) -> str:
    """The product token of a User-Agent for robots.txt group matching (RFC 9309 §2.2.1)."""
    token = user_agent.split("/", 1)[0].split(maxsplit=1)
    return token[0] if token else "*"


class RobotsTagger:
    """Evaluates URLs against robots.txt per host. The fetcher decides whether to obey."""

    def __init__(self, user_agent: str = "*") -> None:
        self._user_agent = user_agent
        self._parsers: dict[str, RobotsRules | None] = {}

    def known(self, host: str) -> bool:
        """True once robots.txt was registered or marked unavailable for ``host``."""
        return host.lower() in self._parsers

    def mark_unavailable(self, host: str) -> None:
        """robots.txt could not be read (error, block, 5xx): every URL on the host is UNKNOWN."""
        self._parsers[host.lower()] = None

    def add(self, host: str, robots_txt: str) -> None:
        """Register the robots.txt text for ``host``."""
        self._parsers[host.lower()] = RobotsRules(robots_txt, self._user_agent)

    def tag(self, host: str, url: str) -> RobotsTag:
        """ALLOWED / DISALLOWED per the host's robots.txt; UNKNOWN when none is available."""
        parser = self._parsers.get(host.lower())
        if parser is None:
            return RobotsTag.UNKNOWN
        return RobotsTag.ALLOWED if parser.allows(url) else RobotsTag.DISALLOWED
