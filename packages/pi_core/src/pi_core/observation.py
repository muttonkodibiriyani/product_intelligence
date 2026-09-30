"""Offer observations: one append-only price/availability snapshot (``offer_observation``).

Prices are ``Decimal`` amounts sharing the observation's single ``currency``; use ``money`` to
get them as ``Money``. Every tracked null carries a reason in ``field_state``.

| Field | Requirements |
|---|---|
| ``observation_id`` (derived), ``correction_of`` | DAT-01, DAT-09 |
| ``source_context_id``, ``source_listing_id``, ``variant_id``, ``seller_id`` | DAT-02 |
| ``observed_at``, ``ingested_at``, ``recorded_at``, ``source_effective_from/to`` | DAT-03 |
| ``price_current/regular_stated/promo/member``, ``installment`` | PRC-01, PRC-02 |
| ``price_type`` | PRC-01, PRC-13 |
| ``currency`` and all amounts | PRC-03 |
| ``tax_status`` | PRC-04 |
| ``unit_price_derived``, ``unit_basis`` | PRC-05 |
| ``availability_state``, ``low_stock_flag``, ``available_variants`` | DAT-06, SRC-12 |
| ``rank_in_category``, ``rank_in_search``, ``badges_at_time`` | blueprint 6.2 |
| ``promotion_ids`` | ``offer_promotion``, PRC-09 |
| ``evidence_id`` | DAT-04 |
| ``quality_status`` | DQ-05 |
| ``field_state`` | DQ-02 |
"""

from decimal import Decimal
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from pi_core.base import FieldStateModel, PiModel
from pi_core.context import CollectionContext
from pi_core.enums import AvailabilityState, PriceType, QualityStatus, TaxStatus
from pi_core.ids import stable_id
from pi_core.money import Money
from pi_core.types import Amount, CurrencyCode, NonEmptyStr, UtcDatetime

PriceField = Literal["price_current", "price_regular_stated", "price_promo", "price_member"]

Rating = Annotated[Amount, Field(ge=0)]


class InstallmentPlan(PiModel):
    """A pay-later offer (Tabby, Tamara); never a selling price (PRC-01)."""

    provider: NonEmptyStr
    instalment_count: int = Field(ge=2)
    instalment_amount: Annotated[Amount, Field(gt=0)]


class OfferObservation(FieldStateModel):
    """What one listing offered in one context at one instant. Insert-only; correct via
    ``correction_of``."""

    TRACKED_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "price_current",
            "price_regular_stated",
            "price_promo",
            "price_member",
            "installment",
            "available_variants",
            "low_stock_flag",
            "delivery_promise",
            "rating_value",
            "rating_count",
            "rank_in_category",
        }
    )

    crawl_run_id: UUID
    source_context_id: UUID
    source_listing_id: UUID
    variant_id: UUID | None = None
    # None means the retailer sells first-party; marketplace sellers get an id (CAT-11).
    seller_id: UUID | None = None
    observed_at: UtcDatetime
    ingested_at: UtcDatetime
    # Set when the row is written; parse output has none yet.
    recorded_at: UtcDatetime | None = None
    source_effective_from: UtcDatetime | None = None
    source_effective_to: UtcDatetime | None = None
    price_current: Amount | None
    price_regular_stated: Amount | None
    price_promo: Amount | None
    price_member: Amount | None
    price_type: PriceType
    currency: CurrencyCode
    installment: InstallmentPlan | None
    tax_status: TaxStatus
    unit_price_derived: Amount | None = None
    unit_basis: NonEmptyStr | None = None
    availability_state: AvailabilityState
    available_variants: Annotated[int, Field(ge=0)] | None
    low_stock_flag: bool | None
    delivery_promise: NonEmptyStr | None
    rating_value: Rating | None
    rating_count: Annotated[int, Field(ge=0)] | None
    rank_in_category: Annotated[int, Field(ge=1)] | None
    rank_in_search: dict[str, Annotated[int, Field(ge=1)]] = Field(default_factory=dict)
    badges_at_time: tuple[NonEmptyStr, ...] = ()
    promotion_ids: tuple[UUID, ...] = ()
    evidence_id: UUID
    # None until the quality gate has run.
    quality_status: QualityStatus | None = None
    correction_of: UUID | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.ingested_at < self.observed_at:
            msg = "ingested_at is before observed_at"
            raise ValueError(msg)
        if self.recorded_at is not None and self.recorded_at < self.ingested_at:
            msg = "recorded_at is before ingested_at"
            raise ValueError(msg)
        if (
            self.source_effective_from is not None
            and self.source_effective_to is not None
            and self.source_effective_to < self.source_effective_from
        ):
            msg = "source_effective_to is before source_effective_from"
            raise ValueError(msg)
        if (self.unit_price_derived is None) != (self.unit_basis is None):
            msg = "unit_price_derived and unit_basis must be given together"
            raise ValueError(msg)
        self._check_price_type()
        return self

    def _check_price_type(self) -> None:
        required: dict[PriceType, str] = {
            PriceType.PROMOTIONAL: "price_promo",
            PriceType.MEMBER: "price_member",
            PriceType.INSTALLMENT: "installment",
        }
        name = required.get(self.price_type)
        if name is not None and getattr(self, name) is None:
            msg = f"price_type {self.price_type} requires {name}"
            raise ValueError(msg)
        if self.price_type is PriceType.QUOTE_ONLY and self.price_current is not None:
            msg = "a quote-only offer has no current price (PRC-13)"
            raise ValueError(msg)

    @property
    def observation_id(self) -> UUID:
        """Stable id from the logical key, so replays are idempotent (DAT-02, DAT-09).

        The crawl run is deliberately excluded: a retried run re-observing the same instant is
        the same fact. A correction differs from its original through ``correction_of``.
        """
        return stable_id(
            "offer_observation",
            self.source_context_id,
            self.source_listing_id,
            self.seller_id,
            self.observed_at,
            self.correction_of,
        )

    def money(self, field: PriceField) -> Money | None:
        """A price field as ``Money`` in the observation's currency."""
        amount: Decimal | None = getattr(self, field)
        return None if amount is None else Money(amount, self.currency)

    @property
    def instalment_money(self) -> Money | None:
        """The per-instalment amount as ``Money``."""
        if self.installment is None:
            return None
        return Money(self.installment.instalment_amount, self.currency)

    def check_context(self, context: CollectionContext) -> None:
        """Raise unless this observation belongs to ``context`` and uses its currency."""
        if self.source_context_id != context.source_context.id:
            msg = "observation belongs to a different source context"
            raise ValueError(msg)
        if self.crawl_run_id != context.crawl_run_id:
            msg = "observation belongs to a different crawl run"
            raise ValueError(msg)
        if self.currency != context.currency:
            msg = f"observation currency {self.currency} differs from context {context.currency}"
            raise ValueError(msg)
