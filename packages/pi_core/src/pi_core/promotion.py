"""Promotions as observed (``promotion``; PRC-09, PRC-15).

Advertised dates (what the retailer says) are kept apart from observed bounds (when we saw it).
``min_spend`` always comes with ``min_spend_currency``, so it is never a bare number.
"""

from typing import Self

from pydantic import Field, JsonValue, model_validator

from pi_core.base import PiModel
from pi_core.enums import PromotionMechanic
from pi_core.money import Money
from pi_core.types import CurrencyCode, DbId, NonEmptyStr, PositiveAmount, UtcDatetime


class PromotionRecord(PiModel):
    """One promotion in one source context."""

    source_context_id: DbId
    mechanic: PromotionMechanic
    terms_original: NonEmptyStr
    code: NonEmptyStr | None = None
    rule: dict[str, JsonValue] = Field(default_factory=dict)
    min_spend: PositiveAmount | None = None
    min_spend_currency: CurrencyCode | None = None
    min_qty: int | None = Field(default=None, ge=1)
    advertised_from: UtcDatetime | None = None
    advertised_to: UtcDatetime | None = None
    first_seen_at: UtcDatetime
    last_seen_at: UtcDatetime
    evidence_id: DbId

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if (self.min_spend is None) != (self.min_spend_currency is None):
            msg = "min_spend and min_spend_currency must be given together"
            raise ValueError(msg)
        if self.last_seen_at < self.first_seen_at:
            msg = "last_seen_at is before first_seen_at"
            raise ValueError(msg)
        if (
            self.advertised_from is not None
            and self.advertised_to is not None
            and self.advertised_to < self.advertised_from
        ):
            msg = "advertised_to is before advertised_from"
            raise ValueError(msg)
        return self

    @property
    def min_spend_money(self) -> Money | None:
        """``min_spend`` as ``Money``."""
        if self.min_spend is None or self.min_spend_currency is None:
            return None
        return Money(self.min_spend, self.min_spend_currency)
