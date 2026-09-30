"""``pi.dataset/v2``: the published snapshot every consumer reads (ADR-0007 §6).

The producers (``demo_export``, later the pipeline), the upload validator
(``infra/scripts/publish_dataset.py``), the read API and the dashboard all use this one definition.
The committed JSON Schema (``docs/contracts/pi-dataset-v2.schema.json``) is generated from these
models. The cross-field rules that JSON Schema cannot express are the ``Dataset`` validator below,
documented in ``docs/contracts/pi-dataset-v2.md``.

Rules in short:
* markets, currencies, retailers and categories are data; nothing is a literal;
* money is ``{"amount": "129.00", "minor": 12900, "currency": "AED"}`` at the ISO 4217 exponent,
  never a JSON float; every other fractional number is a decimal string;
* a missing value is an explicit ``null``, with its reason in ``meta.fields`` or ``notObserved``;
* match edges carry the database ``review_state`` verbatim, so ``locked`` stays distinct from
  ``approved``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from pi_core import (
    AvailabilityState,
    CountryCode,
    CurrencyCode,
    LocaleTag,
    MatchClass,
    PiModel,
    ReviewState,
)
from pi_core.money import CURRENCY_EXPONENTS
from pi_core.types import NonEmptyStr, UtcDatetime

SCHEMA_ID = "pi.dataset/v2"

#: A decimal number as text: consumers never see a JSON float.
DECIMAL_TEXT = r"^-?\d+(\.\d+)?$"
DecimalText = Annotated[str, StringConstraints(pattern=DECIMAL_TEXT)]
#: A source register key (ADR-0007 §2), e.g. ``sephora_me``.
SourceKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,62}$")]
#: A scope: a ComparisonSet id or a vertical/category slice, used as a storage path segment.
ScopeId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")]
#: A stable product id within the dataset (also a URL path segment for the API).
ProductId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
#: Human text per locale, e.g. ``{"en": "...", "ar": "..."}``; at least one locale.
LocalizedText = Annotated[dict[LocaleTag, NonEmptyStr], Field(min_length=1)]


class ContractModel(PiModel):
    """Frozen, strict, and camelCase on the wire (``generatedAt``), snake_case in Python."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


class MoneyValue(ContractModel):
    """An exact amount at its currency's ISO 4217 exponent, as text plus integer minor units."""

    amount: DecimalText
    minor: int
    currency: CurrencyCode

    @model_validator(mode="after")
    def _check_exact(self) -> Self:
        exponent = CURRENCY_EXPONENTS[self.currency]
        _, _, fraction = self.amount.partition(".")
        if len(fraction) != exponent:
            msg = f"{self.amount} {self.currency}: amount must have exactly {exponent} decimals"
            raise ValueError(msg)
        if int(Decimal(self.amount).scaleb(exponent)) != self.minor:
            msg = f"{self.amount} {self.currency}: minor {self.minor} does not match amount"
            raise ValueError(msg)
        return self

    @classmethod
    def of(cls, amount: Decimal, currency: str) -> MoneyValue:
        """Build from an exact ``Decimal``; an amount finer than the exponent is an error."""
        exponent = CURRENCY_EXPONENTS.get(currency.upper())
        if exponent is None:
            msg = f"unknown currency {currency!r}"
            raise ValueError(msg)
        quantum = Decimal(1).scaleb(-exponent)
        exact = amount.quantize(quantum)
        if exact != amount:
            msg = f"{amount} {currency} is not exact at {exponent} decimals"
            raise ValueError(msg)
        return cls(amount=str(exact), minor=int(exact.scaleb(exponent)), currency=currency.upper())

    def decimal(self) -> Decimal:
        return Decimal(self.amount)


class MarketInfo(ContractModel):
    country: CountryCode
    currency: CurrencyCode
    time_zone: NonEmptyStr
    locales: Annotated[tuple[LocaleTag, ...], Field(min_length=1)]

    @field_validator("time_zone")
    @classmethod
    def _check_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown time zone {value!r}"
            raise ValueError(msg) from exc
        return value


class RetailerStatus(StrEnum):
    """Coverage of a retailer in this snapshot. Only ``supported`` backs an absence claim."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    PENDING = "pending"
    RETIRED = "retired"


class Retailer(ContractModel):
    id: SourceKey
    name: NonEmptyStr
    country: CountryCode
    status: RetailerStatus
    since: date | None
    note: LocalizedText | None
    logo: HttpUrl | None = None
    #: Recon samples are present (offers marked ``early``); they never count in comparisons.
    early_examples: bool = False


class FieldStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    NOT_COLLECTED = "not_collected"
    NOT_PUBLISHED = "not_published"
    PARSE_FAILURE = "parse_failure"
    BLOCKED = "blocked"


class Capabilities(ContractModel):
    """What this snapshot can answer. All explicit: a consumer never guesses from absence."""

    history: bool
    promotions: bool
    campaigns: bool
    stock: bool
    sizes: bool
    shades: bool
    coverage: bool
    images: bool
    ratings: bool


class Producer(ContractModel):
    name: NonEmptyStr
    version: NonEmptyStr
    commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,40}$")] | None = None


class Meta(ContractModel):
    kind: Literal["snapshot"]
    cutoff: UtcDatetime
    generated_at: UtcDatetime
    scope: ScopeId
    vertical: SourceKey
    markets: Annotated[tuple[MarketInfo, ...], Field(min_length=1)]
    retailers: Annotated[tuple[Retailer, ...], Field(min_length=1)]
    #: Observation dates; every series has exactly one entry per date.
    dates: Annotated[tuple[date, ...], Field(min_length=1)]
    match_stage: NonEmptyStr
    capabilities: Capabilities
    fields: dict[NonEmptyStr, FieldStatus]
    producer: Producer
    #: Synthetic data; the publisher refuses it unless explicitly allowed.
    test: bool = False


class Size(ContractModel):
    value: DecimalText
    unit: NonEmptyStr


class Rating(ContractModel):
    average: DecimalText
    count: Annotated[int, Field(ge=0)]


class Series(ContractModel):
    """One entry per ``meta.dates``; ``null`` means not observed that day, never zero.

    ``price`` is the selling price observed; ``regular`` is the retailer's stated regular (was)
    price. There is no promo series: promotion depth is derived from the two by the metric layer,
    so the contract carries only what was observed.
    """

    price: tuple[MoneyValue | None, ...]
    regular: tuple[MoneyValue | None, ...] | None = None
    availability: tuple[AvailabilityState | None, ...] | None = None

    def lengths(self) -> dict[str, int]:
        found = {"price": len(self.price)}
        for name in ("regular", "availability"):
            values = getattr(self, name)
            if values is not None:
                found[name] = len(values)
        return found

    def money(self) -> list[MoneyValue]:
        return [
            value
            for values in (self.price, self.regular or ())
            for value in values
            if value is not None
        ]


class Evidence(ContractModel):
    captured_at: UtcDatetime
    source: NonEmptyStr
    run_id: NonEmptyStr | None


class Offer(ContractModel):
    currency: CurrencyCode
    sku: NonEmptyStr | None
    url: HttpUrl | None
    size: Size | None
    shade_count: Annotated[int, Field(ge=0)]
    rating: Rating | None
    #: A recon sample, not a collected observation: excluded from coverage and comparisons.
    early: bool
    series: Series
    evidence: Evidence
    image: HttpUrl | None = None

    @model_validator(mode="after")
    def _check_currency(self) -> Self:
        other = sorted({m.currency for m in self.series.money()} - {self.currency})
        if other:
            msg = f"series money in {other} but the offer currency is {self.currency}"
            raise ValueError(msg)
        return self


class DecidedBy(StrEnum):
    HUMAN = "human"
    AUTO = "auto"


class MatchEdge(ContractModel):
    """One edge between two retailers' offers of a product; retailer ids in canonical order."""

    a: SourceKey
    b: SourceKey
    match_class: MatchClass
    #: The database state verbatim. Counted comparisons use ``approved`` and ``locked`` (both
    #: human-confirmed; ``locked`` is also frozen). They stay distinct here: ``locked`` is never
    #: rewritten as ``approved``. ``proposed`` and ``rejected`` are never counted.
    review_state: ReviewState
    decided_by: DecidedBy | None
    confidence: DecimalText | None
    method: NonEmptyStr
    stage: NonEmptyStr

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.a >= self.b:
            msg = f"match edge must be ordered a < b, got {self.a!r}, {self.b!r}"
            raise ValueError(msg)
        undecided = self.review_state is ReviewState.PROPOSED
        if undecided != (self.decided_by is None):
            msg = "decided_by is required exactly when review_state is not proposed"
            raise ValueError(msg)
        if self.confidence is not None and not Decimal(0) <= Decimal(self.confidence) <= 1:
            msg = f"confidence {self.confidence} is outside 0..1"
            raise ValueError(msg)
        return self


class Product(ContractModel):
    id: ProductId
    brand: NonEmptyStr
    name: NonEmptyStr
    #: A path in the vertical profile's taxonomy, most general first.
    category: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    unit: NonEmptyStr | None
    offers: Annotated[dict[SourceKey, Offer], Field(min_length=1)]
    matches: tuple[MatchEdge, ...] = ()
    shades: tuple[NonEmptyStr, ...] = ()
    #: Vertical attributes, validated against the vertical profile (ADR-0007 §4).
    attributes: dict[NonEmptyStr, JsonValue] = Field(default_factory=dict)
    image: HttpUrl | None = None

    @model_validator(mode="after")
    def _check_matches(self) -> Self:
        seen: set[tuple[str, str]] = set()
        for edge in self.matches:
            pair = (edge.a, edge.b)
            missing = sorted({edge.a, edge.b} - set(self.offers))
            if missing:
                msg = f"match edge {pair} names retailers without an offer: {missing}"
                raise ValueError(msg)
            if pair in seen:
                msg = f"duplicate match edge {pair}"
                raise ValueError(msg)
            seen.add(pair)
        return self


class NotObserved(ContractModel):
    retailer: SourceKey
    start: date
    end: date
    categories: tuple[NonEmptyStr, ...] | None
    why: LocalizedText

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.end < self.start:
            msg = f"notObserved {self.retailer}: end {self.end} before start {self.start}"
            raise ValueError(msg)
        return self


class Dataset(ContractModel):
    schema_id: Literal["pi.dataset/v2"] = Field(alias="schema")
    meta: Meta
    products: Annotated[tuple[Product, ...], Field(min_length=1)]
    not_observed: tuple[NotObserved, ...] = ()

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        errors = _reference_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def market_of(self, retailer_id: str) -> MarketInfo:
        country = next(r.country for r in self.meta.retailers if r.id == retailer_id)
        return next(m for m in self.meta.markets if m.country == country)


def _duplicates(values: list[str]) -> list[str]:
    return sorted({v for v in values if values.count(v) > 1})


def _reference_errors(ds: Dataset) -> list[str]:
    """Cross-field rules; each message names the offending path."""
    errors = _meta_errors(ds.meta)
    errors += [f"products: duplicate id {p}" for p in _duplicates([p.id for p in ds.products])]
    errors += _offer_errors(ds)
    retailer_ids = {r.id for r in ds.meta.retailers}
    errors += [
        f"notObserved: unknown retailer {window.retailer}"
        for window in ds.not_observed
        if window.retailer not in retailer_ids
    ]
    return errors


def _meta_errors(meta: Meta) -> list[str]:
    countries = {m.country for m in meta.markets}
    errors = [
        f"meta.markets: duplicate country {c}"
        for c in _duplicates([m.country for m in meta.markets])
    ]
    errors += [
        f"meta.retailers: duplicate id {r}" for r in _duplicates([r.id for r in meta.retailers])
    ]
    errors += [
        f"meta.retailers.{r.id}: country {r.country} not in markets"
        for r in meta.retailers
        if r.country not in countries
    ]
    if list(meta.dates) != sorted(set(meta.dates)):
        errors.append("meta.dates must be strictly increasing")
    if meta.dates[-1] > meta.cutoff.date():
        errors.append(f"meta.dates: {meta.dates[-1]} is after the cutoff {meta.cutoff.date()}")
    if meta.generated_at < meta.cutoff:
        errors.append("meta.generatedAt is before meta.cutoff")
    return errors


def _offer_errors(ds: Dataset) -> list[str]:
    currency = {m.country: m.currency for m in ds.meta.markets}
    retailer_currency = {r.id: currency.get(r.country) for r in ds.meta.retailers}
    n_dates = len(ds.meta.dates)
    errors: list[str] = []
    for product in ds.products:
        for rid, offer in product.offers.items():
            where = f"products.{product.id}.offers.{rid}"
            if rid not in retailer_currency:
                errors.append(f"{where}: unknown retailer")
                continue
            expected = retailer_currency[rid]
            if expected is not None and offer.currency != expected:
                errors.append(f"{where}: currency {offer.currency} != market currency {expected}")
            errors += [
                f"{where}.series.{name}: length {n} != {n_dates} dates"
                for name, n in offer.series.lengths().items()
                if n != n_dates
            ]
    return errors
