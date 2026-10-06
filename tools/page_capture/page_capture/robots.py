"""robots.txt rules, RFC 9309 style and fail-closed (ADR-0006), as pure functions.

- Groups are chosen by our User-Agent: every ``User-agent`` value that is a case-insensitive
  substring of our UA applies, the longest wins, and only when none matches does ``*`` apply.
  Equally specific groups are merged.
- ``*`` matches any run of octets, a trailing ``$`` anchors the end, the most specific matching
  rule (most pattern octets, wildcards excluded) decides, and ``Allow`` wins a tie.
- 404/410 means no published restriction. Any other non-200 status, a transport error, or a 200
  that is really an HTML page makes robots.txt *unavailable*, and every URL on that host is then
  refused. Nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

ALLOW_ALL_STATUSES = (404, 410)
OK = "ok"
ALLOW_ALL = "allow_all"
UNAVAILABLE = "unavailable"
ALLOWED = "allowed"
DISALLOWED = "disallowed"


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str
    specificity: int
    regex: re.Pattern[str]


def compile_rule(pattern: str, allow: bool) -> Rule:
    anchored = pattern.endswith("$")
    core = unquote(pattern[:-1] if anchored else pattern)
    regex = "^" + re.escape(core).replace(r"\*", ".*") + ("$" if anchored else "")
    return Rule(allow, pattern, len(core.replace("*", "")), re.compile(regex, re.DOTALL))


def _match_len(agent: str, ua: str) -> int:
    """How specifically a ``User-agent`` value names us: -1 for none (``*`` is handled apart)."""
    return len(agent) if agent and agent != "*" and agent in ua else -1


def parse(text: str, user_agent: str) -> tuple[tuple[Rule, ...], float | None]:
    """Rules and crawl-delay of the group(s) that apply to ``user_agent``."""
    groups: list[tuple[list[str], list[Rule], float | None]] = []
    agents: list[str] = []
    rules: list[Rule] = []
    delay: float | None = None
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                groups.append((agents, rules, delay))
                agents, rules, delay, in_rules = [], [], None, False
            agents.append(value.lower())
        elif agents:
            in_rules = True
            if key in ("allow", "disallow"):
                if value:  # an empty Disallow is "allow everything": no rule
                    rules.append(compile_rule(value, key == "allow"))
            elif key == "crawl-delay":
                try:
                    delay = float(value)
                except ValueError:
                    delay = None  # a malformed delay carries no information
    if agents:
        groups.append((agents, rules, delay))
    ua = user_agent.lower()
    scored = [(max((_match_len(a, ua) for a in g[0]), default=-1), g) for g in groups]
    best = max((score for score, _ in scored if score >= 0), default=-1)
    selected = (
        [g for score, g in scored if score == best]
        if best >= 0
        else [g for g in groups if "*" in g[0]]
    )
    delays = [g[2] for g in selected if g[2] is not None]
    return tuple(r for g in selected for r in g[1]), (max(delays) if delays else None)


def looks_like_html(body: str) -> bool:
    head = body[:2048].lstrip().lower()
    return head.startswith(("<!doctype", "<html")) or "<html" in head


@dataclass(frozen=True)
class Robots:
    state: str  # ok | allow_all | unavailable
    rules: tuple[Rule, ...] = ()
    crawl_delay: float | None = None
    reason: str = ""

    def verdict(self, url: str) -> str:
        """``allowed``, ``disallowed`` or ``unavailable`` for one URL on this host."""
        if self.state == UNAVAILABLE:
            return UNAVAILABLE
        if self.state == ALLOW_ALL:
            return ALLOWED
        parts = urlsplit(url)
        target = unquote(parts.path or "/")
        if parts.query:
            target += "?" + unquote(parts.query)
        matched = [r for r in self.rules if r.regex.match(target)]
        if not matched:
            return ALLOWED
        best = max(matched, key=lambda r: (r.specificity, r.allow))
        return ALLOWED if best.allow else DISALLOWED


def from_response(status: int | None, content_type: str, body: str, user_agent: str) -> Robots:
    """Classify a robots.txt fetch. ``status`` None is a transport error."""
    if status in ALLOW_ALL_STATUSES:
        return Robots(ALLOW_ALL, reason=f"http {status}: no robots.txt published")
    if status is None:
        return Robots(UNAVAILABLE, reason="transport error reading robots.txt")
    if status != 200:
        return Robots(UNAVAILABLE, reason=f"http {status} reading robots.txt")
    if "html" in content_type.lower() or looks_like_html(body):
        return Robots(UNAVAILABLE, reason="robots.txt answered with an HTML page")
    rules, delay = parse(body, user_agent)
    return Robots(OK, rules, delay, reason=f"parsed {len(rules)} rules")
