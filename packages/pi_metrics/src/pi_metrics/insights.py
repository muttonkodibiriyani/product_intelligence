"""Decision insights: brand price policy, price gaps by size, and size-ladder value.

Four aggregates for the Insights page, each over rules the other metrics already own:

* **Brand price policy** groups ``compare``'s counted pairs (exact, approved or locked, same
  size, one currency) by brand. A brand with at least ``MIN_COHORT`` counted pairs is labelled
  by where at least ``POLICY_SHARE`` % of them fall: ``other_cheaper``, ``base_cheaper`` or
  ``parity`` (equal price); otherwise ``mixed``. The label describes the observed prices, not
  anyone's intent.
* **Gap by size** groups the same counted pairs by the base offer's published measure
  (``90 ml``). A pair without a measure is not grouped; sizes below ``MIN_COHORT`` are counted
  in ``suppressed``.
* **Size ladders** stay inside one context: consecutive measures of one product family, where
  the larger size should cost less per unit. The family is the retailer's own
  ``content.family`` when published (``basis = family``); otherwise products with the same
  brand, name, top-level category and unit (``basis = name``), a weaker grouping the response
  says it used. A family with two offers at one measure is skipped as ambiguous. A step whose
  larger size costs more than ``HELD_OUT_PCT`` % more per unit is held out as two products
  sharing a name, and counted. Each step says whether either size is on sale (its regular
  price on the date above its price), which can explain an exception.
* **Brand stock-outs** count, per context and brand, the offers observed out of stock on the
  date against the offers in an observed stock state (in, low or out of stock). Counts only,
  never a share: retailers are crawled partially, so a share of the catalogue would overstate
  what was seen. A day without an observation is never out of stock. A brand whose every
  observed offer is out of stock is one the source reports unavailable (often not sold online
  in the market), not a sell-out: it is counted apart (``unavailable_brands``,
  ``unavailable_listings``, the ``unavailable`` rows), and ``out_of_stock`` and ``brands`` cover
  the other, partly-out brands only, so the two never overlap. A partly-out brand is listed
  when at least ``MIN_COHORT`` of its offers are out of stock, the most first. Per shop the
  response also carries ``listed`` (offers collected, the catalogue count) and ``with_stock``.
* **Value picks** stay inside one context and one top-level category (each shop's own).
  ``UNRANKED_CATEGORIES`` (``other``, a catch-all of brushes, nails and hair) are never ranked
  and only counted (``unranked``). Offers that are not like-for-like leave the category's cohort
  and are counted in its ``excluded``: tools in any category (``TOOL_TERMS``; "brush on" and
  "brush tip" name an applicator and stay); body care outside ``body`` and ``fragrance``
  (``BODY_PRODUCT_TERMS``: body wash, sugar scrub, epsom, bath, ...); and in ``fragrance`` a name
  with a body-care term (``BODY_CARE_TERMS``: lotion, shower, after shave, ...) and no fragrance
  term (``FRAGRANCE_TERMS``: parfum, eau de, mist, ...), so a fragrance-and-lotion set stays. The
  category's median price is over the rest (nearest rank, the lower middle, so an observed
  price), rated or not, in the market currency; under ``MIN_COHORT`` offers there is no median
  and the category is counted in ``suppressed``. A pick is rated at least ``VALUE_RATING_PCT`` %
  of its scale by at least ``VALUE_MIN_RATINGS`` reviewers, not out of stock on the date
  (unknown stock is allowed), and at or below its basis's median: ``fragrance`` is compared per
  unit (``PER_UNIT``: price per ml or g against the median per unit of the category's offers in
  the same unit, a unit with ``MIN_COHORT`` of them; an offer without such a size is not a pick);
  every other category by shelf price (``SHELF``), where names with ``SMALL_SIZE_TERMS`` (mini,
  travel, ...) are never picks. Picks rank by rating share shrunk toward the category's mean
  share of its rated offers, ``(share * n + mean * PRIOR_RATINGS) / (n + PRIOR_RATINGS)``, so a
  few perfect ratings do not outrank thousands of good ones; then most ratings, cheapest on the
  basis, id. One brand and (folded) name is one pick, the cheapest on the basis, and a brand has
  at most ``PICKS_PER_BRAND`` picks per category. Ratings are the retailer's own; the shop is
  never compared with another.

No cross-retailer number comes from an unreviewed match: when no pair is counted the pricing
parts say ``matches_unreviewed`` (or why else) and carry no rows.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import NamedTuple

from pi_core import AvailabilityState
from pi_dataset import ContractModel, DatasetV3, MoneyValue, OfferV3, ProductV3, Rating
from pi_dataset.models import FieldStatus, RetailerStatus
from pi_metrics import view
from pi_metrics.compare import GroupBy, PairRow, compare, pair_block
from pi_metrics.model import (
    EVERY_PROFILE,
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Cheaper,
    Cohort,
    Excluded,
    Metric,
    Pct,
    ProductFilter,
    RatingValue,
    Reason,
    Status,
)
from pi_metrics.pricing import UNIT_PLACES

#: Share of a brand's counted pairs (in %) that must agree for a policy label.
POLICY_SHARE = Decimal(80)
#: A larger size this much dearer per unit (in %) is held out as a different product.
HELD_OUT_PCT = Decimal(50)
#: The most ladder exceptions listed per context; ``not_cheaper`` counts them all.
EXCEPTIONS_LISTED = 12
#: Brands listed per context in the stock-out counts.
BRANDS_LISTED = 12
#: A value pick has at least this many ratings ...
VALUE_MIN_RATINGS = 20
#: ... averaging at least this share (in %) of the rating scale (4.5 of 5).
VALUE_RATING_PCT = Decimal(90)
#: Categories listed per context, the most priced offers first; picks listed per category.
CATEGORIES_LISTED = 8
PICKS_LISTED = 5
#: Top-level categories never ranked: a catch-all of unlike things (brushes, nails, hair).
UNRANKED_CATEGORIES = frozenset({"other"})
#: Ranked per unit (``ValueBasis.PER_UNIT``); its body-care listings leave the value cohort.
FRAGRANCE = "fragrance"
#: Body care's own category: ``BODY_PRODUCT_TERMS`` names stay in it (and in ``FRAGRANCE``).
BODY = "body"
#: A ``fragrance`` offer named with one of these and none of ``FRAGRANCE_TERMS`` is body care.
BODY_CARE_TERMS = re.compile(
    r"\b(?:lotion|body wash|shower|3-in-1|shampoo|conditioner|scrub|body butter|soap|bath"
    r"|deodorant|hand cream|body cream|body oil|after ?shave|shave cream|shave gel|shaving)\b",
    re.IGNORECASE,
)
FRAGRANCE_TERMS = re.compile(
    r"\b(?:parfum|eau de|cologne|perfume|mist|extrait|fragrance)\b", re.IGNORECASE
)
#: Outside ``BODY`` and ``FRAGRANCE``, an offer named with one of these is body care.
BODY_PRODUCT_TERMS = re.compile(
    r"\b(?:body (?:wash|scrub|lotion|butter|oil|cream)|sugar scrub|epsom|bath)\b", re.IGNORECASE
)
#: In every category an offer named with one of these is a tool, not a product. ``brush on`` and
#: ``brush tip`` describe a product's applicator and stay in.
TOOL_TERMS = re.compile(
    r"\b(?:brush(?:es)?(?![ -](?:on|tip)\b)|sponges?|(?:facial|face|jade|quartz) roller|gua sha"
    r"|tweezers?|mitt|applicator|curler|device|powder puff|sharpener)\b",
    re.IGNORECASE,
)
#: On the shelf-price basis an offer named with one of these is a small size, never a pick.
SMALL_SIZE_TERMS = re.compile(r"\b(?:mini|travel|discovery|sample|deluxe)\b", re.IGNORECASE)
#: Units a per-unit price is taken in (folded); other measures have no per-unit price.
VALUE_UNITS = frozenset({"ml", "g"})
#: Ratings of prior weight when shrinking a pick's rating share toward its category's mean.
PRIOR_RATINGS = 50
#: Picks listed or counted per brand in one category.
PICKS_PER_BRAND = 2
PROFILES = EVERY_PROFILE


class Policy(StrEnum):
    OTHER_CHEAPER = "other_cheaper"
    BASE_CHEAPER = "base_cheaper"
    PARITY = "parity"
    MIXED = "mixed"


class BrandPolicy(ContractModel):
    brand: str
    n: int
    policy: Policy
    median_gap_pct: Pct
    base_cheaper: int
    other_cheaper: int
    equal: int


class SizeGap(ContractModel):
    value: str
    unit: str
    n: int
    median_gap_pct: Pct
    base_cheaper: int
    other_cheaper: int
    equal: int


class PairInsights(ContractModel):
    base: str
    other: str
    #: Counted pairs (exact, approved or locked, same size, priced on the date).
    n: int
    #: Pairs with a proposed (unreviewed) edge: shown so the gap to a counted answer is visible.
    unreviewed: int
    status: Status
    reason: Reason | None
    brands: tuple[BrandPolicy, ...]
    sizes: tuple[SizeGap, ...]
    #: Brands or sizes with 1..MIN_COHORT-1 counted pairs, withheld.
    suppressed_brands: int
    suppressed_sizes: int


class LadderBasis(StrEnum):
    FAMILY = "family"
    NAME = "name"


class LadderStep(ContractModel):
    family: str
    brand: str
    name: str
    smaller_id: str
    larger_id: str
    unit: str
    smaller_value: str
    larger_value: str
    smaller_price: MoneyValue
    larger_price: MoneyValue
    #: Per-unit price change from the smaller to the larger size; >= 0 means no saving.
    unit_change_pct: Pct
    basis: LadderBasis
    #: The size is on sale: its regular price on the date is above its price.
    smaller_on_sale: bool = False
    larger_on_sale: bool = False


class Ladder(ContractModel):
    retailer: str
    steps: int
    not_cheaper: int
    held_out: int
    median_saving_pct: Pct | None
    reason: Reason | None
    #: The ``not_cheaper`` steps, largest per-unit rise first, at most ``EXCEPTIONS_LISTED``.
    exceptions: tuple[LadderStep, ...]


class BrandStock(ContractModel):
    brand: str
    #: Offers in an observed stock state (in, low or out of stock) on the date.
    observed: int
    out_of_stock: int


class Stockouts(ContractModel):
    retailer: str
    reason: Reason | None
    #: Brands with some offers in stock and at least ``MIN_COHORT`` out of stock, most out first.
    brands: tuple[BrandStock, ...]
    #: Partly-out brands that qualify; only the first ``BRANDS_LISTED`` are listed.
    qualifying: int
    #: Partly-out brands with some, but fewer than ``MIN_COHORT``, offers out of stock.
    suppressed: int
    #: Offers collected for the context, early recon samples aside: the catalogue's count.
    listed: int = 0
    #: Of ``listed``: offers in an observed stock state (in, low or out of stock).
    with_stock: int = 0
    #: Of ``with_stock``: offers out of stock in partly-out brands. Never overlaps
    #: ``unavailable_listings``.
    out_of_stock: int = 0
    #: Brands whose every offer in an observed stock state is out of stock: the source reports
    #: them unavailable (often not sold online in the market), which is not a sell-out.
    unavailable_brands: int = 0
    #: Offers in ``unavailable_brands``. Never overlaps ``out_of_stock``.
    unavailable_listings: int = 0
    #: ``unavailable_brands`` with at least ``MIN_COHORT`` offers, the most first.
    unavailable: tuple[BrandStock, ...] = ()


class ValueBasis(StrEnum):
    #: Shelf price against the category's median price.
    SHELF = "shelf"
    #: Price per ml or g against the category's per-unit median in the same unit.
    PER_UNIT = "per_unit"


class UnitMedian(ContractModel):
    unit: str
    #: Median price per unit (nearest rank, lower middle), ``UNIT_PLACES`` decimals, in the
    #: category's currency.
    median: str
    #: Priced offers measured in ``unit``: the median's cohort.
    n: int


class ValuePick(ContractModel):
    id: str
    brand: str
    name: str
    price: MoneyValue
    rating: RatingValue
    scale: str
    rating_count: int
    #: The card image on an allowed evidence host (set by pi_api), else null.
    image: str | None = None
    #: The published measure, when the offer has one in ``VALUE_UNITS``.
    size_value: str | None = None
    size_unit: str | None = None
    #: ``price`` per ``size_unit``, ``UNIT_PLACES`` decimals, when the size is known.
    unit_price: str | None = None


class ValueCategory(ContractModel):
    category: str
    #: Priced offers in the category and market currency, the median's cohort.
    priced: int
    median: MoneyValue
    #: Of ``priced``: offers with at least ``valueMinRatings`` ratings.
    rated: int
    #: Of ``rated``: rated at least ``valueRatingPct`` % of the scale, in stock or of unknown
    #: stock, at or below the basis's median, one per brand and name, at most
    #: ``PICKS_PER_BRAND`` per brand.
    picks: int
    items: tuple[ValuePick, ...]
    #: Priced offers taken out of the cohort as not like-for-like: body care filed under
    #: ``fragrance`` or another category, or tools. Not in ``priced``.
    excluded: int = 0
    basis: ValueBasis = ValueBasis.SHELF
    #: ``PER_UNIT`` only: the median per unit with at least ``minCohort`` measured offers.
    unit_medians: tuple[UnitMedian, ...] = ()


class ValuePicks(ContractModel):
    retailer: str
    reason: Reason | None
    #: Categories with a median, the most priced offers first (at most ``CATEGORIES_LISTED``).
    categories: tuple[ValueCategory, ...]
    #: Categories with a median, listed or not.
    qualifying: int
    #: Categories with fewer than ``minCohort`` priced offers: no median, no picks.
    suppressed: int
    #: Priced offers in ``UNRANKED_CATEGORIES``, never ranked.
    unranked: int = 0


_Priced = tuple[MoneyValue, ProductV3, OfferV3]


class Insights(ContractModel):
    pricing: PairInsights
    ladders: tuple[Ladder, ...]
    stockouts: tuple[Stockouts, ...] = ()
    value: tuple[ValuePicks, ...] = ()
    policy_share_pct: Pct = POLICY_SHARE
    held_out_pct: Pct = HELD_OUT_PCT
    value_min_ratings: int = VALUE_MIN_RATINGS
    value_rating_pct: Pct = VALUE_RATING_PCT


def _split(rows: list[PairRow]) -> tuple[int, int, int]:
    cheaper = [r.gap.cheaper for r in rows if r.gap is not None]
    return cheaper.count(Cheaper.BASE), cheaper.count(Cheaper.OTHER), cheaper.count(Cheaper.EQUAL)


def _median(rows: list[PairRow]) -> Decimal:
    return statistics.median(sorted(r.gap.pct for r in rows if r.gap is not None))


def policy(base_cheaper: int, other_cheaper: int, equal: int) -> Policy:
    """The label at least ``POLICY_SHARE`` % of the pairs agree on, else ``mixed``."""
    n = base_cheaper + other_cheaper + equal
    for label, count in (
        (Policy.OTHER_CHEAPER, other_cheaper),
        (Policy.BASE_CHEAPER, base_cheaper),
        (Policy.PARITY, equal),
    ):
        if n and Decimal(count) * 100 >= POLICY_SHARE * n:
            return label
    return Policy.MIXED


def _brands(counted: list[PairRow]) -> tuple[tuple[BrandPolicy, ...], int]:
    by: defaultdict[str, list[PairRow]] = defaultdict(list)
    for row in counted:
        by[row.brand].append(row)
    out, suppressed = [], 0
    for brand, rows in by.items():
        if len(rows) < MIN_COHORT:
            suppressed += 1
            continue
        b, o, e = _split(rows)
        out.append(
            BrandPolicy(
                brand=brand,
                n=len(rows),
                policy=policy(b, o, e),
                median_gap_pct=_median(rows),
                base_cheaper=b,
                other_cheaper=o,
                equal=e,
            )
        )
    out.sort(key=lambda r: (r.median_gap_pct, -r.n, r.brand))
    return tuple(out), suppressed


def _sizes(ds: DatasetV3, counted: list[PairRow], base: str) -> tuple[tuple[SizeGap, ...], int]:
    by: defaultdict[tuple[str, Decimal], list[PairRow]] = defaultdict(list)
    for row in counted:
        size = view.product_v3(ds, row.id).offers[base].size
        if size is not None and size.value is not None and size.unit is not None:
            by[(size.unit.casefold(), Decimal(size.value).normalize())].append(row)
    out, suppressed = [], 0
    for (unit, value), rows in sorted(by.items()):
        if len(rows) < MIN_COHORT:
            suppressed += 1
            continue
        b, o, e = _split(rows)
        out.append(
            SizeGap(
                value=f"{value:f}",
                unit=unit,
                n=len(rows),
                median_gap_pct=_median(rows),
                base_cheaper=b,
                other_cheaper=o,
                equal=e,
            )
        )
    return tuple(out), suppressed


def _pricing(ds: DatasetV3, base: str, other: str, on: date | None) -> PairInsights:
    result = compare(ds, base, other, ProductFilter(), on=on, group_by=GroupBy.BRAND)
    rows = result.data.rows
    # A blocked side or a currency mismatch counts no pair at all, as compare's own groups.
    blocked = pair_block(ds, base, other) is not None
    counted = [] if blocked else [r for r in rows if r.counted and r.gap is not None]
    brands, quiet_brands = _brands(counted)
    sizes, quiet_sizes = _sizes(ds, counted, base)
    return PairInsights(
        base=base,
        other=other,
        n=len(counted),
        unreviewed=sum(1 for r in rows if r.excluded_reason is Excluded.MATCH_UNREVIEWED),
        status=result.status,
        reason=result.reason,
        brands=brands if result.status is Status.OK else (),
        sizes=sizes if result.status is Status.OK else (),
        suppressed_brands=quiet_brands,
        suppressed_sizes=quiet_sizes,
    )


type _Rung = tuple[Decimal, ProductV3, MoneyValue]


def _families(
    ds: DatasetV3, context: str, i: int
) -> dict[tuple[str, ...], tuple[LadderBasis, str, list[_Rung]]]:
    families: dict[tuple[str, ...], tuple[LadderBasis, str, list[_Rung]]] = {}
    for product in ds.products:
        offer = view.collected(product, context)
        if offer is None or offer.early or offer.size is None:
            continue
        price = view.price_on(offer, i)
        value, unit = offer.size.value, offer.size.unit
        if price is None or value is None or unit is None or Decimal(value) <= 0:
            continue
        family = offer.content.family if offer.content is not None else None
        if family is not None:
            key: tuple[str, ...] = ("family", family, unit.casefold())
            basis = LadderBasis.FAMILY
        else:
            names = (product.brand, product.name, product.category[0], unit)
            key = ("name", *(view.fold(x) for x in names))
            basis = LadderBasis.NAME
        families.setdefault(key, (basis, family or product.name, []))[2].append(
            (Decimal(value), product, price)
        )
    return families


def _ladder(ds: DatasetV3, context: str, i: int) -> Ladder:
    status = view.status(ds, context)
    if status is RetailerStatus.BLOCKED:
        return Ladder(
            retailer=context,
            steps=0,
            not_cheaper=0,
            held_out=0,
            median_saving_pct=None,
            reason=Reason.RETAILER_BLOCKED,
            exceptions=(),
        )
    steps: list[LadderStep] = []
    held_out = 0
    for basis, label, rungs in _families(ds, context, i).values():
        values = [v for v, _, _ in rungs]
        if len(values) < 2 or len(set(values)) != len(values):
            continue
        rungs.sort(key=lambda r: r[0])
        for (sv, sp, sm), (lv, lp, lm) in pairwise(rungs):
            change = (lm.decimal() / lv) / (sm.decimal() / sv) * 100 - 100
            if change > HELD_OUT_PCT:
                held_out += 1
                continue
            offer = sp.offers[context]
            steps.append(
                LadderStep(
                    family=label,
                    brand=sp.brand,
                    name=sp.name,
                    smaller_id=sp.id,
                    larger_id=lp.id,
                    unit=offer.size.unit if offer.size and offer.size.unit else "",
                    smaller_value=f"{sv.normalize():f}",
                    larger_value=f"{lv.normalize():f}",
                    smaller_price=sm,
                    larger_price=lm,
                    unit_change_pct=change,
                    basis=basis,
                    smaller_on_sale=_on_sale(offer, sm, i),
                    larger_on_sale=_on_sale(lp.offers[context], lm, i),
                )
            )
    bad = sorted((s for s in steps if s.unit_change_pct >= 0), key=_steepest)
    enough = len(steps) >= MIN_COHORT
    return Ladder(
        retailer=context,
        steps=len(steps),
        not_cheaper=len(bad),
        held_out=held_out,
        median_saving_pct=-statistics.median(sorted(s.unit_change_pct for s in steps))
        if enough
        else None,
        reason=None if enough else Reason.COHORT_TOO_SMALL,
        exceptions=tuple(bad[:EXCEPTIONS_LISTED]),
    )


def _on_sale(offer: OfferV3, price: MoneyValue, i: int) -> bool:
    regular = view.regular_on(offer, i)
    return (
        regular is not None
        and regular.currency == price.currency
        and regular.decimal() > price.decimal()
    )


def _steepest(step: LadderStep) -> tuple[Decimal, str]:
    return (-step.unit_change_pct, step.larger_id)


def _brand_stock(
    ds: DatasetV3, context: str, i: int
) -> tuple[int, defaultdict[str, int], defaultdict[str, int]]:
    """Offers collected, and per brand those in an observed stock state and those out of stock."""
    listed = 0
    observed: defaultdict[str, int] = defaultdict(int)
    out: defaultdict[str, int] = defaultdict(int)
    for product in ds.products:
        offer = view.collected(product, context)
        if offer is None:
            continue
        listed += 1
        states = offer.series.availability
        state = None if states is None else states[i]
        if state is None or not state.is_known:
            continue
        observed[product.brand] += 1
        out[product.brand] += state is AvailabilityState.OUT_OF_STOCK
    return listed, observed, out


def _gone(observed: dict[str, int], out: dict[str, int]) -> frozenset[str]:
    return frozenset(b for b, n in out.items() if n == observed[b])


def unavailable_brands(ds: DatasetV3, context: str, i: int) -> frozenset[str]:
    """Brands whose every offer in an observed stock state at ``context`` on date ``i`` is out of
    stock: the source reports them unavailable (see the module's brand stock-outs)."""
    _, observed, out = _brand_stock(ds, context, i)
    return _gone(observed, out)


def _stockouts(ds: DatasetV3, context: str, i: int) -> Stockouts:
    reason = None
    if view.status(ds, context) is RetailerStatus.BLOCKED:
        reason = Reason.RETAILER_BLOCKED
    elif not ds.meta.capabilities.stock:
        reason = Reason.CAPABILITY_OFF
    if reason is not None:
        return Stockouts(retailer=context, reason=reason, brands=(), qualifying=0, suppressed=0)
    listed, observed, out = _brand_stock(ds, context, i)
    gone = _gone(observed, out)
    rows = [BrandStock(brand=b, observed=observed[b], out_of_stock=n) for b, n in out.items()]
    rows.sort(key=lambda r: (-r.out_of_stock, r.brand))
    partly = [r for r in rows if r.brand not in gone and r.out_of_stock >= MIN_COHORT]
    return Stockouts(
        retailer=context,
        reason=None,
        brands=tuple(partly[:BRANDS_LISTED]),
        qualifying=len(partly),
        suppressed=sum(1 for b, n in out.items() if b not in gone and 0 < n < MIN_COHORT),
        listed=listed,
        with_stock=sum(observed.values()),
        out_of_stock=sum(n for b, n in out.items() if b not in gone),
        unavailable_brands=len(gone),
        unavailable_listings=sum(observed[b] for b in gone),
        unavailable=tuple(r for r in rows if r.brand in gone and r.out_of_stock >= MIN_COHORT)[
            :BRANDS_LISTED
        ],
    )


def _value_off(ds: DatasetV3, context: str) -> Reason | None:
    if view.status(ds, context) is RetailerStatus.BLOCKED:
        return Reason.RETAILER_BLOCKED
    if not ds.meta.capabilities.ratings:
        return Reason.CAPABILITY_OFF
    if ds.meta.fields.get("rating", FieldStatus.NOT_COLLECTED) is FieldStatus.NOT_COLLECTED:
        return Reason.FIELD_NOT_COLLECTED
    return None


def _well_rated(rating: Rating | None) -> bool:
    return (
        rating is not None
        and rating.count >= VALUE_MIN_RATINGS
        and Decimal(rating.average) * 100 >= VALUE_RATING_PCT * Decimal(rating.scale)
    )


def body_care_in_fragrance(product: ProductV3) -> bool:
    """Is ``product`` body care filed under ``fragrance``: a body-care term, no fragrance term?"""
    return (
        product.category[0] == FRAGRANCE
        and BODY_CARE_TERMS.search(product.name) is not None
        and FRAGRANCE_TERMS.search(product.name) is None
    )


def not_like_for_like(product: ProductV3) -> bool:
    """Is ``product`` left out of its category's value cohort: body care filed under
    ``fragrance`` or under a category other than ``body``, or a tool?"""
    category = product.category[0]
    return (
        body_care_in_fragrance(product)
        or (
            category not in {BODY, FRAGRANCE}
            and BODY_PRODUCT_TERMS.search(product.name) is not None
        )
        or TOOL_TERMS.search(product.name) is not None
    )


def _measure(offer: OfferV3) -> tuple[Decimal, str] | None:
    """The offer's measure in a ``VALUE_UNITS`` unit, else None."""
    size = offer.size
    if size is None or size.value is None or size.unit is None:
        return None
    value, unit = Decimal(size.value), view.fold(size.unit)
    return (value, unit) if value > 0 and unit in VALUE_UNITS else None


def _lower_middle(values: list[Decimal]) -> Decimal:
    return sorted(values)[(len(values) - 1) // 2]


def _unit_medians(offers: list[_Priced]) -> dict[str, tuple[Decimal, int]]:
    """Per unit, the median price per unit and its cohort size, for units with ``MIN_COHORT``."""
    by_unit: defaultdict[str, list[Decimal]] = defaultdict(list)
    for price, _, offer in offers:
        measure = _measure(offer)
        if measure is not None:
            by_unit[measure[1]].append(price.decimal() / measure[0])
    return {u: (_lower_middle(v), len(v)) for u, v in by_unit.items() if len(v) >= MIN_COHORT}


def _share(rating: Rating) -> Decimal:
    return Decimal(rating.average) / Decimal(rating.scale)


def _in_stock_or_unknown(offer: OfferV3, i: int) -> bool:
    states = offer.series.availability
    return states is None or states[i] is not AvailabilityState.OUT_OF_STOCK


def _unit_text(value: Decimal) -> str:
    return str(value.quantize(Decimal(1).scaleb(-UNIT_PLACES)))


class _Candidate(NamedTuple):
    score: Decimal
    #: The basis's price: per unit on ``PER_UNIT``, else the shelf price.
    cost: Decimal
    pick: ValuePick


def _candidate(
    entry: _Priced, mean: Decimal, units: dict[str, tuple[Decimal, int]] | None, median: Decimal
) -> _Candidate | None:
    """``entry`` as a pick on its basis (per unit when ``units`` is given), else None."""
    price, product, offer = entry
    rating = offer.rating
    if rating is None or not _well_rated(rating):
        return None
    measure = _measure(offer)
    unit_price = None if measure is None else price.decimal() / measure[0]
    if units is not None:
        if measure is None or unit_price is None or measure[1] not in units:
            return None
        if unit_price > units[measure[1]][0]:
            return None
        cost = unit_price
    else:
        if SMALL_SIZE_TERMS.search(product.name) or price.decimal() > median:
            return None
        cost = price.decimal()
    score = (_share(rating) * rating.count + mean * PRIOR_RATINGS) / (rating.count + PRIOR_RATINGS)
    pick = ValuePick(
        id=product.id,
        brand=product.brand,
        name=product.name,
        price=price,
        rating=Decimal(rating.average),
        scale=rating.scale,
        rating_count=rating.count,
        size_value=None if measure is None else f"{measure[0].normalize():f}",
        size_unit=None if measure is None else measure[1],
        unit_price=None if unit_price is None else _unit_text(unit_price),
    )
    return _Candidate(score, cost, pick)


def _picks(candidates: list[_Candidate]) -> list[ValuePick]:
    """One pick per brand and name (the cheapest on the basis), at most ``PICKS_PER_BRAND`` per
    brand, by shrunk rating share, then most ratings, cheapest, id."""
    cheapest: dict[tuple[str, str], _Candidate] = {}
    for c in candidates:
        key = (view.fold(c.pick.brand), view.fold(c.pick.name))
        kept = cheapest.get(key)
        if kept is None or (c.cost, c.pick.id) < (kept.cost, kept.pick.id):
            cheapest[key] = c
    ranked = sorted(
        cheapest.values(), key=lambda c: (-c.score, -c.pick.rating_count, c.cost, c.pick.id)
    )
    per_brand: defaultdict[str, int] = defaultdict(int)
    picks = []
    for c in ranked:
        per_brand[view.fold(c.pick.brand)] += 1
        if per_brand[view.fold(c.pick.brand)] <= PICKS_PER_BRAND:
            picks.append(c.pick)
    return picks


def _category(category: str, offers: list[_Priced], excluded: int, i: int) -> ValueCategory:
    median = sorted((p for p, _, _ in offers), key=MoneyValue.decimal)[(len(offers) - 1) // 2]
    rated = [
        e for e in offers if e[2].rating is not None and e[2].rating.count >= VALUE_MIN_RATINGS
    ]
    mean = (
        sum((_share(o.rating) for _, _, o in rated if o.rating is not None), Decimal(0))
        / len(rated)
        if rated
        else Decimal(0)
    )
    units = _unit_medians(offers) if category == FRAGRANCE else None
    candidates = [
        c
        for e in rated
        if _in_stock_or_unknown(e[2], i)
        and (c := _candidate(e, mean, units, median.decimal())) is not None
    ]
    picks = _picks(candidates)
    return ValueCategory(
        category=category,
        priced=len(offers),
        median=median,
        rated=len(rated),
        picks=len(picks),
        items=tuple(picks[:PICKS_LISTED]),
        excluded=excluded,
        basis=ValueBasis.SHELF if units is None else ValueBasis.PER_UNIT,
        unit_medians=()
        if units is None
        else tuple(
            UnitMedian(unit=u, median=_unit_text(m), n=n) for u, (m, n) in sorted(units.items())
        ),
    )


def _value(ds: DatasetV3, context: str, i: int) -> ValuePicks:
    reason = _value_off(ds, context)
    if reason is not None:
        return ValuePicks(
            retailer=context, reason=reason, categories=(), qualifying=0, suppressed=0
        )
    currency = view.market_currency(ds, view.context(ds, context).retailer)
    priced: defaultdict[str, list[_Priced]] = defaultdict(list)
    excluded: defaultdict[str, int] = defaultdict(int)
    unranked = 0
    for product in ds.products:
        offer = view.collected(product, context)
        price = None if offer is None else view.price_on(offer, i)
        if offer is None or price is None or price.currency != currency:
            continue
        category = product.category[0]
        if category in UNRANKED_CATEGORIES:
            unranked += 1
        elif not_like_for_like(product):
            excluded[category] += 1
        else:
            priced[category].append((price, product, offer))
    rows = [
        _category(category, offers, excluded[category], i)
        for category, offers in priced.items()
        if len(offers) >= MIN_COHORT
    ]
    rows.sort(key=lambda r: (-r.priced, r.category))
    return ValuePicks(
        retailer=context,
        reason=None if rows else Reason.COHORT_TOO_SMALL,
        categories=tuple(rows[:CATEGORIES_LISTED]),
        qualifying=len(rows),
        suppressed=sum(1 for o in priced.values() if len(o) < MIN_COHORT),
        unranked=unranked,
    )


def insights(
    dataset: view.AnyDataset, base: str, other: str, *, on: date | None = None
) -> Metric[Insights]:
    """The pricing insights for context pair ``base``/``other`` and every context's ladder."""
    ds = view.as_v3(dataset)
    if base == other:
        msg = "the two retailers must differ"
        raise view.UnknownInput(msg)
    view.context(ds, base)
    view.context(ds, other)
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    if not view.applies(ds, PROFILES) or not ds.meta.capabilities.sizes:
        reason = Reason.NOT_APPLICABLE if not view.applies(ds, PROFILES) else Reason.CAPABILITY_OFF
        empty = PairInsights(
            base=base,
            other=other,
            n=0,
            unreviewed=0,
            status=Status.NOT_ENOUGH_DATA,
            reason=reason,
            brands=(),
            sizes=(),
            suppressed_brands=0,
            suppressed_sizes=0,
        )
        return Metric[Insights](
            status=Status.NOT_ENOUGH_DATA,
            data=Insights(pricing=empty, ladders=()),
            reason=reason,
            as_of=as_of,
        )
    pricing = _pricing(ds, base, other, on)
    ladders = tuple(_ladder(ds, c.id, i) for c in ds.meta.contexts)
    stockouts = tuple(_stockouts(ds, c.id, i) for c in ds.meta.contexts)
    value = tuple(_value(ds, c.id, i) for c in ds.meta.contexts)
    caveats = tuple(
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": c.id})
        for c in ds.meta.contexts
        if view.status(ds, c.id) is RetailerStatus.PARTIAL
    )
    ok = (
        pricing.status is Status.OK
        or any(ladder.reason is None for ladder in ladders)
        or any(v.reason is None for v in value)
    )
    return Metric[Insights](
        status=Status.OK if ok else Status.NOT_ENOUGH_DATA,
        data=Insights(pricing=pricing, ladders=ladders, stockouts=stockouts, value=value),
        reason=None if ok else pricing.reason,
        cohort=Cohort(description="counted exact pairs, approved or locked", n=pricing.n),
        caveats=caveats,
        as_of=as_of,
    )
