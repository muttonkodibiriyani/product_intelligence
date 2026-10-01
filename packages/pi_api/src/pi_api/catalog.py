"""Catalogue views: ``/v1/meta``, ``/v1/products``, ``/v1/products/{id}[/history]`` (design §6).

Pure functions of a validated dataset and typed queries; the HTTP layer lives in ``app``.
Admin-only fields are in separate models (``AdminEvidence``), never filtered after the fact.

The dataset is read as ``pi.dataset/v3`` (a v2 snapshot is served through its upgrade). Offers
are keyed by context id; a beauty retailer is its own sole context, so its keys are its retailer
ids, as in v2. Fields added for v3 (ADR-0008 step 4b) are additive and come last.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from functools import partial
from itertools import combinations
from types import MappingProxyType
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import Field

from pi_api.floor import PriceFlag
from pi_core import AvailabilityState, Channel, MatchClass, ReviewState
from pi_dataset import (
    Capabilities,
    Context,
    ContractModel,
    DatasetV3,
    FieldStatus,
    MoneyValue,
    OfferV3,
    ProductV3,
    Rating,
    RetailerStatus,
    Size,
    SizeV3,
)
from pi_dataset.profiles import AttributeDef, ProfileInfo
from pi_dataset.text import SourceText
from pi_metrics import COUNTED_STATES, Excluded, Metric, ProductFilter, Reason, Status
from pi_metrics.compare import Gap, pair_with_labels
from pi_metrics.promotions import depth
from pi_metrics.view import AmbiguousContext, context, price_on, regular_on

MAX_LIMIT = 100
MAX_VALUES = 25
MAX_TEXT = 120

ShortText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
Values = Annotated[tuple[ShortText, ...], Field(max_length=MAX_VALUES)]
DecimalText = Annotated[str, Field(pattern=r"^\d{1,12}(\.\d{1,6})?$")]
#: ``<key>:<value>``; the key is a declared facet attribute (``meta.attributeSet``), the value
#: has no C0/C1 control or U+2028/U+2029 characters (each could split a log line).
_ATTR_TEXT = r"^[a-z][A-Za-z0-9_]{1,62}:[^\x00-\x1f\x7f-\x9f\u2028\u2029]+$"
AttrText = Annotated[str, Field(pattern=_ATTR_TEXT, max_length=MAX_TEXT)]


#: Per retailer, the hosts its evidence (or image) URLs may point at (``Settings``).
EvidenceHosts = Mapping[str, frozenset[str]]
NO_HOSTS: EvidenceHosts = MappingProxyType({})


class InvalidQueryError(ValueError):
    """A well-formed request that can't be answered as asked (422)."""


class ProductNotFoundError(Exception):
    """No product with that id in the selected dataset."""


class StaleCursorError(Exception):
    """The cursor's generation is no longer loaded (409)."""


class ScopeQuery(ContractModel):
    market: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    scope: ShortText | None = None


class CoverageQuery(ScopeQuery):
    retailer: Annotated[tuple[ShortText, ...], Field(max_length=MAX_VALUES)] = ()


# ---------------------------------------------------------------- meta


class RetailerView(ContractModel):
    id: str
    name: SourceText
    country: str
    status: RetailerStatus
    since: date | None
    note: dict[str, SourceText] | None


class CategoryNode(ContractModel):
    key: SourceText
    count: int
    #: Empty: the tree lists category codes only. A product's ``category[1:]`` is the retailer's
    #: breadcrumb, not a sub-code, so it is never listed here.
    children: tuple[CategoryNode, ...] = ()


class ScopeRef(ContractModel):
    markets: tuple[str, ...]
    scope: str
    cutoff: datetime
    generation: str


class MetaView(ContractModel):
    datasets: tuple[ScopeRef, ...]
    kind: str
    vertical: str
    cutoff: datetime
    dates: tuple[date, ...]
    match_stage: str
    retailers: tuple[RetailerView, ...]
    capabilities: Capabilities
    fields: dict[str, FieldStatus]
    categories: tuple[CategoryNode, ...]
    test: bool
    #: Where each offer was observed: retailer, channel, location (ADR-0008 §2). A retailer with
    #: one context has it under the retailer's own id.
    contexts: tuple[Context, ...]
    profile: ProfileInfo
    #: The profile's attributes; a ``facet`` one is usable as ``attr=<key>:<value>``.
    attribute_set: tuple[AttributeDef, ...]


def retailer_views(ds: DatasetV3) -> tuple[RetailerView, ...]:
    return tuple(
        RetailerView(
            id=r.id,
            name=r.name,
            country=r.country,
            status=r.status,
            since=r.since,
            note=r.note,
        )
        for r in ds.meta.retailers
    )


def category_tree(products: Iterable[ProductV3]) -> tuple[CategoryNode, ...]:
    """The category codes (``category[0]``), counted in products.

    A product's ``category`` is ``(code,)`` or ``(code, L1, L2, L3)``, where ``L1..`` is the
    retailer's own breadcrumb (#108). The breadcrumb is not a sub-code, so it adds no children.
    """
    top = Counter(p.category[0] for p in products)
    return tuple(CategoryNode(key=key, count=count) for key, count in sorted(top.items()))


def meta_view(ds: DatasetV3, datasets: tuple[ScopeRef, ...]) -> Metric[MetaView]:
    m = ds.meta
    view = MetaView(
        datasets=datasets,
        kind=m.kind,
        vertical=m.vertical,
        cutoff=m.cutoff,
        dates=m.dates,
        match_stage=m.match_stage,
        retailers=retailer_views(ds),
        capabilities=m.capabilities,
        fields=dict(m.fields),
        categories=category_tree(ds.products),
        test=m.test,
        contexts=m.contexts,
        profile=m.profile,
        attribute_set=m.attribute_set,
    )
    return Metric[MetaView](status=Status.OK, data=view, as_of=m.dates[-1])


# ---------------------------------------------------------------- products


class ProductSort(StrEnum):
    NAME = "name"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    #: Need exactly two ``retailer`` values (base first). Signed gap pct, so direction is kept:
    #: ``gap`` puts other-dearest first, ``gap_asc`` other-cheapest first; uncounted last by id.
    GAP = "gap"
    GAP_ASC = "gap_asc"


GAP_SORTS = frozenset({ProductSort.GAP, ProductSort.GAP_ASC})


class ProductFilters(ContractModel):
    """``/v1/products`` filters and order, shared with ``/v1/export/products``. Unknown keys are
    rejected."""

    market: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    scope: ShortText | None = None
    q: ShortText | None = None
    brand: Values = ()
    category: Values = ()
    retailer: Annotated[
        Values,
        Field(
            description=(
                "Repeatable; a retailer id (all its contexts) or a context id. With exactly two "
                "different values the order matters: the first is the base of each card's gap "
                "and of sort=gap/gap_asc, and each must name one context."
            )
        ),
    ] = ()
    matched: bool | None = None
    price_min: DecimalText | None = None
    price_max: DecimalText | None = None
    sort: ProductSort = ProductSort.NAME
    channel: Annotated[
        tuple[Channel, ...],
        Field(
            max_length=MAX_VALUES,
            description="Repeatable. Narrows the offers shown to contexts on these channels.",
        ),
    ] = ()
    location: Annotated[
        Values,
        Field(description="Repeatable. Narrows the offers shown to contexts at these locations."),
    ] = ()
    attr: Annotated[
        tuple[AttrText, ...],
        Field(
            max_length=MAX_VALUES,
            description=(
                "Repeatable ``<key>:<value>`` on a declared facet attribute. Values of one key "
                "are alternatives; different keys must all match."
            ),
        ),
    ] = ()


class ProductQuery(ProductFilters):
    limit: int = Field(default=25, ge=1, le=MAX_LIMIT)
    cursor: Annotated[str, Field(max_length=512)] | None = None


class CardMatch(ContractModel):
    a: str
    b: str
    match_class: MatchClass
    review_state: ReviewState
    confidence: str | None


class PairGap(ContractModel):
    """One context pair's gap on the latest date, or why it isn't counted (design §7.2)."""

    base: str
    other: str
    gap: Gap | None
    excluded_reason: Excluded | None
    #: On a counted pair whose equal measures carry different published labels: the base's
    #: label, then the other's (the ``size_labels_differ`` caveat). Otherwise null.
    size_labels: tuple[SourceText, SourceText] | None = None


def pair_gap(ds: DatasetV3, product: ProductV3, base: str, other: str) -> PairGap:
    row, labels = pair_with_labels(ds, product, base, other, len(ds.meta.dates) - 1)
    return PairGap(
        base=base,
        other=other,
        gap=row.gap,
        excluded_reason=row.excluded_reason,
        size_labels=labels,
    )


def measure(size: SizeV3 | None) -> Size | None:
    """The v2-shaped measure of a size; null for a label-only size."""
    if size is None or size.value is None or size.unit is None:
        return None
    return Size(value=size.value, unit=size.unit)


def size_label(size: SizeV3 | None) -> tuple[str | None, str | None]:
    """The published label (``Medium``, ``38``), never converted, and its system (``eu``)."""
    return (None, None) if size is None else (size.label, size.system)


def _first_label(offers: Iterable[OfferV3]) -> tuple[str | None, str | None]:
    return next((size_label(o.size) for o in offers if o.size and o.size.label), (None, None))


class ProductCard(ContractModel):
    id: str
    brand: SourceText
    name: SourceText
    category: tuple[SourceText, ...]
    size: Size | None
    #: API 1.3.0: the product's image, else the first shown offer's (by context id): an https
    #: URL on its retailer's ``PI_API_IMAGE_HOSTS``, else null. Never invented.
    image: SourceText | None = None
    prices: dict[str, MoneyValue | None]
    #: API 1.7.1: why a ``prices`` entry is null when it was published but withheld:
    #: ``invalid_low`` for a price of 0.01 or less (``pi_api.floor``). Only flagged contexts.
    price_flags: dict[str, PriceFlag] = Field(default_factory=dict)
    matches: tuple[CardMatch, ...]
    #: Set when the search names exactly two retailers (base first); otherwise null.
    gap: PairGap | None = None
    #: The first published size label of the shown offers, if any (``size`` is the measure),
    #: and the label's system (``eu``, ``alpha``) where it matters.
    size_label: SourceText | None = None
    size_system: SourceText | None = None


class FacetCount(ContractModel):
    key: SourceText
    count: int


class Facets(ContractModel):
    brand: tuple[FacetCount, ...]
    category: tuple[FacetCount, ...]
    retailer: tuple[FacetCount, ...]
    #: API 1.3.0: per ``facet`` attribute of ``meta.attributeSet`` (in its order), the products
    #: per value. Values that fold equal count once, under their least raw form; send it back as
    #: ``attr=<key>:<value>``. Only values ``attr`` accepts are listed, at most
    #: ``ATTR_FACET_LIMIT`` per key: the most products first, then shown in raw order. A value
    #: is trimmed (API 1.4.0) before it is folded, listed or matched, so " Matte " is "Matte";
    #: one with a control character inside is still not listed.
    attributes: dict[str, tuple[FacetCount, ...]]
    #: API 1.4.0: the keys of ``attributes`` that had more than ``ATTR_FACET_LIMIT`` listable
    #: values, so the list is not exhaustive (in ``meta.attributeSet`` order).
    attributes_truncated: tuple[str, ...] = ()


class ProductPage(ContractModel):
    total: int
    next_cursor: str | None
    items: tuple[ProductCard, ...]
    facets: Facets


def fold(text: str) -> str:
    """Case- and accent-insensitive key; Arabic letter variants folded to a base form."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.translate(_ARABIC_FOLD)


#: Hamza/madda alef to bare alef, alef maqsura to yeh, teh marbuta to heh; tatweel dropped.
_ARABIC_FOLD = str.maketrans(
    {
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0622": "\u0627",
        "\u0649": "\u064a",
        "\u0629": "\u0647",
        "\u0640": None,
    }
)


def _latest(ds: DatasetV3, offer: OfferV3) -> MoneyValue | None:
    return price_on(offer, len(ds.meta.dates) - 1)


#: A set of context ids, or ``None`` for every context.
Shown = frozenset[str] | None


def _visible(product: ProductV3, shown: Shown) -> list[tuple[str, OfferV3]]:
    return [(c, o) for c, o in product.offers.items() if shown is None or c in shown]


def _low_price(ds: DatasetV3, product: ProductV3, contexts: Shown) -> Decimal | None:
    prices = [
        p.decimal()
        for _, o in _visible(product, contexts)
        if not o.early and (p := _latest(ds, o)) is not None
    ]
    return min(prices, default=None)


def _decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:  # pragma: no cover - the pattern already guarantees a decimal
        raise InvalidQueryError(text) from None


def card(
    ds: DatasetV3,
    product: ProductV3,
    pair: tuple[str, str] | None = None,
    shown: Shown = None,
    images: EvidenceHosts = NO_HOSTS,
) -> ProductCard:
    offers = _visible(product, shown)
    label, system = _first_label(o for _, o in offers)
    return ProductCard(
        id=product.id,
        brand=product.brand,
        name=product.name,
        category=product.category,
        size=next((m for _, o in offers if (m := measure(o.size)) is not None), None),
        prices={c: _latest(ds, o) for c, o in sorted(offers)},
        matches=tuple(
            CardMatch(
                a=e.a,
                b=e.b,
                match_class=e.match_class,
                review_state=e.review_state,
                confidence=e.confidence,
            )
            for e in product.matches
        ),
        gap=None if pair is None else pair_gap(ds, product, *pair),
        image=card_image(ds, product, offers, images),
        size_label=label,
        size_system=system,
    )


def card_image(
    ds: DatasetV3, product: ProductV3, offers: Iterable[tuple[str, OfferV3]], hosts: EvidenceHosts
) -> str | None:
    """The product's image on a host of a retailer that shows it, else a shown offer's own."""
    owner = {c.id: c.retailer for c in ds.meta.contexts}
    shown = sorted((c, o) for c, o in offers if not o.early)
    retailers = sorted({owner[c] for c, _ in shown})
    candidates = [(product.image, r) for r in retailers] + [(o.image, owner[c]) for c, o in shown]
    return next(
        (url for image, r in candidates if (url := evidence_url(image, r, hosts)) is not None), None
    )


def _matched(product: ProductV3) -> bool:
    return any(
        e.match_class is MatchClass.EXACT and e.review_state in COUNTED_STATES
        for e in product.matches
    )


def _named(ds: DatasetV3, ids: Iterable[str]) -> frozenset[str]:
    """The contexts ``ids`` name: a context id itself, a retailer id every context it has."""
    return frozenset(c.id for c in ds.meta.contexts for i in ids if i in (c.id, c.retailer))


def shown_contexts(ds: DatasetV3, query: ProductFilters) -> Shown:
    """The contexts whose offers a card shows: those on the ``channel`` and ``location`` asked
    for, or every context when neither is given (ADR-0008 §2, "narrow the offers shown")."""
    if not query.channel and not query.location:
        return None
    return frozenset(
        c.id
        for c in ds.meta.contexts
        if (not query.channel or c.channel in query.channel)
        and (not query.location or (c.location is not None and c.location.id in query.location))
    )


def _within(named: frozenset[str] | None, shown: Shown) -> Shown:
    if named is None:
        return shown
    return named if shown is None else named & shown


def _attr_texts(value: object) -> dict[str, str]:
    """A stored attribute value as ``{folded: raw}`` texts a filter value can equal."""
    if isinstance(value, bool):
        text = "true" if value else "false"
        return {text: text}
    if isinstance(value, str | int | Decimal):
        text = str(value).strip()  # " Matte " is "Matte": label, fold and filter agree
        return {fold(text): text}  # blank text is refused at load
    if isinstance(value, list | tuple):
        texts: dict[str, str] = {}
        for item in value:
            for folded, raw in _attr_texts(item).items():
                texts[folded] = min(raw, texts.get(folded, raw))
        return texts
    return {}  # an object never equals a filter value


def _product_attr_texts(product: ProductV3, shown: Shown, key: str) -> dict[str, str]:
    """``key``'s texts on the product and its shown non-early offers."""
    texts: dict[str, str] = {}
    offers = [o for _, o in _visible(product, shown) if not o.early]
    for source in (product.attributes, *(o.attributes for o in offers)):
        for folded, raw in _attr_texts(source.get(key)).items():
            texts[folded] = min(raw, texts.get(folded, raw))
    return texts


def _attr_filters(ds: DatasetV3, query: ProductFilters) -> dict[str, set[str]]:
    facets = {a.key for a in ds.meta.attribute_set if a.facet}
    wanted: dict[str, set[str]] = {}
    for item in query.attr:
        key, value = item.split(":", 1)
        if key not in facets:
            msg = f"attr {key!r} is not a facet attribute of this dataset"
            raise InvalidQueryError(msg)
        wanted.setdefault(key, set()).add(fold(value.strip()))
    return wanted


def _has_attr(product: ProductV3, shown: Shown, key: str, values: set[str]) -> bool:
    return not values.isdisjoint(_product_attr_texts(product, shown, key))


Check = Callable[[ProductV3], bool]


def _predicates(ds: DatasetV3, query: ProductFilters) -> dict[str, Check]:
    """One predicate per filter, so each facet can drop its own (design §6, FE ask 6)."""
    brands = {fold(b) for b in query.brand}
    categories = {fold(c) for c in query.category}
    shown = shown_contexts(ds, query)
    named = _within(_named(ds, query.retailer), shown) if query.retailer else None
    words = fold(query.q).split() if query.q else []
    low, high = _decimal(query.price_min), _decimal(query.price_max)
    priced_in = _within(named, shown)
    wanted = _attr_filters(ds, query)
    checks: dict[str, Check] = {}
    if words:
        checks["q"] = lambda p: all(w in fold(f"{p.brand} {p.name} {p.id}") for w in words)
    if brands:
        checks["brand"] = lambda p: fold(p.brand) in brands
    if categories:
        checks["category"] = lambda p: fold(p.category[0]) in categories
    if named is not None:
        checks["retailer"] = lambda p: any(c in named and not o.early for c, o in p.offers.items())
    if shown is not None:
        checks["context"] = lambda p: any(c in shown and not o.early for c, o in p.offers.items())
    if query.matched is not None:
        is_matched = query.matched
        checks["matched"] = lambda p: _matched(p) is is_matched
    if low is not None or high is not None:

        def priced(p: ProductV3) -> bool:
            price = _low_price(ds, p, priced_in)
            return (
                price is not None
                and (low is None or price >= low)
                and (high is None or price <= high)
            )

        checks["price"] = priced
    for key, values in wanted.items():  # one check per key, so its facet can drop it
        checks[f"attr:{key}"] = partial(_has_attr, shown=shown, key=key, values=values)
    return checks


def _passes(product: ProductV3, checks: dict[str, Check], skip: str) -> bool:
    return all(check(product) for name, check in checks.items() if name != skip)


def _facets(ds: DatasetV3, checks: dict[str, Check], shown: Shown) -> Facets:
    """Counts in products; a retailer counts a product once, however many contexts offer it."""
    brand: Counter[str] = Counter()
    category: Counter[str] = Counter()
    retailer: Counter[str] = Counter()
    owner = {c.id: c.retailer for c in ds.meta.contexts}
    for p in ds.products:
        if _passes(p, checks, "brand"):
            brand[p.brand] += 1
        if _passes(p, checks, "category"):
            category[p.category[0]] += 1
        if _passes(p, checks, "retailer"):
            retailer.update({owner[c] for c, o in _visible(p, shown) if not o.early})

    def counts(counter: Counter[str]) -> tuple[FacetCount, ...]:
        return tuple(FacetCount(key=k, count=n) for k, n in sorted(counter.items()))

    attrs = {a.key: _attr_facet(ds, checks, shown, a.key) for a in ds.meta.attribute_set if a.facet}
    return Facets(
        brand=counts(brand),
        category=counts(category),
        retailer=counts(retailer),
        attributes={k: values for k, (values, _) in attrs.items()},
        attributes_truncated=tuple(k for k, (_, cut) in attrs.items() if cut),
    )


#: Values per attribute facet; a long tail of one-off retailer texts would swamp the chips.
ATTR_FACET_LIMIT = 50
_ATTR_FILTER = re.compile(_ATTR_TEXT)


def _filterable(key: str, value: str) -> bool:
    """Whether ``attr=<key>:<value>`` passes ``AttrText``, so a listed value never 422s."""
    text = f"{key}:{value}"
    return len(text) <= MAX_TEXT and _ATTR_FILTER.match(text) is not None


def _attr_facet(
    ds: DatasetV3, checks: dict[str, Check], shown: Shown, key: str
) -> tuple[tuple[FacetCount, ...], bool]:
    """Products per folded value of ``key``, under every filter but ``key``'s own, and
    whether values beyond ``ATTR_FACET_LIMIT`` were left out."""
    counter: Counter[str] = Counter()
    raw: dict[str, str] = {}
    for p in ds.products:
        if _passes(p, checks, f"attr:{key}"):
            texts = _product_attr_texts(p, shown, key)
            counter.update(texts.keys())
            for folded, text in texts.items():
                raw[folded] = min(text, raw.get(folded, text))
    listed = [(f, n) for f, n in counter.items() if _filterable(key, raw[f])]
    top = sorted(listed, key=lambda i: (-i[1], raw[i[0]]))[:ATTR_FACET_LIMIT]
    counts = tuple(FacetCount(key=raw[f], count=n) for f, n in sorted(top, key=lambda i: raw[i[0]]))
    return counts, len(listed) > ATTR_FACET_LIMIT


#: Filters added in API 1.2.0: left out of the digest while unset, so a cursor issued before
#: them still continues.
_ADDED_FILTERS = ("channel", "location", "attr")


def filters_digest(query: ContractModel, extra: str = "") -> str:
    """Binds a cursor to the filters (and ``extra``, e.g. the role) it was issued for."""
    fields = query.model_dump(mode="json", exclude={"cursor", "limit"})
    for name in _ADDED_FILTERS:
        if fields.get(name) == []:
            del fields[name]
    raw = json.dumps({"q": fields, "x": extra}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def encode_cursor(generation: str, offset: int, digest: str) -> str:
    raw = json.dumps({"g": generation, "o": offset, "f": digest}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, generation: str, digest: str) -> int:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        g, offset, f = raw["g"], raw["o"], raw["f"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        msg = "cursor is not valid"
        raise InvalidQueryError(msg) from None
    if not isinstance(offset, int) or offset < 0:
        msg = "cursor is not valid"
        raise InvalidQueryError(msg)
    if f != digest:
        msg = "cursor belongs to different filters"
        raise InvalidQueryError(msg)
    if g != generation:
        raise StaleCursorError
    return offset


def _unknown_values(ds: DatasetV3, query: ProductFilters) -> None:
    known = {r.id for r in ds.meta.retailers} | {c.id for c in ds.meta.contexts}
    unknown = sorted(set(query.retailer) - known)
    if unknown:
        msg = f"unknown retailer or context {unknown[0]!r}"
        raise InvalidQueryError(msg)
    places = {c.location.id for c in ds.meta.contexts if c.location is not None}
    if not set(query.location) <= places:
        msg = "unknown location"  # free text: never echoed
        raise InvalidQueryError(msg)


def _sole(ds: DatasetV3, value: str) -> str | None:
    """The one context ``value`` names, or ``None`` for a retailer with several."""
    try:
        return context(ds, value).id
    except AmbiguousContext:
        return None


def _search_pair(ds: DatasetV3, query: ProductFilters) -> tuple[str, str] | None:
    """The two contexts a card's gap compares, if the search names exactly two.

    A retailer with several contexts names none of them: its cards carry no gap, and
    ``sort=gap/gap_asc`` is refused (422 ``ambiguous_context``) rather than guess one.
    """
    if len(query.retailer) == 2 and query.retailer[0] != query.retailer[1]:
        base, other = (_sole(ds, v) for v in query.retailer)
        if base is not None and other is not None:
            return base, other
        if query.sort in GAP_SORTS:
            for value in query.retailer:
                context(ds, value)  # raises AmbiguousContext for the first ambiguous one
    if query.sort in GAP_SORTS:
        msg = f"sort={query.sort} needs exactly two different retailer values (base first)"
        raise InvalidQueryError(msg)
    return None


def _by_gap(
    ds: DatasetV3, hits: list[ProductV3], pair: tuple[str, str], *, ascending: bool
) -> list[ProductV3]:
    sign = 1 if ascending else -1
    gaps = [(p, pair_gap(ds, p, *pair).gap) for p in hits]
    # Ties break on id ascending in both directions, as the price sorts do.
    counted = sorted(
        ((p, g) for p, g in gaps if g is not None), key=lambda pg: (sign * pg[1].pct, pg[0].id)
    )
    return [p for p, _ in counted] + sorted((p for p, g in gaps if g is None), key=lambda p: p.id)


def _ordered(
    ds: DatasetV3,
    query: ProductFilters,
    pair: tuple[str, str] | None,
    checks: dict[str, Check],
) -> list[ProductV3]:
    """Every product passing the filters, in the query's sort order."""
    hits = [p for p in ds.products if _passes(p, checks, "")]
    shown = shown_contexts(ds, query)
    visible = _within(_named(ds, query.retailer), shown) if query.retailer else shown
    if query.sort is ProductSort.NAME:
        hits.sort(key=lambda p: (fold(p.name), p.id))
    elif query.sort in GAP_SORTS and pair is not None:
        hits = _by_gap(ds, hits, pair, ascending=query.sort is ProductSort.GAP_ASC)
    else:
        priced = [(p, _low_price(ds, p, visible)) for p in hits]
        sign = -1 if query.sort is ProductSort.PRICE_DESC else 1
        # Ties break on id ascending in both directions; unpriced products come last.
        with_price = sorted(
            ((p, v) for p, v in priced if v is not None), key=lambda pv: (sign * pv[1], pv[0].id)
        )
        hits = [p for p, _ in with_price] + sorted(
            (p for p, v in priced if v is None), key=lambda p: p.id
        )
    return hits


def product_page(
    ds: DatasetV3, generation: str, query: ProductQuery, images: EvidenceHosts = NO_HOSTS
) -> Metric[ProductPage]:
    _unknown_values(ds, query)
    pair = _search_pair(ds, query)
    checks = _predicates(ds, query)
    shown = shown_contexts(ds, query)
    digest = filters_digest(query)
    offset = 0 if query.cursor is None else decode_cursor(query.cursor, generation, digest)
    hits = _ordered(ds, query, pair, checks)
    page = hits[offset : offset + query.limit]
    end = offset + len(page)
    return Metric[ProductPage](
        status=Status.OK,
        data=ProductPage(
            total=len(hits),
            next_cursor=encode_cursor(generation, end, digest) if end < len(hits) else None,
            items=tuple(card(ds, p, pair, shown, images) for p in page),
            facets=_facets(ds, checks, shown),
        ),
        as_of=ds.meta.dates[-1],
    )


def product_cards(
    ds: DatasetV3, query: ProductFilters, images: EvidenceHosts = NO_HOSTS
) -> Metric[tuple[ProductCard, ...]]:
    """Every card ``/v1/products`` would page through for these filters, in the same order."""
    _unknown_values(ds, query)
    pair = _search_pair(ds, query)
    hits = _ordered(ds, query, pair, _predicates(ds, query))
    shown = shown_contexts(ds, query)
    return Metric[tuple[ProductCard, ...]](
        status=Status.OK,
        data=tuple(card(ds, p, pair, shown, images) for p in hits),
        as_of=ds.meta.dates[-1],
    )


# ---------------------------------------------------------------- detail and history


class Evidence(ContractModel):
    captured_at: datetime
    #: Only an https URL on the retailer's allowlisted hosts; anything else is null.
    url: SourceText | None


def evidence_url(url: object, retailer: str, hosts: EvidenceHosts) -> str | None:
    """``url`` if it is https, on one of ``retailer``'s hosts, with no credentials or odd port.

    The FE checks only the scheme, so this is where a dataset URL pointing anywhere else (a
    phishing host, another retailer's host, ``user@host`` tricks) is stopped: it becomes null.
    """
    if url is None:
        return None
    text = str(url)
    if not text.isascii() or not text.isprintable() or " " in text or "\\" in text:
        return None  # browsers read a backslash as "/", so its host could differ from ours
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        return None
    if port not in (None, 443) or parts.hostname is None:
        return None
    return text if parts.hostname in hosts.get(retailer, frozenset()) else None


class AdminEvidence(Evidence):
    """Admins only (design §4): where the observation came from."""

    source: SourceText
    run_id: str | None


class OfferView(ContractModel):
    #: The retailer the offer is at; ``context`` says where it was observed.
    retailer: str
    price: MoneyValue | None
    #: API 1.7.1: ``invalid_low`` when the published price was 0.01 or less and is withheld
    #: (``price`` is then null and the offer is in no figure); null otherwise.
    price_flag: PriceFlag | None = None
    regular: MoneyValue | None
    promo_pct: Annotated[str, Field(pattern=r"^-?\d+(\.\d+)?$")] | None
    rating: Rating | None
    size: Size | None
    #: The retailer's published number of shades. Valid on its own: ``capabilities.shades =
    #: false`` means no shade *list* is served, not that the product has no shades.
    shade_count: int | None
    sku: SourceText | None
    early: bool
    availability: AvailabilityState | None
    evidence: Evidence
    context: str
    channel: Channel
    #: The context's location id; null for a context with no location (online).
    location: str | None
    size_label: SourceText | None
    size_system: SourceText | None


class AdminOfferView(OfferView):
    evidence: AdminEvidence


class ProductDetail(ContractModel):
    card: ProductCard
    offers: tuple[OfferView, ...]
    #: Every context pair of the offers (base = the lower id), latest date.
    pairs: tuple[PairGap, ...]


class AdminProductDetail(ContractModel):
    card: ProductCard
    offers: tuple[AdminOfferView, ...]
    pairs: tuple[PairGap, ...]


def pair_gaps(ds: DatasetV3, product: ProductV3) -> tuple[PairGap, ...]:
    return tuple(pair_gap(ds, product, a, b) for a, b in combinations(sorted(product.offers), 2))


def _promo(price: MoneyValue | None, regular: MoneyValue | None) -> str | None:
    if price is None or regular is None or price.decimal() >= regular.decimal():
        return None
    return str(depth(price, regular).quantize(Decimal("0.1")))


def _offer_fields(ds: DatasetV3, ctx: Context, offer: OfferV3) -> dict[str, Any]:
    i = len(ds.meta.dates) - 1
    price, regular = price_on(offer, i), regular_on(offer, i)
    states = offer.series.availability
    return {
        "retailer": ctx.retailer,
        "price": price,
        "regular": regular,
        "promo_pct": _promo(price, regular),
        "rating": offer.rating,
        "size": measure(offer.size),
        "shade_count": offer.shade_count,
        "sku": offer.sku,
        "early": offer.early,
        "availability": None if states is None else states[i],
        "context": ctx.id,
        "channel": ctx.channel,
        "location": None if ctx.location is None else ctx.location.id,
        "size_label": size_label(offer.size)[0],
        "size_system": size_label(offer.size)[1],
    }


def _offers(ds: DatasetV3, product: ProductV3) -> list[tuple[Context, OfferV3]]:
    """The product's offers by context id, each with its context."""
    return [(context(ds, c), o) for c, o in sorted(product.offers.items())]


def find(ds: DatasetV3, product_id: str) -> ProductV3:
    for p in ds.products:
        if p.id == product_id:
            return p
    raise ProductNotFoundError(product_id)


def product_detail(
    ds: DatasetV3, product: ProductV3, hosts: EvidenceHosts, images: EvidenceHosts = NO_HOSTS
) -> Metric[ProductDetail]:
    offers = tuple(
        OfferView(
            **_offer_fields(ds, c, o),
            evidence=Evidence(
                captured_at=o.evidence.captured_at, url=evidence_url(o.url, c.retailer, hosts)
            ),
        )
        for c, o in _offers(ds, product)
    )
    return Metric[ProductDetail](
        status=Status.OK,
        data=ProductDetail(
            card=card(ds, product, images=images), offers=offers, pairs=pair_gaps(ds, product)
        ),
        as_of=ds.meta.dates[-1],
    )


def admin_product_detail(
    ds: DatasetV3, product: ProductV3, hosts: EvidenceHosts, images: EvidenceHosts = NO_HOSTS
) -> Metric[AdminProductDetail]:
    offers = tuple(
        AdminOfferView(
            **_offer_fields(ds, c, o),
            evidence=AdminEvidence(
                captured_at=o.evidence.captured_at,
                url=evidence_url(o.url, c.retailer, hosts),
                source=o.evidence.source,
                run_id=o.evidence.run_id,
            ),
        )
        for c, o in _offers(ds, product)
    )
    return Metric[AdminProductDetail](
        status=Status.OK,
        data=AdminProductDetail(
            card=card(ds, product, images=images), offers=offers, pairs=pair_gaps(ds, product)
        ),
        as_of=ds.meta.dates[-1],
    )


class HistoryPoint(ContractModel):
    date: date
    price: MoneyValue | None
    regular: MoneyValue | None
    availability: AvailabilityState | None


class History(ContractModel):
    id: str
    series: dict[str, tuple[HistoryPoint, ...]]


class HistoryQuery(ContractModel):
    market: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    scope: ShortText | None = None
    start: date | None = Field(default=None, alias="from")
    end: date | None = Field(default=None, alias="to")


def history(ds: DatasetV3, product: ProductV3, query: HistoryQuery) -> Metric[History]:
    """Per-context series (a sole context's key is its retailer's id); a missing day is null,
    never carried forward."""
    if query.start and query.end and query.start > query.end:
        msg = "from is after to"
        raise InvalidQueryError(msg)
    days = [
        (i, d)
        for i, d in enumerate(ds.meta.dates)
        if (query.start is None or d >= query.start) and (query.end is None or d <= query.end)
    ]
    if len(days) > 1 and not ds.meta.capabilities.history:
        days = days[-1:]
        status, reason = Status.NOT_ENOUGH_DATA, Reason.CAPABILITY_OFF
    else:
        status, reason = Status.OK, None
    series = {
        r: tuple(
            HistoryPoint(
                date=d,
                price=price_on(o, i),
                regular=regular_on(o, i),
                availability=None if o.series.availability is None else o.series.availability[i],
            )
            for i, d in days
        )
        for r, o in sorted(product.offers.items())
    }
    return Metric[History](
        status=status,
        data=History(id=product.id, series=series),
        reason=reason,
        as_of=days[-1][1] if days else ds.meta.dates[-1],
    )


def product_filter(query: ProductFilters) -> ProductFilter:
    return ProductFilter(brands=query.brand, categories=query.category)
