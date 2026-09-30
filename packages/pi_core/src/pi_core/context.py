"""Where and how data is collected: sources, source contexts and the per-fetch context.

| Model / field | Blueprint 5.1 | Requirements |
|---|---|---|
| ``Source`` | ``source`` | SRC-01 |
| ``SourceContext`` market, locale, channel, device, cohort | ``source_context`` | SRC-02, SCP-06 |
| ``SourceContext.ladder_rung_current/ladder_rung_max_allowed`` | ``source_context`` | ADR-0003 |
| ``SourceContext.coverage_status/fallback_of`` | ``source_context`` | SCP-02, SCP-08, ADR-0004 |
| ``SourceContext.history_start_at/valid_from/valid_to`` | ``source_context`` | DAT-07, SRC-16 |
| ``CollectionContext`` | ``crawl_run`` (subset) | SRC-02, SRC-09, ADR-0003 |
"""

from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, HttpUrl, JsonValue, field_validator, model_validator

from pi_core.base import PiModel
from pi_core.enums import (
    Channel,
    CoverageStatus,
    Device,
    FetchMethod,
    LadderRung,
    Locale,
    Market,
    SourceKind,
)
from pi_core.types import DbId, NonEmptyStr, UtcDatetime


def check_permitted(rung: LadderRung) -> None:
    """Raise if ``rung`` is forbidden program-wide (``FORBIDDEN_RUNGS``)."""
    if not rung.is_permitted:
        msg = f"rung {rung.name} is forbidden"
        raise ValueError(msg)


def check_rung(rung: LadderRung, method: FetchMethod) -> None:
    """Raise unless ``rung`` is permitted and ``method`` belongs to it (a consistent audit)."""
    check_permitted(rung)
    if method.rung is not rung:
        msg = f"fetch method {method} belongs to rung {method.rung.name}, not {rung.name}"
        raise ValueError(msg)


class Source(PiModel):
    """A retailer or data provider, e.g. Sephora Middle East (``source``)."""

    id: DbId
    name: NonEmptyStr
    kind: SourceKind
    base_url: HttpUrl | None
    notes: str | None = None


class SourceContext(PiModel):
    """One market/locale/channel slice of a source; the unit of coverage and replay (SRC-02).

    The currency is derived from the market, never configured separately, so a context cannot
    state prices in a currency its market does not use.
    """

    id: DbId
    source_id: DbId
    country: Market
    locale: Locale
    channel: Channel = Channel.ONLINE
    location_context: dict[str, JsonValue] = Field(default_factory=dict)
    time_zone: str
    device: Device = Device.DESKTOP
    cohort_id: DbId | None = None
    refresh_policy: dict[str, JsonValue] = Field(default_factory=dict)
    ladder_rung_current: LadderRung = LadderRung.SITE_DATA
    # Paid rungs are opt-in: raising this to PAID_PROXY is the owner's decision (ADR-0003).
    # The cap never permits a forbidden rung: escalation skips STEALTH_BROWSER.
    ladder_rung_max_allowed: LadderRung = LadderRung.EGRESS_VARIATION
    coverage_status: CoverageStatus = CoverageStatus.PENDING
    fallback_of: DbId | None = None
    history_start_at: UtcDatetime | None = None
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None = None

    @field_validator("time_zone")
    @classmethod
    def _check_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown time zone {value!r}"
            raise ValueError(msg) from exc
        return value

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        check_permitted(self.ladder_rung_current)
        if self.ladder_rung_current > self.ladder_rung_max_allowed:
            msg = "ladder_rung_current exceeds ladder_rung_max_allowed"
            raise ValueError(msg)
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            msg = "valid_to must be after valid_from"
            raise ValueError(msg)
        if self.fallback_of == self.id:
            msg = "a context cannot be its own fallback"
            raise ValueError(msg)
        return self

    @property
    def currency(self) -> str:
        """Currency of every price collected in this context."""
        return self.country.currency


class CollectionContext(PiModel):
    """Everything a connector needs to fetch and parse under one context, plus the audit of how.

    ``ladder_rung_used`` and ``fetch_method`` must agree, and the rung may not exceed what the
    source context allows, so an unapproved paid fetch is unrepresentable.
    """

    source_context: SourceContext
    crawl_run_id: DbId
    connector_version: NonEmptyStr
    ladder_rung_used: LadderRung
    fetch_method: FetchMethod

    @model_validator(mode="after")
    def _check_rung(self) -> Self:
        check_rung(self.ladder_rung_used, self.fetch_method)
        if self.ladder_rung_used > self.source_context.ladder_rung_max_allowed:
            msg = (
                f"rung {self.ladder_rung_used.name} exceeds the context's allowed "
                f"{self.source_context.ladder_rung_max_allowed.name}"
            )
            raise ValueError(msg)
        return self

    @property
    def market(self) -> Market:
        """Market being collected."""
        return self.source_context.country

    @property
    def locale(self) -> Locale:
        """Locale being collected."""
        return self.source_context.locale

    @property
    def currency(self) -> str:
        """Currency of every price collected under this context."""
        return self.source_context.currency
