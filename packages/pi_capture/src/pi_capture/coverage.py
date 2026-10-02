"""Per-retailer, per-attribute coverage: how often each page-sourced attribute was actually read.

For each retailer and each attribute that a page can show for the vertical, count the pages on
which the attribute was observed, not shown, blocked, unreadable (``parse_failed``), not
applicable, or not looked for. The last bucket is for attributes outside the extractor's
``looked_for`` set on a page: nobody tried, so the page cannot be said to lack them. An attribute
the extractor did look for and no reading mentions is "not shown". Shares are exact ``Decimal``
to four places.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

from pi_capture.model import ProductCapture, ReadingState
from pi_capture.registry import Attribute, Vertical, page_sourced

__all__ = ["AttributeCoverage", "CoverageReport", "RetailerCoverage", "coverage"]

_WORST_FIRST: tuple[ReadingState, ...] = ("parse_failed", "blocked", "not_applicable", "not_shown")
_FOUR_PLACES = Decimal("0.0001")

PageState = Literal[
    "observed", "not_shown", "blocked", "parse_failed", "not_applicable", "not_looked_for"
]


@dataclass(frozen=True, slots=True)
class AttributeCoverage:
    key: str
    level: str
    group: str
    pages: int
    observed: int
    not_shown: int
    blocked: int
    parse_failed: int
    not_applicable: int
    not_looked_for: int
    observed_share: Decimal

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "level": self.level,
            "group": self.group,
            "pages": self.pages,
            "observed": self.observed,
            "not_shown": self.not_shown,
            "blocked": self.blocked,
            "parse_failed": self.parse_failed,
            "not_applicable": self.not_applicable,
            "not_looked_for": self.not_looked_for,
            "observed_share": str(self.observed_share),
        }


@dataclass(frozen=True, slots=True)
class RetailerCoverage:
    retailer: str
    pages: int
    attributes: tuple[AttributeCoverage, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "retailer": self.retailer,
            "pages": self.pages,
            "attributes": [a.to_json() for a in self.attributes],
        }


@dataclass(frozen=True, slots=True)
class CoverageReport:
    vertical: str
    retailers: tuple[RetailerCoverage, ...]

    def to_json(self) -> str:
        data = {"vertical": self.vertical, "retailers": [r.to_json() for r in self.retailers]}
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    def to_markdown(self) -> str:
        """A report a buyer can read: one table per shop, plain words, no codes."""
        lines = [f"# What we could read from {self.vertical} product pages", ""]
        if not self.retailers:
            lines += ["No pages were captured.", ""]
        for r in self.retailers:
            lines += [
                f"## {r.retailer}",
                "",
                f"Pages read: {r.pages}",
                "",
                "| Detail | Where it lives | Area | Read | Not on page | Page blocked "
                "| Could not read | Does not apply | Not looked for | Share read |",
                "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
            lines += [
                f"| {a.key.replace('_', ' ')} | {a.level} | {a.group} | {a.observed} "
                f"| {a.not_shown} | {a.blocked} | {a.parse_failed} | {a.not_applicable} "
                f"| {a.not_looked_for} | {_percent(a.observed_share)} |"
                for a in r.attributes
            ]
            lines.append("")
        return "\n".join(lines)


def _percent(share: Decimal) -> str:
    return f"{(share * 100).quantize(Decimal('0.1'))}%"


def _page_state(capture: ProductCapture, key: str) -> PageState:
    if capture.capture_state == "blocked":
        return "blocked"
    if capture.capture_state == "unparsed":
        return "parse_failed"
    states = {r.state for r in capture.readings if r.key == key}
    if "observed" in states:
        return "observed"
    for state in _WORST_FIRST:
        if state in states:
            return state
    if capture.looked_for and key not in capture.looked_for:
        return "not_looked_for"
    return "not_shown"


def _attribute_coverage(attribute: Attribute, pages: list[ProductCapture]) -> AttributeCoverage:
    counts: dict[PageState, int] = {
        "observed": 0,
        "not_shown": 0,
        "blocked": 0,
        "parse_failed": 0,
        "not_applicable": 0,
        "not_looked_for": 0,
    }
    for page in pages:
        counts[_page_state(page, attribute.key)] += 1
    share = (Decimal(counts["observed"]) / Decimal(len(pages))).quantize(
        _FOUR_PLACES, rounding=ROUND_HALF_EVEN
    )
    return AttributeCoverage(
        key=attribute.key,
        level=str(attribute.level),
        group=str(attribute.group),
        pages=len(pages),
        observed_share=share,
        **counts,
    )


def coverage(captures: Iterable[ProductCapture], *, vertical: Vertical | str) -> CoverageReport:
    """Coverage of every page-sourced attribute applicable to ``vertical``, per retailer."""
    wanted = Vertical(vertical)
    attributes = [a for a in page_sourced() if wanted in a.verticals]
    by_retailer: dict[str, list[ProductCapture]] = {}
    for c in captures:
        by_retailer.setdefault(c.retailer, []).append(c)
    retailers = tuple(
        RetailerCoverage(
            retailer=name,
            pages=len(pages),
            attributes=tuple(_attribute_coverage(a, pages) for a in attributes),
        )
        for name, pages in sorted(by_retailer.items())
    )
    return CoverageReport(vertical=str(wanted), retailers=retailers)
