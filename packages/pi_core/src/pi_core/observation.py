"""Offer observations: one append-only price/availability snapshot (``offer_observation``).

Prices are positive ``Decimal`` amounts sharing the observation's single ``currency``; use
``money`` to get them as ``Money``. Every tracked null carries a reason in ``field_state``; a
missing price is never zero.

Availability rules (DAT-06): when ``field_state["availability_state"]`` says the stock could not
be read (``NO_STOCK_CLAIM_REASONS``), the state cannot be ``out_of_stock``; and
``availability_state == low_stock`` exactly when ``low_stock_flag`` is true.

| Field | Requirements |
|---|---|
| ``idempotency_key`` (derived), ``correction_of`` | DAT-01, DAT-09 |
| ``source_context_id``, ``source_listing_id``, ``variant_id``, ``seller_id`` | DAT-02 |
| ``observed_at``, ``ingested_at``, ``recorded_at``, ``source_effective_from/to`` | DAT-03 |
| ``price_current/regular_stated/promo/member``, ``installment`` | PRC-01, PRC-02 |
| ``price_type``, ``price_range_min/max`` | PRC-01, PRC-13 |
| ``currency`` and all amounts | PRC-03 |
| ``tax_status`` | PRC-04 |
| ``unit_price_derived``, ``unit_basis`` | PRC-05 |
| ``availability_state``, ``low_stock_flag``, ``available_variants`` | DAT-06, SRC-12 |
| ``rating_value``, ``rating_scale``, ``rating_count`` | blueprint 5.1 |
| ``rank_in_category``, ``rank_in_search``, ``badges_at_time`` | blueprint 6.2 |
| ``promotion_ids`` | ``offer_promotion``, PRC-09 |
| ``evidence_id`` | DAT-04 |
| ``quality_status`` | DQ-05 |
| ``field_state`` | DQ-02 |
"""

from decimal import Decimal
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from pi_core.base import FieldStateModel, PiModel
from pi_core.context import CollectionContext
from pi_core.enums import AvailabilityState, FieldState, PriceType, QualityStatus, TaxStatus
from pi_core.ids import logical_key
from pi_core.money import Money
from pi_core.types import (
    CurrencyCode,
    DbId,
    NonEmptyStr,
    PositiveAmount,
    UtcDatetime,
    refuse_float,
)

PriceField = Literal[
    "price_current",
    "price_regular_stated",
    "price_promo",
    "price_member",
    "price_range_min",
    "price_range_max",
    "unit_price_derived",
]

#: Availability reasons under which no stock-out may be recorded (DAT-06).
NO_STOCK_CLAIM_REASONS = frozenset(
    {FieldState.BLOCKED, FieldState.PARSE_FAILURE, FieldState.UNKNOWN}
)

#: ``numeric(7,2)``: a rating value or the scale it is out of (e.g. 4.60 of 5).
Rating = Annotated[
    Decimal, BeforeValidator(refuse_float), Field(ge=0, max_digits=7, decimal_places=2)
]


class InstallmentPlan(PiModel):
    """A pay-later offer (Tabby, Tamara); never a selling price (PRC-01)."""

    provider: NonEmptyStr
    instalment_count: int = Field(ge=2)
    instalment_amount: PositiveAmount


class OfferObservation(FieldStateModel):
    """What one listing offered in one context at one instant. Insert-only; correct via
    ``correction_of``."""

    QUALIFIED_FIELDS: ClassVar[frozenset[str]] = frozenset({"availability_state"})
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

    crawl_run_id: DbId
    source_context_id: DbId
    source_listing_id: DbId
    variant_id: DbId | None = None
    # None means the retailer sells first-party; marketplace sellers keep their source id (CAT-11).
    seller_id: NonEmptyStr | None = None
    observed_at: UtcDatetime
    ingested_at: UtcDatetime
    # Set when the row is written; parse output has none yet.
    recorded_at: UtcDatetime | None = None
    source_effective_from: UtcDatetime | None = None
    source_effective_to: UtcDatetime | None = None
    price_current: PositiveAmount | None
    price_regular_stated: PositiveAmount | None
    price_promo: PositiveAmount | None
    price_member: PositiveAmount | None
    price_type: PriceType
    # Set exactly when price_type is RANGE; a range never collapses into price_current (PRC-13).
    price_range_min: PositiveAmount | None = None
    price_range_max: PositiveAmount | None = None
    currency: CurrencyCode
    installment: InstallmentPlan | None
    tax_status: TaxStatus
    unit_price_derived: PositiveAmount | None = None
    unit_basis: NonEmptyStr | None = None
    availability_state: AvailabilityState
    available_variants: Annotated[int, Field(ge=0)] | None
    low_stock_flag: bool | None
    delivery_promise: NonEmptyStr | None
    rating_value: Rating | None
    # Required with rating_value: the scale it is out of.
    rating_scale: Annotated[Rating, Field(gt=0)] | None = None
    rating_count: Annotated[int, Field(ge=0)] | None
    rank_in_category: Annotated[int, Field(ge=1)] | None
    rank_in_search: dict[str, Annotated[int, Field(ge=1)]] = Field(default_factory=dict)
    badges_at_time: tuple[NonEmptyStr, ...] = ()
    promotion_ids: tuple[DbId, ...] = ()
    evidence_id: DbId
    # None until the quality gate has run.
    quality_status: QualityStatus | None = None
    correction_of: DbId | None = None

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
        if (self.rating_value is None) != (self.rating_scale is None):
            msg = "rating_value and rating_scale must be given together"
            raise ValueError(msg)
        if (
            self.rating_value is not None
            and self.rating_scale is not None
            and self.rating_value > self.rating_scale
        ):
            msg = "rating_value exceeds rating_scale"
            raise ValueError(msg)
        self._check_price_type()
        self._check_availability()
        return self

    def _check_availability(self) -> None:
        reason = self.field_state.get("availability_state")
        if (
            reason in NO_STOCK_CLAIM_REASONS
            and self.availability_state is AvailabilityState.OUT_OF_STOCK
        ):
            msg = f"availability marked {reason}: cannot record out_of_stock (DAT-06)"
            raise ValueError(msg)
        if (self.availability_state is AvailabilityState.LOW_STOCK) != (
            self.low_stock_flag is True
        ):
            msg = "availability_state low_stock and low_stock_flag must agree"
            raise ValueError(msg)

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
        if self.price_type in {PriceType.QUOTE_ONLY, PriceType.RANGE} and (
            self.price_current is not None
        ):
            msg = f"a {self.price_type} offer has no single current price (PRC-13)"
            raise ValueError(msg)
        is_range = self.price_type is PriceType.RANGE
        low, high = self.price_range_min, self.price_range_max
        if is_range and (low is None or high is None):
            msg = "price_type range requires price_range_min and price_range_max"
            raise ValueError(msg)
        if not is_range and (low is not None or high is not None):
            msg = "price_range_min/max are only set for price_type range"
            raise ValueError(msg)
        if low is not None and high is not None and low > high:
            msg = "price_range_min exceeds price_range_max"
            raise ValueError(msg)

    @property
    def idempotency_key(self) -> str:
        """``offer_observation.idempotency_key``: replays of the same fact collide (DAT-02, DAT-09).

        The crawl run is deliberately excluded: a retried run re-observing the same instant is
        the same fact. A correction differs from its original through ``correction_of``.
        """
        return logical_key(
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
