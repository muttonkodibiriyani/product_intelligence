"""Promotions as observed (``promotion``; PRC-09, PRC-15).

Advertised dates (what the retailer says) are kept apart from observed bounds (when we saw it).
``currency`` is an addition to blueprint 5.1 so ``min_spend`` is never a bare number.
"""

from typing import Self
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from pi_core.base import PiModel
from pi_core.enums import PromotionMechanic
from pi_core.ids import stable_id
from pi_core.money import Money
from pi_core.types import Amount, CurrencyCode, NonEmptyStr, UtcDatetime


class PromotionRecord(PiModel):
    """One promotion in one source context."""

    source_context_id: UUID
    mechanic: PromotionMechanic
    terms_original: NonEmptyStr
    code: NonEmptyStr | None = None
    rule: dict[str, JsonValue] = Field(default_factory=dict)
    min_spend: Amount | None = None
    currency: CurrencyCode | None = None
    min_qty: int | None = Field(default=None, ge=1)
    advertised_from: UtcDatetime | None = None
    advertised_to: UtcDatetime | None = None
    first_seen_at: UtcDatetime
    last_seen_at: UtcDatetime
    evidence_id: UUID

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if (self.min_spend is None) != (self.currency is None):
            msg = "min_spend and currency must be given together"
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
    def promotion_id(self) -> UUID:
        """Stable id. The mechanic is excluded so better parsing later does not re-key history."""
        return stable_id(
            "promotion",
            self.source_context_id,
            self.terms_original,
            self.code,
            self.advertised_from,
        )

    @property
    def min_spend_money(self) -> Money | None:
        """``min_spend`` as ``Money``."""
        if self.min_spend is None or self.currency is None:
            return None
        return Money(self.min_spend, self.currency)
