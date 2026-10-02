"""``pi.dataset/v3`` (ADR-0008): v2 plus label sizes, selling contexts and declared attributes.

v2 (``pi_dataset.models``) is frozen; nothing here changes it. v3 reuses every v2 shape that the
ADR leaves unchanged (money, series, ratings, match edges, markets, retailers, capabilities) and
adds, per ADR-0008 §4:

* ``meta.profile``, ``meta.attributeSet`` and ``meta.contexts``;
* ``Size.label`` and ``Size.system``, with ``value``/``unit`` now nullable together;
* offers keyed by **context** id, with ``Offer.attributes`` and ``evidence.itemKey``;
* ``notObserved[].context``.

The cross-field rules (the context-id rule, identity rules (a)-(c), declared attributes, money
currencies inside attributes, the profile's size rules) are the ``DatasetV3`` validator below.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator, Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, HttpUrl, JsonValue, ValidationError, model_validator

from pi_core import Channel, CurrencyCode
from pi_core.types import NonEmptyStr
from pi_dataset.models import (
    DECIMAL_TEXT,
    ContractModel,
    Evidence,
    LocalizedText,
    MarketInfo,
    MatchEdge,
    Meta,
    MoneyValue,
    NotObserved,
    Offer,
    ProductId,
    SourceKey,
    UnsignedDecimalText,
    _duplicates,
    _meta_errors,
)
from pi_dataset.profiles import (
    AttributeDef,
    AttributeKey,
    AttributeLevel,
    AttributeType,
    ProfileInfo,
    committed_profile,
)

SCHEMA_ID_V3 = "pi.dataset/v3"
#: The profile whose snapshots must stay measured, online-only and on the committed key set.
BEAUTY = "beauty"
_DECIMAL = re.compile(DECIMAL_TEXT)


class SizeV3(ContractModel):
    """The size of the thing priced, as published: a measure, a label, or both. Never converted.

    ``{"value": "250", "unit": "ml"}``, ``{"label": "Medium"}``, or a count such as
    ``{"value": "9", "unit": "pcs", "label": "9 pcs"}``. ``system`` names the label's namespace
    (``alpha``, ``eu``, ``uk``, ``us``) where it matters.
    """

    value: UnsignedDecimalText | None
    unit: NonEmptyStr | None
    label: NonEmptyStr | None
    system: NonEmptyStr | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.value is None and self.label is None:
            msg = "size needs a value or a label"
            raise ValueError(msg)
        if (self.value is None) != (self.unit is None):
            msg = "size value and unit are set together or not at all"
            raise ValueError(msg)
        if self.value is not None and Decimal(self.value) <= 0:
            msg = f"size {self.value} {self.unit} must be positive"
            raise ValueError(msg)
        if self.system is not None and self.label is None:
            msg = "size system needs a label"
            raise ValueError(msg)
        return self


class Location(ContractModel):
    """A branch or area. No coordinates on the wire."""

    id: SourceKey
    label: LocalizedText
    city: NonEmptyStr | None
    area: NonEmptyStr | None


class Context(ContractModel):
    """One priced place an item is sold: retailer, channel and optionally a location (§2)."""

    id: SourceKey
    retailer: SourceKey
    channel: Channel
    location: Location | None
    label: LocalizedText


class MetaV3(Meta):
    #: Kept from v2 (``vertical``) and must equal ``profile.name``.
    profile: ProfileInfo
    attribute_set: tuple[AttributeDef, ...]
    contexts: Annotated[tuple[Context, ...], Field(min_length=1)]


class ItemKeyKind(StrEnum):
    SKU = "sku"
    MENU_ITEM_ID = "menu_item_id"
    SOURCE_PRODUCT_ID = "source_product_id"


class EvidenceV3(Evidence):
    #: The source's own stable item key: the only basis for grouping one retailer's contexts.
    item_key: NonEmptyStr | None
    item_key_kind: ItemKeyKind | None

    @model_validator(mode="after")
    def _check_key(self) -> Self:
        if (self.item_key is None) != (self.item_key_kind is None):
            msg = "evidence itemKey and itemKeyKind are set together or not at all"
            raise ValueError(msg)
        return self


class OfferV3(Offer):
    size: SizeV3 | None  # type: ignore[assignment]  # v3 widens Size (ADR-0008 §1)
    evidence: EvidenceV3  # v3 adds itemKey (ADR-0008 §2)
    #: Declared offer-level keys only (fees, daypart, size-run stock).
    attributes: dict[AttributeKey, JsonValue] = Field(default_factory=dict)
    #: How many of the retailer's listings the producer grouped into this offer (e.g. the shades
    #: of one size); ``null`` when the producer doesn't say. Optional and additive.
    listing_count: Annotated[int, Field(ge=1)] | None = None


class ProductV3(ContractModel):
    id: ProductId
    brand: NonEmptyStr
    name: NonEmptyStr
    category: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    unit: NonEmptyStr | None
    #: Keyed by context id. A retailer's sole context has the retailer's id, so v2 keys still work.
    offers: Annotated[dict[SourceKey, OfferV3], Field(min_length=1)]
    #: Edges between retailers (``a < b`` retailer ids, as in v2), never between contexts.
    matches: tuple[MatchEdge, ...] = ()
    shades: tuple[NonEmptyStr, ...] = ()
    #: Declared product-level keys only.
    attributes: dict[AttributeKey, JsonValue] = Field(default_factory=dict)
    image: HttpUrl | None = None


class NotObservedV3(NotObserved):
    #: One context of the retailer; ``null`` means the whole retailer, as in v2.
    context: SourceKey | None


class DatasetV3(ContractModel):
    schema_id: Literal["pi.dataset/v3"] = Field(alias="schema")
    meta: MetaV3
    products: Annotated[tuple[ProductV3, ...], Field(min_length=1)]
    not_observed: tuple[NotObservedV3, ...] = ()

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        errors = v3_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def market_of(self, retailer_id: str) -> MarketInfo:
        country = next(r.country for r in self.meta.retailers if r.id == retailer_id)
        return next(m for m in self.meta.markets if m.country == country)

    def context(self, context_id: str) -> Context:
        return next(c for c in self.meta.contexts if c.id == context_id)


# ---------------------------------------------------------------- cross-field rules


def v3_errors(ds: DatasetV3) -> list[str]:
    """Every cross-field problem, each naming its path."""
    errors = _meta_errors(ds.meta)
    errors += _profile_errors(ds)
    errors += _context_errors(ds)
    errors += [f"products: duplicate id {p}" for p in _duplicates([p.id for p in ds.products])]
    errors += _offer_errors(ds)
    errors += _identity_errors(ds)
    errors += _attribute_errors(ds)
    errors += _not_observed_errors(ds)
    return errors


def _profile_errors(ds: DatasetV3) -> list[str]:
    meta = ds.meta
    errors: list[str] = []
    if meta.vertical != meta.profile.name:
        errors.append(f"meta.vertical {meta.vertical} != meta.profile.name {meta.profile.name}")
    errors += [
        f"meta.attributeSet: duplicate key {k}"
        for k in _duplicates([a.key for a in meta.attribute_set])
    ]
    committed = committed_profile(meta.profile.name, meta.profile.version)
    ref = f"{meta.profile.name}@{meta.profile.version}"
    if committed is None:
        if meta.profile.name == BEAUTY:
            errors.append(f"meta.profile: {ref} is not a committed profile")
        return errors
    if meta.profile != committed.info():
        errors.append(f"meta.profile: size flags differ from the committed {ref}")
    if meta.attribute_set != committed.attribute_set:
        extra = sorted(
            {a.key for a in meta.attribute_set} - {a.key for a in committed.attribute_set}
        )
        detail = f" (undeclared keys {extra})" if extra else ""
        errors.append(f"meta.attributeSet differs from the committed {ref}{detail}")
    return errors


def _context_errors(ds: DatasetV3) -> list[str]:
    """The context-id rule (ADR-0008 §2): a retailer id names a context iff it is the only one."""
    retailer_ids = {r.id for r in ds.meta.retailers}
    contexts = ds.meta.contexts
    errors = [f"meta.contexts: duplicate id {c}" for c in _duplicates([c.id for c in contexts])]
    by_retailer: dict[str, list[Context]] = defaultdict(list)
    for context in contexts:
        where = f"meta.contexts.{context.id}"
        if context.retailer not in retailer_ids:
            errors.append(f"{where}: unknown retailer {context.retailer}")
            continue
        by_retailer[context.retailer].append(context)
        if context.id in retailer_ids and context.id != context.retailer:
            errors.append(f"{where}: id is another retailer's id")
        if ds.meta.profile.name == BEAUTY and (
            context.channel is not Channel.ONLINE or context.location is not None
        ):
            errors.append(f"{where}: a beauty context is online with no location")
    for retailer in sorted(retailer_ids):
        own = by_retailer.get(retailer, [])
        if not own:
            errors.append(f"meta.contexts: retailer {retailer} has no context")
        elif len(own) == 1 and own[0].id != retailer:
            errors.append(f"meta.contexts.{own[0].id}: a sole context has its retailer's id")
        elif len(own) > 1 and any(c.id == retailer for c in own):
            errors.append(
                f"meta.contexts.{retailer}: retailer {retailer} has {len(own)} contexts, so none "
                "may use the bare retailer id"
            )
    return errors


def _retailer_of(ds: DatasetV3) -> dict[str, str]:
    return {c.id: c.retailer for c in ds.meta.contexts}


def _offer_errors(ds: DatasetV3) -> list[str]:
    currency = {m.country: m.currency for m in ds.meta.markets}
    retailer_currency = {r.id: currency.get(r.country) for r in ds.meta.retailers}
    retailer_of = _retailer_of(ds)
    profile = ds.meta.profile
    n_dates = len(ds.meta.dates)
    errors: list[str] = []
    for product in ds.products:
        for cid, offer in product.offers.items():
            where = f"products.{product.id}.offers.{cid}"
            if cid not in retailer_of:
                errors.append(f"{where}: unknown context")
                continue
            expected = retailer_currency.get(retailer_of[cid])
            if expected is not None and offer.currency != expected:
                errors.append(f"{where}: currency {offer.currency} != market currency {expected}")
            errors += [
                f"{where}.series.{name}: length {n} != {n_dates} dates"
                for name, n in offer.series.lengths().items()
                if n != n_dates
            ]
            errors += _size_errors(where, offer.size, profile)
        offered = {retailer_of[c] for c in product.offers if c in retailer_of}
        seen: set[tuple[str, str]] = set()
        for edge in product.matches:
            pair = (edge.a, edge.b)
            missing = sorted({edge.a, edge.b} - offered)
            if missing:
                errors.append(
                    f"products.{product.id}: match edge {pair} names retailers without an "
                    f"offer: {missing}"
                )
            if pair in seen:
                errors.append(f"products.{product.id}: duplicate match edge {pair}")
            seen.add(pair)
    return errors


def _size_errors(where: str, size: SizeV3 | None, profile: ProfileInfo) -> list[str]:
    if size is None:
        return []
    errors: list[str] = []
    measured_only = not profile.size_labels_comparable or profile.name == BEAUTY
    if size.value is None and measured_only:
        errors.append(f"{where}.size: profile {profile.name} needs a measured size, not a label")
    if profile.size_system_required and size.label is not None and size.system is None:
        errors.append(f"{where}.size: profile {profile.name} needs a system for every label")
    return errors


def _canonical(url: object) -> str:
    return str(url).split("#", 1)[0]


def _identity_errors(ds: DatasetV3) -> list[str]:
    """Identity rules (a)-(c) of ADR-0008 §2, plus the itemKey-or-url rule."""
    retailer_of = _retailer_of(ds)
    contexts_per_retailer: dict[str, int] = defaultdict(int)
    for context in ds.meta.contexts:
        contexts_per_retailer[context.retailer] += 1
    keyed: dict[tuple[str, str], set[str]] = defaultdict(set)
    unkeyed: dict[tuple[str, str], set[str]] = defaultdict(set)
    keyed_urls: dict[tuple[str, str], set[str]] = defaultdict(set)
    errors: list[str] = []
    for product in ds.products:
        by_retailer: dict[str, list[tuple[str, OfferV3]]] = defaultdict(list)
        for cid, offer in product.offers.items():
            if cid in retailer_of:
                by_retailer[retailer_of[cid]].append((cid, offer))
        for retailer, offers in sorted(by_retailer.items()):
            where = f"products.{product.id}: retailer {retailer}"
            keys = {o.evidence.item_key for _, o in offers}
            if len(offers) > 1 and None in keys:
                errors.append(f"{where} has an unkeyed offer next to another of its offers (c)")
            elif len(keys) > 1:
                errors.append(f"{where} offers carry different itemKeys {sorted(map(str, keys))}")
            for cid, offer in offers:
                key = offer.evidence.item_key
                if key is not None:
                    keyed[(retailer, key)].add(product.id)
                    if offer.url is not None:
                        keyed_urls[(retailer, _canonical(offer.url))].add(product.id)
                elif offer.url is not None:
                    unkeyed[(retailer, _canonical(offer.url))].add(product.id)
                elif contexts_per_retailer[retailer] > 1:
                    errors.append(
                        f"products.{product.id}.offers.{cid}: retailer {retailer} has several "
                        "contexts, so the offer needs an itemKey or a url"
                    )
    errors += [
        f"retailer {r} itemKey {k} is in several products {sorted(ps)} (a)"
        for (r, k), ps in sorted(keyed.items())
        if len(ps) > 1
    ]
    errors += [
        f"retailer {r} url {u} is in several products {sorted(ps)} (a)"
        for (r, u), ps in sorted(unkeyed.items())
        if len(ps) > 1
    ]
    errors += [
        f"retailer {r} url {u} is unkeyed in {sorted(ps)} and keyed in "
        f"{sorted(keyed_urls[(r, u)])} (a)"
        for (r, u), ps in sorted(unkeyed.items())
        if (r, u) in keyed_urls and len(ps | keyed_urls[(r, u)]) > 1
    ]
    return errors


def _attribute_errors(ds: DatasetV3) -> list[str]:
    declared = {a.key: a for a in ds.meta.attribute_set}
    market_currencies = frozenset(m.currency for m in ds.meta.markets)
    errors: list[str] = []
    for product in ds.products:
        where = f"products.{product.id}.attributes"
        errors += _values_errors(
            where, product.attributes, AttributeLevel.PRODUCT, declared, market_currencies
        )
        for cid, offer in product.offers.items():
            errors += _values_errors(
                f"products.{product.id}.offers.{cid}.attributes",
                offer.attributes,
                AttributeLevel.OFFER,
                declared,
                frozenset({offer.currency}),
            )
    return errors


def _values_errors(
    where: str,
    values: Mapping[str, JsonValue],
    level: AttributeLevel,
    declared: Mapping[str, AttributeDef],
    currencies: frozenset[CurrencyCode],
) -> list[str]:
    errors: list[str] = []
    for key, value in values.items():
        spec = declared.get(key)
        if spec is None or spec.level is not level:
            errors.append(f"{where}.{key}: not a declared {level} attribute")
            continue
        if not spec.capability:
            errors.append(f"{where}.{key}: declared as not collected (capability false)")
            continue
        problem = _type_problem(spec, value)
        if problem is not None:
            errors.append(f"{where}.{key}: {problem}")
            continue
        for path, money in _money_in(value, f"{where}.{key}"):
            if isinstance(money, str):
                errors.append(f"{path}: {money}")
            elif money.currency not in currencies:
                errors.append(f"{path}: money in {money.currency}, expected {sorted(currencies)}")
    return errors


def _type_problem(spec: AttributeDef, value: JsonValue) -> str | None:
    match spec.type:
        case AttributeType.TEXT:
            ok = isinstance(value, str) and value.strip() != ""
        case AttributeType.ENUM:
            allowed = {v.id for v in spec.values or ()}
            if not isinstance(value, str) or value not in allowed:
                return f"{value!r} is not one of {sorted(allowed)}"
            return None
        case AttributeType.DECIMAL:
            ok = isinstance(value, str) and _DECIMAL.fullmatch(value) is not None
        case AttributeType.MONEY:
            ok = _is_money(value)  # its shape is checked strictly by _money_in
        case AttributeType.BOOL:
            ok = isinstance(value, bool)
        case AttributeType.TEXT_LIST:
            ok = isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
        case AttributeType.OBJECT:
            ok = isinstance(value, dict)
    return None if ok else f"value is not of type {spec.type}"


def _is_money(value: JsonValue) -> bool:
    """Any object with a ``currency`` or ``minor`` is money, so a malformed one is an error.

    ``{amount, minor}`` without a currency is a broken money value, not plain object data.
    """
    return isinstance(value, dict) and not {"currency", "minor"}.isdisjoint(value)


def _money_in(value: JsonValue, path: str) -> Iterator[tuple[str, MoneyValue | str]]:
    """Every money object under ``value``, walking into objects and lists (§2, nit 4)."""
    if isinstance(value, dict):
        if _is_money(value):
            try:
                yield path, MoneyValue.model_validate(value, strict=True)
            except ValidationError as exc:
                yield path, f"bad money: {exc.errors()[0]['msg']}"
            return
        for key, item in value.items():
            yield from _money_in(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _money_in(item, f"{path}.{i}")


def _not_observed_errors(ds: DatasetV3) -> list[str]:
    retailer_ids = {r.id for r in ds.meta.retailers}
    retailer_of = _retailer_of(ds)
    errors: list[str] = []
    for window in ds.not_observed:
        if window.retailer not in retailer_ids:
            errors.append(f"notObserved: unknown retailer {window.retailer}")
        elif window.context is not None and retailer_of.get(window.context) != window.retailer:
            errors.append(
                f"notObserved: context {window.context} is not one of {window.retailer}'s"
            )
    return errors
