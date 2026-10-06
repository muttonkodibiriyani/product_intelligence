"""Findings: twelve ranked, decision-framed answers for the top of the Insights page.

Each finding is recomputed from the served view on every snapshot; nothing in it is written by
hand. The request names a ``focus`` context (the shop the findings speak to) and a ``rival``;
every other context of the view is a ``third`` shop. A finding carries its numbers as typed
``params`` (the client words them per locale), a mini ``chart``, up to ``EXAMPLES_LISTED`` product
``examples``, and the evidence behind it: ``n`` of ``of``, the ``match`` and ``basis`` it rests
on, and its ``threshold``. Below its threshold a finding is ``not_enough_data`` with a reason and
no params, and it is ranked after every shown finding.

Every cross-shop price comes from compare's counted pairs (exact, approved or locked, same size,
one currency). With no counted pair between the focus and the rival, the match-based findings
(``brand_depth_gaps``, ``brand_price_policy``, ``size_level_gaps``, ``real_discounts``) say
``matches_unreviewed`` (or ``no_match``), never a number from a proposed match. The rest stay
inside one shop, or compare brand presence, never prices.

House rules: stock-outs are counts and never rank shops; a brand whose every observed offer is
out of stock is one the source reports unavailable, counted apart (``unavailable*`` params, never
a headline); a shop whose was-prices are unverified, or that states none, shows no discounts (a
``discounts_not_shown`` chip, not zero); money is ``MoneyValue`` in the market currency, and price
bands (``PRICE_BANDS``) are in its major unit. Ratings are each shop's own, on its own scale, and
shops are never compared on them. A price the read-time floor withheld (a ``view.WithheldOffer``)
is ``pricing_anomalies``' evidence and has no price anywhere else.
"""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from functools import cache
from itertools import chain, combinations, zip_longest

from pi_core import AvailabilityState
from pi_dataset import ContractModel, DatasetV3, MoneyValue, OfferV3, ProductV3
from pi_dataset.models import FieldStatus, RetailerStatus
from pi_metrics import view
from pi_metrics.compare import PairRow, compare, pair_block, same_item
from pi_metrics.insights import (
    FRAGRANCE,
    POLICY_SHARE,
    VALUE_RATING_PCT,
    BrandPolicy,
    LadderStep,
    Policy,
    SizeGap,
    brand_policies,
    brand_stockouts,
    size_gaps,
    size_ladder,
)
from pi_metrics.model import (
    BEAUTY,
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
    fixed,
)

#: An all-capitals brand word this short is an acronym and keeps its capitals (YSL, NYX).
ACRONYM_LETTERS = 4
#: Product examples per finding.
EXAMPLES_LISTED = 4
#: Examples from each side when a finding contrasts two groups (cheap and dear, say).
EXAMPLES_PER_SIDE = EXAMPLES_LISTED // 2
#: Chart rows per finding.
CHART_ROWS = 8
#: brand_white_space: an absent brand counts with at least this many listings at the rival, and
#: this many absent brands are listed, the most-reviewed first.
WHITE_SPACE_MIN_LISTINGS = 5
ABSENT_LISTED = 12
#: brand_depth_gaps: a rival product page with at least this many displayed reviews is a hero.
HERO_MIN_REVIEWS = 500
#: A shop's rated cohort needs this many reviews per product, this many products per category,
#: and this many products in all; below it the shop has too few ratings.
RATED_MIN_REVIEWS = 50
RATED_CATEGORY_MIN = 20
RATED_SHOP_MIN = 100
#: A laggard is rated below this share (in %) of its scale (4.0 of 5).
LAGGARD_RATING_PCT = Decimal(80)
#: promo_strategy: a brand is listed with at least this many listings with a stated regular
#: price, is large with at least ``PROMO_LARGE_BRAND``, and depends on promotion when at least
#: ``PROMO_DEPENDENT_PCT`` % of them are marked down.
PROMO_MIN_LISTINGS = 10
PROMO_LARGE_BRAND = 50
PROMO_DEPENDENT_PCT = Decimal(50)
#: promo_strategy's breadth: regular price under ``PRICE_BANDS[0]`` against at or over this.
PROMO_HIGH_BAND = Decimal(400)
#: real_discounts: a stated regular price within this many % of the other shop's selling price
#: makes the markdown real; at least ``REAL_DISCOUNT_MIN`` matched markdowns are needed.
REAL_DISCOUNT_TOLERANCE_PCT = Decimal(3)
REAL_DISCOUNT_MIN = 5
#: positioning: a shop's category needs this many priced listings.
POSITION_MIN = 30
POSITION_CATEGORIES = ("lips", "eyes", "foundation", "skincare", "fragrance")
POSITION_CHARTED = ("lips", "foundation", "fragrance")
#: Band edges in the market currency's major unit: <50, 50-99, 100-199, 200-399, 400-799, 800+.
PRICE_BANDS = (Decimal(50), Decimal(100), Decimal(200), Decimal(400), Decimal(800))
#: fragrance_ladder ladders bottles in this unit only, never these names (sets, minis, refills).
ML = "ml"
NOT_A_BOTTLE = re.compile(
    r"\b(?:refill|refills|set|kit|travel|mini|coffret|gift|discovery|duo|trio|bundle)\b|\sx\s|\+",
    re.IGNORECASE,
)
FLANKER = re.compile(r"\b(?:intense|elixir|absolu|absolute|extreme|le parfum)\b", re.IGNORECASE)
_EDP = re.compile(r"\beau de parfum\b|\bedp\b", re.IGNORECASE)
_EDT = re.compile(r"\beau de toilette\b|\bedt\b", re.IGNORECASE)
_LINE_NOISE = re.compile(
    r"\b(?:eau de parfum|eau de toilette|eau de cologne|edp|edt|edc|parfum|spray|refillable|"
    r"vaporisateur|vapo|natural|intense|elixir|absolu|absolute|extreme|le|for (?:him|her|men|"
    r"women)|pour (?:homme|femme))\b|\b\d+(?: \d+)?\s*(?:ml|g|oz)\b"
)
#: Words brand_depth_gaps' name screen ignores.
NAME_STOP = frozenset(
    [
        "eau",
        "de",
        "parfum",
        "toilette",
        "edp",
        "edt",
        "spray",
        "the",
        "for",
        "her",
        "him",
        "men",
        "women",
        "pour",
        "homme",
        "femme",
        "travel",
        "size",
        "mini",
        "set",
        "and",
        "with",
        "ml",
    ]
)
#: Beauty only: the findings read beauty categories, sizes in ml and fragrance names.
PROFILES = frozenset({BEAUTY})
_MEDIAN = Decimal("0.5")
_STOCKED = frozenset({AvailabilityState.IN_STOCK, AvailabilityState.LOW_STOCK})

type BrandKey = Callable[[str], str]
_pct_text = fixed(1)


class FindingKey(StrEnum):
    BRAND_WHITE_SPACE = "brand_white_space"
    BRAND_DEPTH_GAPS = "brand_depth_gaps"
    BRAND_PRICE_POLICY = "brand_price_policy"
    SIZE_LEVEL_GAPS = "size_level_gaps"
    STOCK = "stock"
    PROMO_STRATEGY = "promo_strategy"
    REAL_DISCOUNTS = "real_discounts"
    FRAGRANCE_LADDER = "fragrance_ladder"
    SIZE_TRAPS = "size_traps"
    POSITIONING = "positioning"
    PRICE_VS_RATING = "price_vs_rating"
    PRICING_ANOMALIES = "pricing_anomalies"


#: The rank order of shown findings; withheld findings follow in the same order.
ORDER = tuple(FindingKey)


class Area(StrEnum):
    ASSORTMENT = "assortment"
    PRICE = "price"
    AVAILABILITY = "availability"
    PROMOTIONS = "promotions"
    FRAGRANCE = "fragrance"
    VALUE = "value"
    CUSTOMER_VOICE = "customer_voice"
    TRUST = "trust"


class MatchBasis(StrEnum):
    #: Compare's counted pairs: exact, approved or locked, same size, one currency.
    COUNTED_PAIRS = "counted_pairs"
    #: Products of one shop compared with each other.
    WITHIN_SHOP = "within_shop"
    #: Brand names (after clean-up), no product matching.
    BRAND_LEVEL = "brand_level"
    #: One shop's own listings, nothing matched.
    SINGLE_SHOP = "single_shop"


class Basis(StrEnum):
    SELLING_PRICE = "selling_price"
    PER_UNIT = "per_unit"
    STATED_REGULAR = "stated_regular"
    STOCK_FLAG = "stock_flag"
    RATING = "rating"
    BRAND_PRESENCE = "brand_presence"


class ParamKind(StrEnum):
    COUNT = "count"
    #: A percentage at 1 dp.
    PCT = "pct"
    MONEY = "money"
    #: A rank correlation, -1 to 1, 2 dp.
    RATIO = "ratio"
    #: Data as published (a brand, a product name, a size such as ``90 ml``), never translated.
    TEXT = "text"
    #: A context id; the client names the shop.
    RETAILER = "retailer"
    #: A category code; the client names it.
    CATEGORY = "category"
    #: ``TEXT`` items the client joins per locale.
    LIST = "list"
    #: Not measured: the client shows its missing-data mark, never a zero.
    MISSING = "missing"


class Param(ContractModel):
    kind: ParamKind
    value: str = ""
    currency: str | None = None
    items: tuple[str, ...] = ()


class ChartKind(StrEnum):
    BARS = "bars"
    #: Signed % bars around zero; negative is the focus shop cheaper.
    DIVERGING = "diverging"
    #: ``parts`` per row, one per ``columns`` entry, summing to ``value``.
    STACKED = "stacked"
    #: ``parts`` are the row's observations, ascending; ``value`` is their median.
    STRIPS = "strips"
    #: Rows are ``code`` labels; ``parts`` per row, one per ``columns`` entry.
    MATRIX = "matrix"


class ChartUnit(StrEnum):
    PCT = "pct"
    COUNT = "count"


class ChartRow(ContractModel):
    #: A brand, size or product as published, or (``code``) a code the client names.
    label: str
    code: bool = False
    retailer: str | None = None
    value: Pct
    n: int | None = None
    #: The whole ``value`` is a part of ("78 of 176"), for counts.
    of: int | None = None
    parts: tuple[Pct, ...] = ()


class Chart(ContractModel):
    kind: ChartKind
    unit: ChartUnit
    #: ``STACKED`` and ``MATRIX`` column labels (codes the client names, or price bands).
    columns: tuple[str, ...] = ()
    rows: tuple[ChartRow, ...]


class Example(ContractModel):
    id: str
    retailer: str
    brand: str
    name: str
    #: ``None`` when unpriced on the date, or withheld by the price floor (``price_withheld``).
    price: MoneyValue | None
    price_withheld: bool = False
    #: The stated regular price when above ``price`` and the shop's markdowns are shown.
    regular: MoneyValue | None = None
    #: What the example is set against: the same item at another shop, or another product of
    #: the same shop (an EDT, a smaller size).
    versus: str | None = None
    versus_id: str | None = None
    versus_name: str | None = None
    versus_price: MoneyValue | None = None
    #: (price - versus price) / versus price x 100 (per unit for a size step).
    gap_pct: Pct | None = None
    rating: RatingValue | None = None
    scale: str | None = None
    rating_count: int | None = None
    stock: AvailabilityState | None = None
    #: The card image on an allowed evidence host (set by pi_api), else null.
    image: str | None = None


class ChipCode(StrEnum):
    #: The shop's rated cohort is under ``RATED_SHOP_MIN``.
    TOO_FEW_RATINGS = "too_few_ratings"
    #: The shop has fewer than ``MIN_COHORT`` size steps or fragrance pairs.
    TOO_FEW_PAIRS = "too_few_pairs"
    #: The shop publishes no stock state.
    STOCK_NOT_COLLECTED = "stock_not_collected"
    #: The shop's was-prices are unverified or not stated: no discounts shown, not zero.
    DISCOUNTS_NOT_SHOWN = "discounts_not_shown"


class Chip(ContractModel):
    code: ChipCode
    retailer: str


class Finding(ContractModel):
    key: FindingKey
    rank: int
    area: Area
    status: Status
    reason: Reason | None
    #: The finding's cohort, in its own unit (pairs, brands, listings, products, steps) ...
    n: int
    #: ... out of this many eligible, when a whole is defined (the coverage), else null.
    of: int | None
    match: MatchBasis
    basis: Basis
    #: The finding's minimum, in the unit of ``n`` (see ``THRESHOLD``).
    threshold: int
    params: dict[str, Param]
    #: The headline's key number: ``params[FIGURE[key]]``; null when withheld.
    figure: Param | None
    chart: Chart | None
    examples: tuple[Example, ...]
    chips: tuple[Chip, ...] = ()


class Findings(ContractModel):
    focus: str
    rival: str
    thirds: tuple[str, ...]
    #: Counted pairs between the focus and the rival: 0 withholds the match-based findings.
    counted_pairs: int
    findings: tuple[Finding, ...]


# ---------------------------------------------------------------- params


def _count(n: int) -> Param:
    return Param(kind=ParamKind.COUNT, value=str(n))


def _pct(value: Decimal) -> Param:
    return Param(kind=ParamKind.PCT, value=_pct_text(value))


def _ratio(value: Decimal) -> Param:
    return Param(kind=ParamKind.RATIO, value=str(value))


def _money(m: MoneyValue) -> Param:
    return Param(kind=ParamKind.MONEY, value=m.amount, currency=m.currency)


def _text(s: str) -> Param:
    return Param(kind=ParamKind.TEXT, value=s)


def _list(items: Iterable[str]) -> Param:
    return Param(kind=ParamKind.LIST, items=tuple(items))


def _shop(cid: str) -> Param:
    return Param(kind=ParamKind.RETAILER, value=cid)


def _category(code: str) -> Param:
    return Param(kind=ParamKind.CATEGORY, value=code)


MISSING = Param(kind=ParamKind.MISSING)


def _or_missing[T](value: T | None, as_param: Callable[[T], Param]) -> Param:
    return MISSING if value is None else as_param(value)


# ---------------------------------------------------------------- arithmetic


def share(part: int, whole: int) -> Decimal:
    """``part`` of ``whole`` in %."""
    return Decimal(part) * 100 / whole


def nearest_rank(values: Iterable[Decimal], p: Decimal) -> Decimal:
    """The lower nearest-rank quantile: always an observed value (p=0.5 is the lower median)."""
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * p)]


def spearman(xs: list[Decimal], ys: list[Decimal]) -> Decimal | None:
    """Spearman's rank correlation, average ranks for ties, at 2 dp; ``None`` with fewer than
    two values or no variance on either side."""
    if len(xs) < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    rho = Decimal(repr(sxy / math.sqrt(sxx * syy))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return max(Decimal(-1), min(Decimal(1), rho))


def _ranks(values: list[Decimal]) -> list[float]:
    order = sorted(range(len(values)), key=lambda k: values[k])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for k in order[start : end + 1]:
            ranks[k] = (start + end) / 2
        start = end + 1
    return ranks


def band_labels() -> tuple[str, ...]:
    """``<50``, ``50-99``, ..., ``800+`` from ``PRICE_BANDS``."""
    edges = [f"{e:f}" for e in PRICE_BANDS]
    inner = [f"{a}-{b - 1:f}" for a, b in zip(edges, PRICE_BANDS[1:], strict=False)]
    return (f"<{edges[0]}", *inner, f"{edges[-1]}+")


def band_of(amount: Decimal) -> int:
    """0 (under the first edge) to ``len(PRICE_BANDS)`` (at or over the last)."""
    return sum(amount >= e for e in PRICE_BANDS)


def depth(price: MoneyValue, regular: MoneyValue) -> Decimal:
    """(regular - price) / regular x 100: the stated discount."""
    return (regular.decimal() - price.decimal()) / regular.decimal() * 100


# ---------------------------------------------------------------- names


def fold_name(text: str) -> str:
    """Accents stripped, casefolded, punctuation as spaces: for name screens only."""
    decomposed = unicodedata.normalize("NFKD", view.fold(text))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", plain).split())


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(
        t for t in fold_name(name).split() if t not in NAME_STOP and not t.isdigit() and len(t) > 1
    )


def concentration(name: str) -> str | None:
    if _EDP.search(name):
        return "edp"
    if _EDT.search(name):
        return "edt"
    return None


def fragrance_line(name: str) -> str:
    """The name without concentration, flanker, size and spray words: one line's key."""
    return " ".join(_LINE_NOISE.sub(" ", fold_name(name)).split())


# ---------------------------------------------------------------- listings


@dataclass(frozen=True)
class _Listing:
    product: ProductV3
    context: str
    offer: OfferV3


@dataclass(frozen=True)
class _Priced(_Listing):
    price: MoneyValue


def _priced(ds: DatasetV3, context: str, i: int) -> Iterator[_Priced]:
    """The context's collected offers priced on date ``i`` in the market currency."""
    currency = view.market_currency(ds, view.context(ds, context).retailer)
    for product in ds.products:
        offer = view.collected(product, context)
        price = None if offer is None else view.price_on(offer, i)
        if offer is not None and price is not None and price.currency == currency:
            yield _Priced(product, context, offer, price)


def _seen(ds: DatasetV3, context: str, i: int) -> Iterator[_Listing]:
    """The context's collected offers observed on date ``i`` (a withheld price included)."""
    for product in ds.products:
        offer = view.collected(product, context)
        if offer is not None and view.seen(offer, i):
            yield _Listing(product, context, offer)


def _listing(ds: DatasetV3, product_id: str, context: str) -> _Listing:
    product = view.product_v3(ds, product_id)
    return _Listing(product, context, product.offers[context])


def _withheld(offer: OfferV3, i: int) -> bool:
    return isinstance(offer, view.WithheldOffer) and i in offer.withheld


def _stocked(x: _Listing, i: int) -> bool:
    states = x.offer.series.availability
    return states is not None and states[i] in _STOCKED


def _out_of_stock(x: _Listing, i: int) -> bool:
    states = x.offer.series.availability
    return states is not None and states[i] is AvailabilityState.OUT_OF_STOCK


def _reviews(x: _Listing) -> int:
    rating = x.offer.rating
    return 0 if rating is None else rating.count


def _rating(x: _Listing) -> Decimal:
    rating = x.offer.rating
    return Decimal(0) if rating is None else Decimal(rating.average)


def rating_pct(x: _Listing) -> Decimal:
    """The rating as a share (in %) of its own scale; 0 when unrated."""
    rating = x.offer.rating
    if rating is None:
        return Decimal(0)
    return Decimal(rating.average) * 100 / Decimal(rating.scale)


def _page(x: _Listing) -> str:
    """The product page: sizes of one page share its reviews."""
    url = x.offer.url
    return x.product.id if url is None else str(url)


def _page_reviews(listings: Iterable[_Listing]) -> int:
    """Displayed reviews, once per product page."""
    pages: dict[str, int] = {}
    for x in listings:
        pages[_page(x)] = max(pages.get(_page(x), 0), _reviews(x))
    return sum(pages.values())


def _most_reviewed(x: _Listing) -> tuple[int, str]:
    return (-_reviews(x), x.product.id)


def example(
    listing: _Listing,
    i: int,
    *,
    versus: _Listing | None = None,
    versus_price: MoneyValue | None = None,
    gap_pct: Decimal | None = None,
) -> Example:
    """A product example on date ``i``; ``versus`` is what it is set against (its price is
    ``versus_price`` when given, else its price on the date)."""
    o = listing.offer
    states = o.series.availability
    rating = o.rating
    if versus is not None and versus_price is None:
        versus_price = view.price_on(versus.offer, i)
    price, regular = view.price_on(o, i), view.regular_on(o, i)
    if price is None or regular is None or regular.decimal() <= price.decimal():
        regular = None
    return Example(
        id=listing.product.id,
        retailer=listing.context,
        brand=listing.product.brand,
        name=listing.product.name,
        price=price,
        price_withheld=_withheld(o, i),
        regular=regular,
        versus=None if versus is None else versus.context,
        versus_id=None if versus is None else versus.product.id,
        versus_name=None if versus is None else versus.product.name,
        versus_price=versus_price,
        gap_pct=gap_pct,
        rating=None if rating is None else Decimal(rating.average),
        scale=None if rating is None else rating.scale,
        rating_count=None if rating is None else rating.count,
        stock=None if states is None else states[i],
    )


def distinct(examples: Iterable[Example]) -> tuple[Example, ...]:
    """The first example per shop and product name (sizes and shades of one product once)."""
    seen: set[tuple[str, str, str]] = set()
    out = []
    for e in examples:
        if (name := (e.retailer, e.brand, e.name)) not in seen:
            seen.add(name)
            out.append(e)
    return tuple(out)


# ---------------------------------------------------------------- finding shells

_AREA = {
    FindingKey.BRAND_WHITE_SPACE: Area.ASSORTMENT,
    FindingKey.BRAND_DEPTH_GAPS: Area.ASSORTMENT,
    FindingKey.BRAND_PRICE_POLICY: Area.PRICE,
    FindingKey.SIZE_LEVEL_GAPS: Area.PRICE,
    FindingKey.STOCK: Area.AVAILABILITY,
    FindingKey.PROMO_STRATEGY: Area.PROMOTIONS,
    FindingKey.REAL_DISCOUNTS: Area.PROMOTIONS,
    FindingKey.FRAGRANCE_LADDER: Area.FRAGRANCE,
    FindingKey.SIZE_TRAPS: Area.VALUE,
    FindingKey.POSITIONING: Area.PRICE,
    FindingKey.PRICE_VS_RATING: Area.CUSTOMER_VOICE,
    FindingKey.PRICING_ANOMALIES: Area.TRUST,
}
_MATCH = {
    FindingKey.BRAND_WHITE_SPACE: MatchBasis.BRAND_LEVEL,
    FindingKey.BRAND_DEPTH_GAPS: MatchBasis.COUNTED_PAIRS,
    FindingKey.BRAND_PRICE_POLICY: MatchBasis.COUNTED_PAIRS,
    FindingKey.SIZE_LEVEL_GAPS: MatchBasis.COUNTED_PAIRS,
    FindingKey.STOCK: MatchBasis.BRAND_LEVEL,
    FindingKey.PROMO_STRATEGY: MatchBasis.SINGLE_SHOP,
    FindingKey.REAL_DISCOUNTS: MatchBasis.COUNTED_PAIRS,
    FindingKey.FRAGRANCE_LADDER: MatchBasis.WITHIN_SHOP,
    FindingKey.SIZE_TRAPS: MatchBasis.WITHIN_SHOP,
    FindingKey.POSITIONING: MatchBasis.SINGLE_SHOP,
    FindingKey.PRICE_VS_RATING: MatchBasis.SINGLE_SHOP,
    FindingKey.PRICING_ANOMALIES: MatchBasis.SINGLE_SHOP,
}
_BASIS = {
    FindingKey.BRAND_WHITE_SPACE: Basis.BRAND_PRESENCE,
    FindingKey.BRAND_DEPTH_GAPS: Basis.BRAND_PRESENCE,
    FindingKey.BRAND_PRICE_POLICY: Basis.SELLING_PRICE,
    FindingKey.SIZE_LEVEL_GAPS: Basis.SELLING_PRICE,
    FindingKey.STOCK: Basis.STOCK_FLAG,
    FindingKey.PROMO_STRATEGY: Basis.STATED_REGULAR,
    FindingKey.REAL_DISCOUNTS: Basis.STATED_REGULAR,
    FindingKey.FRAGRANCE_LADDER: Basis.PER_UNIT,
    FindingKey.SIZE_TRAPS: Basis.PER_UNIT,
    FindingKey.POSITIONING: Basis.SELLING_PRICE,
    FindingKey.PRICE_VS_RATING: Basis.RATING,
    FindingKey.PRICING_ANOMALIES: Basis.SELLING_PRICE,
}
#: Each finding's minimum, in the unit of its ``n``.
THRESHOLD = {
    FindingKey.BRAND_WHITE_SPACE: MIN_COHORT,  # absent brands, WHITE_SPACE_MIN_LISTINGS each
    FindingKey.BRAND_DEPTH_GAPS: MIN_COHORT,  # absent heroes
    FindingKey.BRAND_PRICE_POLICY: MIN_COHORT,  # counted pairs in a listed brand
    FindingKey.SIZE_LEVEL_GAPS: MIN_COHORT,  # counted pairs in a listed size, two sizes
    FindingKey.STOCK: MIN_COHORT,  # out-of-stock listings in a listed brand
    FindingKey.PROMO_STRATEGY: PROMO_MIN_LISTINGS,  # listings with a regular price, per brand
    FindingKey.REAL_DISCOUNTS: REAL_DISCOUNT_MIN,  # markdowns on counted pairs
    FindingKey.FRAGRANCE_LADDER: MIN_COHORT,  # pairs per shop and upgrade
    FindingKey.SIZE_TRAPS: MIN_COHORT,  # size steps at the focus shop
    FindingKey.POSITIONING: POSITION_MIN,  # priced listings per shop and category
    FindingKey.PRICE_VS_RATING: RATED_SHOP_MIN,  # products with RATED_MIN_REVIEWS reviews
    FindingKey.PRICING_ANOMALIES: 1,  # withheld prices
}
#: The param each finding's headline leads with: its one key number.
FIGURE = {
    FindingKey.BRAND_WHITE_SPACE: "absent",
    FindingKey.BRAND_DEPTH_GAPS: "absent",
    FindingKey.BRAND_PRICE_POLICY: "focusCheaper",
    FindingKey.SIZE_LEVEL_GAPS: "heroMedianPct",
    FindingKey.STOCK: "brand1Out",
    FindingKey.PROMO_STRATEGY: "modePct",
    FindingKey.REAL_DISCOUNTS: "real",
    FindingKey.FRAGRANCE_LADDER: "inversions",
    FindingKey.SIZE_TRAPS: "focusNotCheaper",
    FindingKey.POSITIONING: "lipsUnderFocus",
    FindingKey.PRICE_VS_RATING: "fragranceRho",
    FindingKey.PRICING_ANOMALIES: "focusCount",
}


def _withhold(key: FindingKey, reason: Reason, *, chips: Iterable[Chip] = ()) -> Finding:
    return Finding(
        key=key,
        rank=0,
        area=_AREA[key],
        status=Status.NOT_ENOUGH_DATA,
        reason=reason,
        n=0,
        of=None,
        match=_MATCH[key],
        basis=_BASIS[key],
        threshold=THRESHOLD[key],
        params={},
        figure=None,
        chart=None,
        examples=(),
        chips=tuple(chips),
    )


def _shown(  # noqa: PLR0913 -- one finding's parts, all keyword-only
    key: FindingKey,
    *,
    n: int,
    of: int | None,
    params: dict[str, Param],
    chart: Chart,
    examples: Iterable[Example],
    chips: Iterable[Chip] = (),
) -> Finding:
    return Finding(
        key=key,
        rank=0,
        area=_AREA[key],
        status=Status.OK,
        reason=None,
        n=n,
        of=of,
        match=_MATCH[key],
        basis=_BASIS[key],
        threshold=THRESHOLD[key],
        params=params,
        figure=params[FIGURE[key]],
        chart=chart,
        examples=distinct(examples)[:EXAMPLES_LISTED],
        chips=tuple(chips),
    )


# ---------------------------------------------------------------- shared cohorts


@dataclass(frozen=True)
class _Pairs:
    """Compare's counted rows with ``base`` and ``other``: gap = (other - base) / base."""

    counted: list[PairRow]
    #: Rows offered by both contexts, counted or not.
    both: int
    reason: Reason | None


def _pairs(ds: DatasetV3, base: str, other: str, on: date | None) -> _Pairs:
    rows = compare(ds, base, other, ProductFilter(), on=on).data.rows
    blocked = pair_block(ds, base, other)
    counted = [] if blocked else [r for r in rows if r.counted and r.gap is not None]
    both = sum(1 for r in rows if r.excluded_reason is not Excluded.NOT_OFFERED)
    reason = blocked
    if not counted and reason is None:
        unreviewed = any(r.excluded_reason is Excluded.MATCH_UNREVIEWED for r in rows)
        reason = Reason.MATCHES_UNREVIEWED if unreviewed else Reason.NO_MATCH
    return _Pairs(counted=counted, both=both, reason=reason)


def _pair_example(ds: DatasetV3, row: PairRow, base: str, other: str, i: int) -> Example:
    """The ``other`` side of a counted row, set against ``base``."""
    return example(
        _listing(ds, row.id, other),
        i,
        versus=_listing(ds, row.id, base),
        versus_price=row.base_price,
        gap_pct=None if row.gap is None else row.gap.pct,
    )


def _by_gap(row: PairRow) -> tuple[Decimal, str]:
    return (Decimal(0) if row.gap is None else row.gap.pct, row.id)


@dataclass(frozen=True)
class _Rated:
    """A shop's rated cohort: priced offers with ``RATED_MIN_REVIEWS`` reviews, by category
    (categories under ``RATED_CATEGORY_MIN`` left out), with each category's price quartile
    edges (nearest rank, lower)."""

    by_category: dict[str, list[_Priced]]
    edges: dict[str, tuple[Decimal, ...]]

    @property
    def n(self) -> int:
        return sum(len(v) for v in self.by_category.values())

    def quartile(self, x: _Priced) -> int:
        """0 (cheapest) to 3 (dearest) within the listing's category."""
        return sum(x.price.decimal() > e for e in self.edges[x.product.category[0]])

    def items(self) -> Iterator[_Priced]:
        for category in sorted(self.by_category):
            yield from self.by_category[category]


def _ratings_off(ds: DatasetV3) -> Reason | None:
    if not ds.meta.capabilities.ratings:
        return Reason.CAPABILITY_OFF
    if ds.meta.fields.get("rating", FieldStatus.NOT_COLLECTED) is FieldStatus.NOT_COLLECTED:
        return Reason.FIELD_NOT_COLLECTED
    return None


def _rated(ds: DatasetV3, context: str, i: int) -> _Rated:
    by: defaultdict[str, list[_Priced]] = defaultdict(list)
    if _ratings_off(ds) is None:
        for x in _priced(ds, context, i):
            if _reviews(x) >= RATED_MIN_REVIEWS:
                by[x.product.category[0]].append(x)
    kept = {c: v for c, v in by.items() if len(v) >= RATED_CATEGORY_MIN}
    edges = {
        c: tuple(nearest_rank((x.price.decimal() for x in v), Decimal(q) / 4) for q in (1, 2, 3))
        for c, v in kept.items()
    }
    return _Rated(by_category=kept, edges=edges)


def _champion(rated: _Rated, x: _Priced) -> bool:
    """In its category's cheapest quartile, rated at least ``VALUE_RATING_PCT`` % of its scale."""
    return rated.quartile(x) == 0 and rating_pct(x) >= VALUE_RATING_PCT


def _laggard(rated: _Rated, x: _Priced) -> bool:
    """In its category's dearest quartile, rated below ``LAGGARD_RATING_PCT`` % of its scale."""
    return rated.quartile(x) == 3 and rating_pct(x) < LAGGARD_RATING_PCT


def _brands(
    ds: DatasetV3, contexts: Iterable[str], i: int, brand_key: BrandKey
) -> tuple[dict[str, set[str]], dict[str, dict[str, list[_Listing]]]]:
    """Per context, the exact brand names seen on date ``i``, and its listings by brand key."""
    names: dict[str, set[str]] = {}
    keys: dict[str, dict[str, list[_Listing]]] = {}
    for c in contexts:
        by: defaultdict[str, list[_Listing]] = defaultdict(list)
        for x in _seen(ds, c, i):
            by[brand_key(x.product.brand)].append(x)
        names[c] = {x.product.brand for xs in by.values() for x in xs}
        keys[c] = dict(by)
    return names, keys


def _exact(keys: dict[str, dict[str, list[_Listing]]], a: str, b: str, key: str) -> bool:
    """Both contexts list the brand key under one identical brand name."""
    return bool({x.product.brand for x in keys[a][key]} & {x.product.brand for x in keys[b][key]})


def _title_token(token: str) -> str:
    """One word of an all-capitals brand: up to ``ACRONYM_LETTERS`` letters is an acronym and
    stays as written (YSL, NYX, E.L.F.), a longer word is title-cased (COSMETICS)."""
    if sum(c.isalpha() for c in token) <= ACRONYM_LETTERS:
        return token
    return token.title()


def display_brand(spellings: Iterable[str]) -> str:
    """How one brand is written in findings, from every spelling the shops use: the most frequent
    spelling that is not all capitals, as found (then the first alphabetically); if every
    spelling is in capitals, the most frequent one with its long words title-cased."""
    counts = Counter(spellings)
    mixed = [s for s in counts if s.upper() != s]
    if mixed:
        return min(mixed, key=lambda s: (-counts[s], s))
    shown = min(counts, key=lambda s: (-counts[s], s))
    return " ".join(_title_token(t) for t in shown.split(" "))


@dataclass(frozen=True)
class BrandNames:
    """Brand keys for brand-level comparisons, and each key's ``display_brand`` spelling over
    every product in the dataset."""

    key: BrandKey
    spelling: dict[str, str]

    def show(self, brand: str) -> str:
        return self.spelling.get(self.key(brand), brand)

    def of(self, listings: list[_Listing]) -> str:
        """The display name of the brand key ``listings`` share."""
        return self.show(listings[0].product.brand)


def brand_names(ds: DatasetV3, brand_key: BrandKey) -> BrandNames:
    by: defaultdict[str, list[str]] = defaultdict(list)
    for p in ds.products:
        by[brand_key(p.brand)].append(p.brand)
    return BrandNames(key=brand_key, spelling={k: display_brand(v) for k, v in by.items()})


def _currency(ds: DatasetV3, context: str) -> str:
    return view.market_currency(ds, view.context(ds, context).retailer)


# ---------------------------------------------------------------- 1 brand white space


def brand_white_space(  # noqa: PLR0913 -- the request's parts, then the injected brand key
    ds: DatasetV3,
    focus: str,
    rival: str,
    thirds: tuple[str, ...],
    i: int,
    *,
    names: BrandNames,
) -> Finding:
    """Brands the rival sells and the focus shop does not, the most-reviewed first; the one with
    the most cheap, highly rated products at the rival; and what the first third shop adds."""
    key = FindingKey.BRAND_WHITE_SPACE
    spellings, keys = _brands(ds, (focus, rival, *thirds), i, names.key)
    absent = sorted(
        (
            (k, xs)
            for k, xs in keys[rival].items()
            if k not in keys[focus] and len(xs) >= WHITE_SPACE_MIN_LISTINGS
        ),
        key=lambda kv: (-_page_reviews(kv[1]), -len(kv[1]), kv[0]),
    )
    if len(absent) < MIN_COHORT:
        return _withhold(key, Reason.COHORT_TOO_SMALL)
    listed = absent[:ABSENT_LISTED]
    shared = keys[focus].keys() & keys[rival].keys()
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "rival": _shop(rival),
        "focusBrands": _count(len(spellings[focus])),
        "rivalBrands": _count(len(spellings[rival])),
        "shared": _count(len(shared)),
        "sharedExact": _count(sum(1 for k in shared if _exact(keys, focus, rival, k))),
        "absent": _count(len(absent)),
        "absentListed": _count(len(listed)),
        "absentNames": _list(names.of(xs) for _, xs in listed[:6]),
        "absentReviews": _count(sum(_page_reviews(xs) for _, xs in listed)),
        "minListings": _count(WHITE_SPACE_MIN_LISTINGS),
    }
    rated = _rated(ds, rival, i)
    champions: defaultdict[str, list[_Priced]] = defaultdict(list)
    for x in rated.items():
        if _champion(rated, x):
            champions[names.key(x.product.brand)].append(x)
    leads = sorted(
        ((k, xs) for k, xs in absent if champions[k]),
        key=lambda kv: (-len(champions[kv[0]]), kv[0]),
    )
    lead_keys = ("lead", "leadListings", "leadChampions", "leadFrom", "leadTo")
    params |= dict.fromkeys(lead_keys, MISSING)
    if leads:
        k, xs = leads[0]
        prices = sorted((x.price for x in champions[k]), key=MoneyValue.decimal)
        params |= {
            "lead": _text(names.of(xs)),
            "leadListings": _count(len(xs)),
            "leadChampions": _count(len(champions[k])),
            "leadFrom": _money(prices[0]),
            "leadTo": _money(prices[-1]),
        }
    for t in thirds[:1]:
        only = sorted(
            ((k, xs) for k, xs in keys[t].items() if k not in keys[focus]),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )
        params |= {
            "third": _shop(t),
            "thirdBrands": _count(len(spellings[t])),
            "thirdOnly": _count(len(only)),
            "thirdTop": _list(names.of(xs) for _, xs in only[:3]),
            "thirdTopListings": _list(str(len(xs)) for _, xs in only[:3]),
        }
    chart = Chart(
        kind=ChartKind.BARS,
        unit=ChartUnit.COUNT,
        rows=tuple(
            ChartRow(
                label=names.of(xs), retailer=rival, value=Decimal(_page_reviews(xs)), n=len(xs)
            )
            for _, xs in listed[:CHART_ROWS]
        ),
    )
    examples = [example(min(xs, key=_most_reviewed), i) for _, xs in listed]
    every = set().union(*(k.keys() for k in keys.values()))
    return _shown(key, n=len(absent), of=len(every), params=params, chart=chart, examples=examples)


# ---------------------------------------------------------------- 2 brand depth gaps


@dataclass(frozen=True)
class _House:
    """A brand both shops sell that the focus shop sells (almost) only as fragrance."""

    focus: list[_Listing]
    rival: list[_Listing]

    @property
    def focus_fragrance(self) -> int:
        return sum(x.product.category[0] == FRAGRANCE for x in self.focus)

    @property
    def rival_other(self) -> int:
        return sum(x.product.category[0] != FRAGRANCE for x in self.rival)


def brand_depth_gaps(  # noqa: PLR0913 -- the request's parts, then the injected brand key
    ds: DatasetV3,
    focus: str,
    rival: str,
    pairs: _Pairs,
    i: int,
    *,
    names: BrandNames,
) -> Finding:
    """The rival's hero products (``HERO_MIN_REVIEWS`` reviews) from brands both shops sell that
    the focus shop lacks: no exact counted match, and no focus listing of the brand whose name
    holds every word of the hero's (a likely matcher miss, screened out rather than counted).
    Also the houses the focus shop sells almost only as fragrance (``POLICY_SHARE`` % or more)
    while the rival sells ``MIN_COHORT`` or more of their other products."""
    key = FindingKey.BRAND_DEPTH_GAPS
    if pairs.reason is not None:
        return _withhold(key, pairs.reason)
    off = _ratings_off(ds)
    if off is not None:
        return _withhold(key, off)
    _, keys = _brands(ds, (focus, rival), i, names.key)
    shared = sorted(keys[focus].keys() & keys[rival].keys())
    focus_words = {k: [name_tokens(x.product.name) for x in keys[focus][k]] for k in shared}
    heroes: dict[str, list[_Listing]] = {}
    for k in shared:
        for x in keys[rival][k]:
            if _reviews(x) >= HERO_MIN_REVIEWS:
                heroes.setdefault(_page(x), []).append(x)
    matched = screened = 0
    absent: list[_Listing] = []
    for members in heroes.values():
        if any(same_item(ds, x.product, rival, focus) for x in members):
            matched += 1
            continue
        hero = min(members, key=_most_reviewed)
        words = name_tokens(hero.product.name)
        if words and any(words <= w for w in focus_words[names.key(hero.product.brand)]):
            screened += 1
            continue
        absent.append(hero)
    if len(absent) < MIN_COHORT:
        return _withhold(key, Reason.COHORT_TOO_SMALL)
    absent.sort(key=_most_reviewed)
    houses = sorted(
        (
            h
            for k in shared
            if (h := _House(keys[focus][k], keys[rival][k])).focus_fragrance * 100
            >= POLICY_SHARE * len(h.focus)
            and h.rival_other >= MIN_COHORT
        ),
        key=lambda h: (-h.rival_other, names.of(h.rival)),
    )
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "rival": _shop(rival),
        "heroes": _count(len(heroes)),
        "absent": _count(len(absent)),
        "matched": _count(matched),
        "screened": _count(screened),
        "minReviews": _count(HERO_MIN_REVIEWS),
        "shared": _count(len(shared)),
        "absentNames": _list(f"{names.show(x.product.brand)} {x.product.name}" for x in absent[:4]),
        "houses": _count(len(houses)),
        "houseNames": _list(names.of(h.rival) for h in houses[:3]),
        "policySharePct": _pct(POLICY_SHARE),
    }
    lead_keys = ("lead", "leadFocusFragrance", "leadFocusOther", "leadRivalOther")
    params |= dict.fromkeys(lead_keys, MISSING)
    if houses:
        h = houses[0]
        params |= {
            "lead": _text(names.of(h.rival)),
            "leadFocusFragrance": _count(h.focus_fragrance),
            "leadFocusOther": _count(len(h.focus) - h.focus_fragrance),
            "leadRivalOther": _count(h.rival_other),
        }
    rows = []
    for h in houses[:4]:
        label = names.of(h.rival)
        for c, listings in ((focus, h.focus), (rival, h.rival)):
            frag = sum(x.product.category[0] == FRAGRANCE for x in listings)
            parts = (Decimal(frag), Decimal(len(listings) - frag))
            rows.append(
                ChartRow(label=label, retailer=c, value=Decimal(len(listings)), parts=parts)
            )
    chart = Chart(
        kind=ChartKind.STACKED,
        unit=ChartUnit.COUNT,
        columns=(FRAGRANCE, "other"),
        rows=tuple(rows),
    )
    examples = [example(x, i) for x in absent]
    return _shown(key, n=len(absent), of=len(heroes), params=params, chart=chart, examples=examples)


# ---------------------------------------------------------------- 3 brand price policy


def brand_price_policy(  # noqa: PLR0913 -- the request's parts, then the brand names
    ds: DatasetV3, focus: str, rival: str, pairs: _Pairs, i: int, *, names: BrandNames
) -> Finding:
    """Per brand, where the focus shop's prices sit against the rival's on the same items
    (``insights.brand_policies``), with the basket, and how many of the focus shop's cheaper
    pairs are still cheaper at its stated regular price (list price, not promotion)."""
    key = FindingKey.BRAND_PRICE_POLICY
    if pairs.reason is not None:
        return _withhold(key, pairs.reason)
    brands, _ = brand_policies(pairs.counted)
    if not brands:
        return _withhold(key, Reason.COHORT_TOO_SMALL)
    rows = pairs.counted
    cheaper = Counter(r.gap.cheaper for r in rows if r.gap is not None)
    rival_prices = [r.base_price for r in rows if r.base_price is not None]
    focus_prices = [r.other_price for r in rows if r.other_price is not None]
    rival_total = sum((p.decimal() for p in rival_prices), Decimal(0))
    focus_total = sum((p.decimal() for p in focus_prices), Decimal(0))
    currency = rival_prices[0].currency
    at_regular = 0
    for r in rows:
        if r.gap is None or r.gap.cheaper is not Cheaper.OTHER or r.base_price is None:
            continue
        listed = view.regular_on(_listing(ds, r.id, focus).offer, i) or r.other_price
        at_regular += listed is not None and listed.decimal() < r.base_price.decimal()
    undercut = [b for b in brands if b.policy is Policy.OTHER_CHEAPER]
    parity = sorted((b for b in brands if b.policy is Policy.PARITY), key=lambda b: (-b.n, b.brand))
    named = undercut[:5]
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "rival": _shop(rival),
        "n": _count(len(rows)),
        "focusCheaper": _count(cheaper[Cheaper.OTHER]),
        "level": _count(cheaper[Cheaper.EQUAL]),
        "rivalCheaper": _count(cheaper[Cheaper.BASE]),
        "basketPct": _pct((focus_total / rival_total - 1) * 100),
        "basketFocus": _money(MoneyValue.of(focus_total, currency)),
        "basketRival": _money(MoneyValue.of(rival_total, currency)),
        "cheaperAtRegular": _count(at_regular),
        "brands": _count(len(brands)),
        "undercut": _count(len(undercut)),
        "undercutNames": _list(names.show(b.brand) for b in named),
        "undercutLowPct": _or_missing(max((b.median_gap_pct for b in named), default=None), _pct),
        "undercutHighPct": _or_missing(min((b.median_gap_pct for b in named), default=None), _pct),
        "parity": _count(len(parity)),
        "parityNames": _list(names.show(b.brand) for b in parity[:4]),
        "policySharePct": _pct(POLICY_SHARE),
    }
    params |= dict.fromkeys(("lead", "leadCheaper", "leadN", "leadMedianPct"), MISSING)
    params |= dict.fromkeys(("parityLead", "parityLeadLevel", "parityLeadN"), MISSING)
    if undercut:
        lead = max(undercut, key=lambda b: (b.other_cheaper, -b.median_gap_pct, b.brand))
        params |= {
            "lead": _text(names.show(lead.brand)),
            "leadCheaper": _count(lead.other_cheaper),
            "leadN": _count(lead.n),
            "leadMedianPct": _pct(lead.median_gap_pct),
        }
    if parity:
        params |= {
            "parityLead": _text(names.show(parity[0].brand)),
            "parityLeadLevel": _count(parity[0].equal),
            "parityLeadN": _count(parity[0].n),
        }
    chart = Chart(kind=ChartKind.DIVERGING, unit=ChartUnit.PCT, rows=_policy_rows(brands, names))
    examples: list[Example] = []
    for chosen in (undercut[:EXAMPLES_PER_SIDE], parity[:EXAMPLES_PER_SIDE]):
        # the brands' pairs in turn, so two brands show one pair each and one brand shows two
        mine = [sorted((r for r in rows if r.brand == b.brand), key=_by_gap) for b in chosen]
        turns = (r for r in chain.from_iterable(zip_longest(*mine)) if r is not None)
        examples += distinct(_pair_example(ds, r, rival, focus, i) for r in turns)[
            :EXAMPLES_PER_SIDE
        ]
    return _shown(key, n=len(rows), of=pairs.both, params=params, chart=chart, examples=examples)


def _policy_rows(brands: tuple[BrandPolicy, ...], names: BrandNames) -> tuple[ChartRow, ...]:
    """The ``CHART_ROWS`` brands furthest from parity, most negative first."""
    far = sorted(brands, key=lambda b: (-abs(b.median_gap_pct), -b.n, b.brand))[:CHART_ROWS]
    far.sort(key=lambda b: (b.median_gap_pct, -b.n, b.brand))
    return tuple(ChartRow(label=names.show(b.brand), value=b.median_gap_pct, n=b.n) for b in far)


# ---------------------------------------------------------------- 4 size level gaps


def size_label(s: SizeGap) -> str:
    return f"{s.value} {s.unit}"


def _measure(ds: DatasetV3, product_id: str, context: str) -> tuple[str, str] | None:
    """The size key ``insights.size_gaps`` groups by: (unit, value)."""
    size = view.product_v3(ds, product_id).offers[context].size
    if size is None or size.value is None or size.unit is None:
        return None
    return size.unit.casefold(), f"{Decimal(size.value).normalize():f}"


def size_level_gaps(ds: DatasetV3, focus: str, rival: str, pairs: _Pairs, i: int) -> Finding:
    """The gap on the same items by published size (``insights.size_gaps``): the hero size, where
    the focus shop is furthest below the rival, against the entry (smallest) size."""
    key = FindingKey.SIZE_LEVEL_GAPS
    if pairs.reason is not None:
        return _withhold(key, pairs.reason)
    sizes, suppressed = size_gaps(ds, pairs.counted, rival)
    if len(sizes) < 2:
        return _withhold(key, Reason.COHORT_TOO_SMALL)
    hero = min(sizes, key=lambda s: (s.median_gap_pct, -s.n, Decimal(s.value)))
    entry = min(sizes, key=lambda s: (s.unit != hero.unit, Decimal(s.value)))
    n = sum(s.n for s in sizes)
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "rival": _shop(rival),
        "n": _count(n),
        "sizes": _count(len(sizes)),
        "suppressed": _count(suppressed),
    }
    for role, s in (("hero", hero), ("entry", entry)):
        params |= {
            role: _text(size_label(s)),
            f"{role}Cheaper": _count(s.other_cheaper),
            f"{role}Level": _count(s.equal),
            f"{role}N": _count(s.n),
            f"{role}MedianPct": _pct(s.median_gap_pct),
        }
    chart = Chart(
        kind=ChartKind.DIVERGING,
        unit=ChartUnit.PCT,
        rows=tuple(ChartRow(label=size_label(s), value=s.median_gap_pct, n=s.n) for s in sizes),
    )
    examples: list[Example] = []
    for s in (hero, entry):
        at = sorted(
            (r for r in pairs.counted if _measure(ds, r.id, rival) == (s.unit, s.value)),
            key=_by_gap,
        )
        examples += distinct(_pair_example(ds, r, rival, focus, i) for r in at)[:EXAMPLES_PER_SIDE]
    return _shown(key, n=n, of=len(pairs.counted), params=params, chart=chart, examples=examples)


# ---------------------------------------------------------------- 5 stock


def stock(  # noqa: PLR0913 -- the request's parts, then the injected brand key
    ds: DatasetV3,
    focus: str,
    rival: str,
    thirds: tuple[str, ...],
    i: int,
    *,
    names: BrandNames,
) -> Finding:
    """Out-of-stock counts by brand at the focus shop (``insights.brand_stockouts``: brands the
    source reports wholly unavailable kept apart), and the rival's out-of-stock brands the focus
    shop has in stock. Counts only: shops are never ranked on them."""
    key = FindingKey.STOCK
    shops = {c: brand_stockouts(ds, c, i) for c in (focus, rival, *thirds)}
    chips = [
        Chip(code=ChipCode.STOCK_NOT_COLLECTED, retailer=c)
        for c, s in shops.items()
        if s.reason is not None or s.with_stock == 0
    ]
    mine = shops[focus]
    if mine.reason is not None:
        return _withhold(key, mine.reason, chips=chips)
    if not mine.brands:
        return _withhold(key, Reason.COHORT_TOO_SMALL, chips=chips)
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "rival": _shop(rival),
        "outOfStock": _count(mine.out_of_stock),
        "brands": _count(mine.qualifying),
        "withStock": _count(mine.with_stock),
        "listed": _count(mine.listed),
        "unavailableListings": _count(mine.unavailable_listings),
        "unavailableBrands": _count(mine.unavailable_brands),
    }
    for n, row in enumerate(mine.brands[:2], 1):
        params |= {
            f"brand{n}": _text(names.show(row.brand)),
            f"brand{n}Out": _count(row.out_of_stock),
            f"brand{n}Observed": _count(row.observed),
        }
    in_stock = Counter(names.key(x.product.brand) for x in _seen(ds, focus, i) if _stocked(x, i))
    theirs = shops[rival]
    short = (
        [] if theirs.reason else [r for r in theirs.brands if in_stock[names.key(r.brand)] > 0][:3]
    )
    params |= {
        "rivalShort": _list(names.show(r.brand) for r in short),
        "rivalShortOut": _list(str(r.out_of_stock) for r in short),
        "rivalShortFocusIn": _list(str(in_stock[names.key(r.brand)]) for r in short),
    }
    chart = Chart(
        kind=ChartKind.BARS,
        unit=ChartUnit.COUNT,
        rows=tuple(
            ChartRow(
                label=names.show(r.brand),
                retailer=focus,
                value=Decimal(r.out_of_stock),
                of=r.observed,
            )
            for r in mine.brands[:6]
        ),
    )
    found = [_out(ds, focus, r.brand, i) for r in mine.brands[:4]]
    found += [_out(ds, rival, r.brand, i) for r in short[:2]]
    examples = [e for e in found if e is not None]
    return _shown(
        key,
        n=mine.with_stock,
        of=mine.listed,
        params=params,
        chart=chart,
        examples=examples,
        chips=chips,
    )


def _out(ds: DatasetV3, context: str, brand: str, i: int) -> Example | None:
    """The brand's most-reviewed out-of-stock listing at the context."""
    out = [x for x in _seen(ds, context, i) if x.product.brand == brand and _out_of_stock(x, i)]
    return example(min(out, key=_most_reviewed), i) if out else None


# ---------------------------------------------------------------- 6 promo strategy


def _promo_off(ds: DatasetV3, context: str, unverified: frozenset[str]) -> Reason | None:
    """Why the context's markdowns are not shown, as summary's promotion metrics gate them."""
    if not ds.meta.capabilities.promotions:
        return Reason.CAPABILITY_OFF
    if ds.meta.fields.get("regular", FieldStatus.NOT_COLLECTED) in {
        FieldStatus.NOT_COLLECTED,
        FieldStatus.NOT_PUBLISHED,
    }:
        return Reason.FIELD_NOT_COLLECTED
    if context in unverified:
        return Reason.WAS_PRICE_UNVERIFIED
    return None


def _stated(ds: DatasetV3, context: str, i: int) -> list[tuple[_Priced, MoneyValue]]:
    """Priced listings with a stated regular price in the same currency."""
    out = []
    for x in _priced(ds, context, i):
        regular = view.regular_on(x.offer, i)
        if regular is not None and regular.currency == x.price.currency:
            out.append((x, regular))
    return out


def _markdowns(
    ds: DatasetV3, context: str, i: int, unverified: frozenset[str]
) -> list[tuple[_Priced, MoneyValue]] | None:
    """The context's listings with a stated regular, or ``None`` when it shows no discounts
    (gated, or no regular stated)."""
    if _promo_off(ds, context, unverified) is not None:
        return None
    return _stated(ds, context, i) or None


def _marked(x: _Priced, regular: MoneyValue) -> bool:
    return regular.decimal() > x.price.decimal()


def promo_strategy(  # noqa: PLR0913 -- the request's parts, then the brand names
    ds: DatasetV3,
    focus: str,
    thirds: tuple[str, ...],
    i: int,
    unverified: frozenset[str],
    *,
    names: BrandNames,
) -> Finding:
    """How the focus shop marks down: listings with a stated regular price that are marked down,
    the most common depth, the brands that depend on promotion, the large brands never marked
    down, and breadth by price band; with the first third shop's markdowns."""
    key = FindingKey.PROMO_STRATEGY
    stated = {c: _markdowns(ds, c, i, unverified) for c in (focus, *thirds)}
    chips = [
        Chip(code=ChipCode.DISCOUNTS_NOT_SHOWN, retailer=c) for c, s in stated.items() if not s
    ]
    off = _promo_off(ds, focus, unverified)
    if off is not None:
        return _withhold(key, off, chips=chips)
    mine = stated[focus] or []
    marked = [(x, r) for x, r in mine if _marked(x, r)]
    by: defaultdict[str, list[bool]] = defaultdict(list)
    for x, r in mine:
        by[x.product.brand].append(_marked(x, r))
    listed = {b: v for b, v in by.items() if len(v) >= PROMO_MIN_LISTINGS}
    if not marked or not listed:
        return _withhold(key, Reason.COHORT_TOO_SMALL, chips=chips)
    dependent = sorted(
        (b for b, v in listed.items() if share(sum(v), len(v)) >= PROMO_DEPENDENT_PCT),
        key=lambda b: (-share(sum(by[b]), len(by[b])), -len(by[b]), b),
    )
    large = [b for b, v in by.items() if len(v) >= PROMO_LARGE_BRAND]
    depths = Counter(depth(x.price, r).quantize(Decimal(1), ROUND_HALF_UP) for x, r in marked)
    mode, mode_n = min(depths.items(), key=lambda kv: (-kv[1], kv[0]))
    low = [_marked(x, r) for x, r in mine if r.decimal() < PRICE_BANDS[0]]
    high = [_marked(x, r) for x, r in mine if r.decimal() >= PROMO_HIGH_BAND]
    currency = _currency(ds, focus)
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "marked": _count(len(marked)),
        "stated": _count(len(mine)),
        "modePct": _pct(mode),
        "modeCount": _count(mode_n),
        "dependent": _count(len(dependent)),
        "dependentNames": _list(names.show(b) for b in dependent[:3]),
        "dependentMarked": _list(str(sum(by[b])) for b in dependent[:3]),
        "dependentListed": _list(str(len(by[b])) for b in dependent[:3]),
        "large": _count(len(large)),
        "largeNever": _count(sum(1 for b in large if not any(by[b]))),
        "lowBand": _money(MoneyValue.of(PRICE_BANDS[0], currency)),
        "lowBandPct": _or_missing(share(sum(low), len(low)) if low else None, _pct),
        "highBand": _money(MoneyValue.of(PROMO_HIGH_BAND, currency)),
        "highBandPct": _or_missing(share(sum(high), len(high)) if high else None, _pct),
    }
    third_down: list[tuple[_Priced, MoneyValue]] = []
    for t in thirds[:1]:
        theirs = stated[t]
        down = [] if theirs is None else [(x, r) for x, r in theirs if _marked(x, r)]
        third_down = sorted(down, key=lambda m: (-depth(m[0].price, m[1]), m[0].product.id))
        median = nearest_rank((depth(x.price, r) for x, r in down), _MEDIAN) if down else None
        params |= {
            "third": _shop(t),
            "thirdMarked": MISSING if theirs is None else _count(len(down)),
            "thirdMedianPct": _or_missing(median, _pct),
            "thirdBrands": _list(
                names.show(b) for b, _ in Counter(x.product.brand for x, _ in down).most_common(3)
            ),
        }
    chart = Chart(
        kind=ChartKind.BARS,
        unit=ChartUnit.PCT,
        rows=tuple(
            ChartRow(
                label=names.show(b),
                retailer=focus,
                value=share(sum(by[b]), len(by[b])),
                n=sum(by[b]),
                of=len(by[b]),
            )
            for b in dependent[:CHART_ROWS]
        ),
    )
    dearest = sorted(marked, key=lambda m: (-m[1].decimal(), m[0].product.id))
    examples = [
        *distinct(example(x, i) for x, _ in dearest)[:EXAMPLES_PER_SIDE],
        *distinct(example(x, i) for x, _ in third_down)[:EXAMPLES_PER_SIDE],
    ]
    of = sum(1 for _ in _priced(ds, focus, i))
    return _shown(
        key, n=len(mine), of=of, params=params, chart=chart, examples=examples, chips=chips
    )


# ---------------------------------------------------------------- 7 real discounts


@dataclass(frozen=True)
class _Markdown:
    row: PairRow
    on: str
    versus: str
    price: MoneyValue
    regular: MoneyValue
    versus_price: MoneyValue

    @property
    def depth(self) -> Decimal:
        return depth(self.price, self.regular)

    @property
    def real(self) -> bool:
        """The stated regular is within ``REAL_DISCOUNT_TOLERANCE_PCT`` % of the other price."""
        off = abs(self.regular.decimal() - self.versus_price.decimal())
        return off * 100 <= REAL_DISCOUNT_TOLERANCE_PCT * self.versus_price.decimal()


def real_discounts(  # noqa: PLR0913 -- the request's parts, then the unverified contexts
    ds: DatasetV3,
    focus: str,
    rival: str,
    thirds: tuple[str, ...],
    i: int,
    *,
    first: _Pairs,
    on: date | None,
    unverified: frozenset[str],
    names: BrandNames,
) -> Finding:
    """On counted pairs between any two shops: the markdowns either side states, and how many
    are real (the stated regular price is what the other shop charges). ``first`` holds the
    rival's and the focus shop's pairs, already read."""
    key = FindingKey.REAL_DISCOUNTS
    counted = 0
    marks: list[_Markdown] = []
    for s, t in combinations((focus, rival, *thirds), 2):
        if {s, t} == {focus, rival}:
            a, b, pairs = rival, focus, first
        else:
            a, b, pairs = s, t, _pairs(ds, s, t, on)
        counted += len(pairs.counted)
        for r in pairs.counted:
            if r.base_price is None or r.other_price is None:
                continue
            sides = ((a, b, r.base_price, r.other_price), (b, a, r.other_price, r.base_price))
            for x, y, price, other in sides:
                if _promo_off(ds, x, unverified) is not None:
                    continue
                regular = view.regular_on(_listing(ds, r.id, x).offer, i)
                if (
                    regular is not None
                    and regular.currency == price.currency
                    and regular.decimal() > price.decimal()
                ):
                    marks.append(_Markdown(r, x, y, price, regular, other))
    if counted == 0:
        return _withhold(key, first.reason or Reason.NO_MATCH)
    if len(marks) < REAL_DISCOUNT_MIN:
        return _withhold(key, Reason.COHORT_TOO_SMALL)
    marks.sort(key=lambda m: (-m.depth, m.row.id, m.on))
    lead = marks[0]
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "pairs": _count(counted),
        "markdowns": _count(len(marks)),
        "real": _count(sum(m.real for m in marks)),
        "tolerancePct": _pct(REAL_DISCOUNT_TOLERANCE_PCT),
        "focusMarkdowns": _count(sum(m.on == focus for m in marks)),
        "lead": _text(f"{names.show(lead.row.brand)} {lead.row.name}"),
        "leadShop": _shop(lead.on),
        "leadPct": _pct(lead.depth),
        "leadPrice": _money(lead.price),
        "leadRegular": _money(lead.regular),
        "leadVersus": _shop(lead.versus),
        "leadVersusPrice": _money(lead.versus_price),
    }
    chart = Chart(
        kind=ChartKind.BARS,
        unit=ChartUnit.PCT,
        rows=tuple(
            ChartRow(label=f"{names.show(m.row.brand)} {m.row.name}", retailer=m.on, value=m.depth)
            for m in marks[:CHART_ROWS]
        ),
    )
    examples = [
        example(
            _listing(ds, m.row.id, m.on),
            i,
            versus=_listing(ds, m.row.id, m.versus),
            versus_price=m.versus_price,
            gap_pct=(m.price.decimal() / m.versus_price.decimal() - 1) * 100,
        )
        for m in marks
    ]
    return _shown(key, n=len(marks), of=counted, params=params, chart=chart, examples=examples)


# ---------------------------------------------------------------- 8 fragrance ladder


class Upgrade(StrEnum):
    #: Eau de parfum over eau de toilette, same line and bottle size.
    EDP_EDT = "edp_edt"
    #: A flanker (Intense, Elixir, Absolu, Extreme, Le Parfum) over its EDP.
    FLANKER_EDP = "flanker_edp"


@dataclass(frozen=True)
class Rung:
    upgrade: Upgrade
    up: _Priced
    base: _Priced

    @property
    def premium(self) -> Decimal:
        """How much more the upgrade costs than its base, same size, in %."""
        return (self.up.price.decimal() / self.base.price.decimal() - 1) * 100


def _bottle(x: _Priced) -> Decimal | None:
    """The bottle size in ml of a fragrance listing that is a single bottle, else ``None``."""
    size = x.offer.size
    if (
        x.product.category[0] != FRAGRANCE
        or size is None
        or size.value is None
        or view.fold(size.unit or "") != ML
        or NOT_A_BOTTLE.search(x.product.name)
    ):
        return None
    return Decimal(size.value)


def fragrance_rungs(ds: DatasetV3, context: str, i: int, brand_key: BrandKey) -> list[Rung]:
    """Within one shop, same brand, line and bottle size: EDP over EDT, and flanker over EDP.
    A group with two listings of one kind is skipped, never guessed."""
    groups: defaultdict[tuple[str, str, Decimal], defaultdict[str, list[_Priced]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for x in _priced(ds, context, i):
        ml = _bottle(x)
        kind = "flanker" if FLANKER.search(x.product.name) else concentration(x.product.name)
        if ml is not None and kind is not None:
            line = (brand_key(x.product.brand), fragrance_line(x.product.name), ml)
            groups[line][kind].append(x)
    rungs = []
    for line in sorted(groups):
        one = {k: v[0] for k, v in groups[line].items() if len(v) == 1}
        if "edp" in one and "edt" in one:
            rungs.append(Rung(Upgrade.EDP_EDT, one["edp"], one["edt"]))
        if "flanker" in one and "edp" in one:
            rungs.append(Rung(Upgrade.FLANKER_EDP, one["flanker"], one["edp"]))
    return rungs


def fragrance_ladder(  # noqa: PLR0913 -- the request's parts, then the injected brand key
    ds: DatasetV3,
    focus: str,
    rival: str,
    thirds: tuple[str, ...],
    i: int,
    *,
    names: BrandNames,
) -> Finding:
    """What each upgrade costs at each shop (median premium, groups under ``MIN_COHORT`` pairs
    suppressed), and the focus shop's inversions: an upgrade cheaper than its base."""
    key = FindingKey.FRAGRANCE_LADDER
    contexts = (focus, rival, *thirds)
    rungs = {c: fragrance_rungs(ds, c, i, names.key) for c in contexts}
    groups = {
        (c, u): sorted(r.premium for r in rungs[c] if r.upgrade is u)
        for c in contexts
        for u in Upgrade
    }
    kept = {k: v for k, v in groups.items() if len(v) >= MIN_COHORT}
    chips = [
        Chip(code=ChipCode.TOO_FEW_PAIRS, retailer=c)
        for c in contexts
        if not any(k[0] == c for k in kept)
    ]
    if not any(k[0] == focus for k in kept):
        return _withhold(key, Reason.COHORT_TOO_SMALL, chips=chips)
    inversions = sorted(
        (r for r in rungs[focus] if r.premium < 0), key=lambda r: (r.premium, r.up.product.id)
    )
    params: dict[str, Param] = {"focus": _shop(focus), "rival": _shop(rival)}
    for role, c in (("focus", focus), ("rival", rival)):
        for u, name in ((Upgrade.EDP_EDT, "Edp"), (Upgrade.FLANKER_EDP, "Flanker")):
            values = kept.get((c, u))
            median = nearest_rank(values, _MEDIAN) if values else None
            params[f"{role}{name}Pct"] = _or_missing(median, _pct)
            params[f"{role}{name}N"] = _count(len(groups[(c, u)]))
            params[f"{role}{name}Negative"] = _count(sum(v < 0 for v in groups[(c, u)]))
    params["inversions"] = _count(len(inversions))
    lead_keys = ("lead", "leadBase", "leadPct", "leadPrice", "leadBasePrice")
    params |= dict.fromkeys(lead_keys, MISSING)
    if inversions:
        lead = inversions[0]
        params |= {
            "lead": _text(f"{names.show(lead.up.product.brand)} {lead.up.product.name}"),
            "leadBase": _text(lead.base.product.name),
            "leadPct": _pct(lead.premium),
            "leadPrice": _money(lead.up.price),
            "leadBasePrice": _money(lead.base.price),
        }
    chart = Chart(
        kind=ChartKind.STRIPS,
        unit=ChartUnit.PCT,
        rows=tuple(
            ChartRow(
                label=u.value,
                code=True,
                retailer=c,
                value=nearest_rank(v, _MEDIAN),
                n=len(v),
                parts=tuple(v),
            )
            for u in Upgrade
            for c in contexts
            if (v := kept.get((c, u)))
        ),
    )
    examples = [
        example(r.up, i, versus=r.base, versus_price=r.base.price, gap_pct=r.premium)
        for r in inversions
    ]
    n = sum(len(v) for (c, _), v in groups.items() if c == focus)
    return _shown(key, n=n, of=None, params=params, chart=chart, examples=examples, chips=chips)


# ---------------------------------------------------------------- 9 size traps


def _step_label(s: LadderStep, names: BrandNames) -> str:
    return f"{names.show(s.brand)} {s.family} {s.smaller_value}→{s.larger_value} {s.unit}"


def size_traps(  # noqa: PLR0913 -- the request's parts, then the brand names
    ds: DatasetV3, focus: str, rival: str, thirds: tuple[str, ...], i: int, *, names: BrandNames
) -> Finding:
    """Going up a size at each shop (``insights.size_ladder``): the median per-unit saving, and
    the focus shop's steps where the larger size is not cheaper per unit."""
    key = FindingKey.SIZE_TRAPS
    roles = (("focus", focus), ("rival", rival), *(("third", t) for t in thirds[:1]))
    ladders = {c: size_ladder(ds, c, i) for c in (focus, rival, *thirds)}
    chips = [
        Chip(code=ChipCode.TOO_FEW_PAIRS, retailer=c) for c, lad in ladders.items() if lad.reason
    ]
    mine = ladders[focus]
    if mine.reason is not None:
        return _withhold(key, mine.reason, chips=chips)
    params: dict[str, Param] = {}
    for role, c in roles:
        lad = ladders[c]
        params |= {
            role: _shop(c),
            f"{role}Steps": _count(lad.steps),
            f"{role}SavingPct": _or_missing(lad.median_saving_pct, _pct),
            f"{role}NotCheaper": MISSING if lad.reason else _count(lad.not_cheaper),
        }
    params["heldOut"] = _count(mine.held_out)
    params |= dict.fromkeys(("lead", "leadPct"), MISSING)
    if mine.exceptions:
        params |= {
            "lead": _text(_step_label(mine.exceptions[0], names)),
            "leadPct": _pct(mine.exceptions[0].unit_change_pct),
        }
    chart = Chart(
        kind=ChartKind.BARS,
        unit=ChartUnit.PCT,
        rows=tuple(
            ChartRow(label=_step_label(s, names), retailer=focus, value=s.unit_change_pct)
            for s in mine.exceptions[:CHART_ROWS]
        ),
    )
    examples = [
        example(
            _listing(ds, s.larger_id, focus),
            i,
            versus=_listing(ds, s.smaller_id, focus),
            versus_price=s.smaller_price,
            gap_pct=s.unit_change_pct,
        )
        for s in mine.exceptions
    ]
    return _shown(
        key, n=mine.steps, of=None, params=params, chart=chart, examples=examples, chips=chips
    )


# ---------------------------------------------------------------- 10 positioning


def positioning(ds: DatasetV3, focus: str, rival: str, thirds: tuple[str, ...], i: int) -> Finding:
    """Each shop's price mix by category: the share under the first band edge, at or over the
    last, and the median; categories with fewer than ``POSITION_MIN`` priced listings at a shop
    left out (``missing``)."""
    key = FindingKey.POSITIONING
    contexts = (focus, rival, *thirds)
    priced = {c: list(_priced(ds, c, i)) for c in contexts}
    mix: dict[tuple[str, str], list[_Priced]] = {}
    for c in contexts:
        for category in POSITION_CATEGORIES:
            xs = [x for x in priced[c] if x.product.category[0] == category]
            if len(xs) >= POSITION_MIN:
                mix[(c, category)] = xs
    if not any(c == focus for c, _ in mix) or not any(c != focus for c, _ in mix):
        return _withhold(key, Reason.COHORT_TOO_SMALL)
    currency = _currency(ds, focus)
    roles = (("Focus", focus), ("Rival", rival), *(("Third", t) for t in thirds[:1]))
    params: dict[str, Param] = {role.lower(): _shop(c) for role, c in roles}
    params["lowBand"] = _money(MoneyValue.of(PRICE_BANDS[0], currency))
    params["highBand"] = _money(MoneyValue.of(PRICE_BANDS[-1], currency))
    for role, c in roles:
        for category in POSITION_CATEGORIES:
            amounts = [x.price.decimal() for x in mix.get((c, category), [])]
            if not amounts:
                params |= dict.fromkeys(
                    (f"{category}Under{role}", f"{category}Over{role}", f"{category}Median{role}"),
                    MISSING,
                )
                continue
            median = nearest_rank(amounts, _MEDIAN)
            params |= {
                f"{category}Under{role}": _pct(
                    share(sum(a < PRICE_BANDS[0] for a in amounts), len(amounts))
                ),
                f"{category}Over{role}": _pct(
                    share(sum(a >= PRICE_BANDS[-1] for a in amounts), len(amounts))
                ),
                f"{category}Median{role}": _money(MoneyValue.of(median, currency)),
            }
        frag = sum(x.product.category[0] == FRAGRANCE for x in priced[c])
        params[f"fragranceShare{role}"] = _or_missing(
            share(frag, len(priced[c])) if priced[c] else None, _pct
        )
    rows = []
    for category in POSITION_CHARTED:
        for c in contexts:
            cell = mix.get((c, category))
            if cell:
                bands = Counter(band_of(x.price.decimal()) for x in cell)
                parts = tuple(share(bands[b], len(cell)) for b in range(len(PRICE_BANDS) + 1))
                rows.append(
                    ChartRow(
                        label=category,
                        code=True,
                        retailer=c,
                        value=Decimal(100),
                        n=len(cell),
                        parts=parts,
                    )
                )
    chart = Chart(
        kind=ChartKind.STACKED, unit=ChartUnit.PCT, columns=band_labels(), rows=tuple(rows)
    )
    cheap = sorted(
        (x for x in mix.get((focus, "lips"), []) if x.price.decimal() < PRICE_BANDS[0]),
        key=_most_reviewed,
    )
    dear = sorted(
        (x for x in mix.get((rival, FRAGRANCE), []) if x.price.decimal() >= PRICE_BANDS[-1]),
        key=_most_reviewed,
    )
    examples = [
        *distinct(example(x, i) for x in cheap)[:EXAMPLES_PER_SIDE],
        *distinct(example(x, i) for x in dear)[:EXAMPLES_PER_SIDE],
    ]
    n = sum(len(v) for v in mix.values())
    of = sum(len(v) for v in priced.values())
    return _shown(key, n=n, of=of, params=params, chart=chart, examples=examples)


# ---------------------------------------------------------------- 11 price vs rating


class Stars(StrEnum):
    #: At least ``VALUE_RATING_PCT`` % of the scale.
    HIGH = "high"
    #: At least ``LAGGARD_RATING_PCT`` %.
    MID = "mid"
    LOW = "low"


def stars(x: _Listing) -> Stars:
    pct = rating_pct(x)
    if pct >= VALUE_RATING_PCT:
        return Stars.HIGH
    return Stars.MID if pct >= LAGGARD_RATING_PCT else Stars.LOW


def price_vs_rating(
    ds: DatasetV3, focus: str, rival: str, thirds: tuple[str, ...], i: int
) -> Finding:
    """In the first of the focus, rival and third shops with ``RATED_SHOP_MIN`` rated products:
    the rank correlation of price and rating per category, and the champions (cheapest quartile,
    highly rated) against the laggards (dearest quartile, rated low). Shops under it get a chip;
    shops are never compared on ratings."""
    key = FindingKey.PRICE_VS_RATING
    off = _ratings_off(ds)
    if off is not None:
        return _withhold(key, off)
    contexts = (focus, rival, *thirds)
    rated = {c: _rated(ds, c, i) for c in contexts}
    chips = [
        Chip(code=ChipCode.TOO_FEW_RATINGS, retailer=c)
        for c in contexts
        if rated[c].n < RATED_SHOP_MIN
    ]
    shop = next((c for c in contexts if rated[c].n >= RATED_SHOP_MIN), None)
    if shop is None:
        return _withhold(key, Reason.COHORT_TOO_SMALL, chips=chips)
    r = rated[shop]
    rhos: dict[str, tuple[Decimal, int]] = {}
    for category, xs in r.by_category.items():
        rho = spearman([x.price.decimal() for x in xs], [_rating(x) for x in xs])
        if rho is not None:
            rhos[category] = (rho, len(xs))
    champions = sorted((x for x in r.items() if _champion(r, x)), key=_most_reviewed)
    laggards = sorted((x for x in r.items() if _laggard(r, x)), key=_most_reviewed)
    cells = Counter((stars(x), r.quartile(x)) for x in r.items())
    params: dict[str, Param] = {
        "shop": _shop(shop),
        "focus": _shop(focus),
        "n": _count(r.n),
        "minReviews": _count(RATED_MIN_REVIEWS),
        "champions": _count(len(champions)),
        "laggards": _count(len(laggards)),
        "focusRated": _count(rated[focus].n),
        "rivalRated": _count(rated[rival].n),
    }
    params |= dict.fromkeys(
        ("fragranceRho", "fragranceN", "lowRho", "lowCategory", "highRho", "highCategory"),
        MISSING,
    )
    if FRAGRANCE in rhos:
        params |= {
            "fragranceRho": _ratio(rhos[FRAGRANCE][0]),
            "fragranceN": _count(rhos[FRAGRANCE][1]),
        }
    if rhos:
        low = min(rhos, key=lambda c: (rhos[c][0], c))
        high = max(rhos, key=lambda c: (rhos[c][0], c))
        params |= {
            "lowRho": _ratio(rhos[low][0]),
            "lowCategory": _category(low),
            "highRho": _ratio(rhos[high][0]),
            "highCategory": _category(high),
        }
    chart = Chart(
        kind=ChartKind.MATRIX,
        unit=ChartUnit.COUNT,
        columns=("q1", "q2", "q3", "q4"),
        rows=tuple(
            ChartRow(
                label=s.value,
                code=True,
                retailer=shop,
                value=Decimal(sum(cells[(s, q)] for q in range(4))),
                parts=tuple(Decimal(cells[(s, q)]) for q in range(4)),
            )
            for s in Stars
        ),
    )
    examples = [
        *distinct(example(x, i) for x in champions)[:EXAMPLES_PER_SIDE],
        *distinct(example(x, i) for x in laggards)[:EXAMPLES_PER_SIDE],
    ]
    of = sum(1 for _ in _priced(ds, shop, i))
    return _shown(key, n=r.n, of=of, params=params, chart=chart, examples=examples, chips=chips)


# ---------------------------------------------------------------- 12 pricing anomalies


def pricing_anomalies(  # noqa: PLR0913 -- the request's parts, then the brand names
    ds: DatasetV3, focus: str, rival: str, thirds: tuple[str, ...], i: int, *, names: BrandNames
) -> Finding:
    """Listings whose price the read-time floor withheld, per shop: likely samples or gifts
    exposed as products, and the in-stock ones a customer could order at that price."""
    key = FindingKey.PRICING_ANOMALIES
    contexts = (focus, rival, *thirds)
    seen = {c: list(_seen(ds, c, i)) for c in contexts}
    bad = {c: [x for x in seen[c] if _withheld(x.offer, i)] for c in contexts}
    total = sum(len(v) for v in bad.values())
    if total < THRESHOLD[key]:
        return _withhold(key, Reason.COHORT_TOO_SMALL)
    mine = bad[focus]
    brands = Counter(x.product.brand for x in mine).most_common(3)
    params: dict[str, Param] = {
        "focus": _shop(focus),
        "focusCount": _count(len(mine)),
        "focusInStock": _count(sum(_stocked(x, i) for x in mine)),
        "focusBrands": _list(names.show(b) for b, _ in brands),
        "focusBrandCounts": _list(str(n) for _, n in brands),
        "rival": _shop(rival),
        "rivalCount": _count(len(bad[rival])),
    }
    for t in thirds[:1]:
        params |= {"third": _shop(t), "thirdCount": _count(len(bad[t]))}
    chart = Chart(
        kind=ChartKind.BARS,
        unit=ChartUnit.COUNT,
        rows=tuple(
            ChartRow(label=c, code=True, retailer=c, value=Decimal(len(bad[c])), of=len(seen[c]))
            for c in contexts
        ),
    )
    order = sorted(mine, key=lambda x: (not _stocked(x, i), *_most_reviewed(x)))
    order += sorted((x for c in contexts[1:] for x in bad[c]), key=_most_reviewed)
    examples = [example(x, i) for x in order]
    of = sum(len(v) for v in seen.values())
    return _shown(key, n=total, of=of, params=params, chart=chart, examples=examples)


# ---------------------------------------------------------------- all twelve


def _presented(f: Finding, ds: DatasetV3, unverified: frozenset[str], names: BrandNames) -> Finding:
    """The finding's examples with each brand as ``display_brand`` writes it, and no regular
    price from a shop whose markdowns are not shown."""
    examples = tuple(
        e.model_copy(
            update={
                "brand": names.show(e.brand),
                "regular": None if _promo_off(ds, e.retailer, unverified) else e.regular,
            }
        )
        for e in f.examples
    )
    return f.model_copy(update={"examples": examples})


def ranked(items: Iterable[Finding]) -> tuple[Finding, ...]:
    """Shown findings in ``ORDER``, then withheld ones in ``ORDER``; ranks from 1."""
    ordered = sorted(items, key=lambda f: (f.status is not Status.OK, ORDER.index(f.key)))
    return tuple(f.model_copy(update={"rank": n}) for n, f in enumerate(ordered, 1))


def findings(  # noqa: PLR0913 -- the request, then the injected brand key and unverified set
    dataset: view.AnyDataset,
    focus: str,
    rival: str,
    *,
    on: date | None = None,
    brand_key: BrandKey = view.fold,
    unverified: frozenset[str] = frozenset(),
) -> Metric[Findings]:
    """The twelve findings for ``focus`` against ``rival``, every other context a third shop.

    ``brand_key`` cleans brand names for brand-level comparisons (pi_api passes pi_match's
    ``normalise_brand``); ``unverified`` holds the contexts whose was-prices are unverified.
    """
    ds = view.as_v3(dataset)
    if focus == rival:
        msg = "the two retailers must differ"
        raise view.UnknownInput(msg)
    view.context(ds, focus)
    view.context(ds, rival)
    thirds = tuple(c.id for c in ds.meta.contexts if c.id not in {focus, rival})
    i = view.date_index(ds, on)
    as_of = ds.meta.dates[i]
    if not view.applies(ds, PROFILES):
        return Metric[Findings](
            status=Status.NOT_ENOUGH_DATA,
            data=Findings(focus=focus, rival=rival, thirds=thirds, counted_pairs=0, findings=()),
            reason=Reason.NOT_APPLICABLE,
            as_of=as_of,
        )
    pairs = _pairs(ds, rival, focus, on)
    names = brand_names(ds, cache(brand_key))  # one key per brand name, not per listing
    shown = ranked(
        _presented(f, ds, unverified, names)
        for f in (
            brand_white_space(ds, focus, rival, thirds, i, names=names),
            brand_depth_gaps(ds, focus, rival, pairs, i, names=names),
            brand_price_policy(ds, focus, rival, pairs, i, names=names),
            size_level_gaps(ds, focus, rival, pairs, i),
            stock(ds, focus, rival, thirds, i, names=names),
            promo_strategy(ds, focus, thirds, i, unverified, names=names),
            real_discounts(
                ds, focus, rival, thirds, i, first=pairs, on=on, unverified=unverified, names=names
            ),
            fragrance_ladder(ds, focus, rival, thirds, i, names=names),
            size_traps(ds, focus, rival, thirds, i, names=names),
            positioning(ds, focus, rival, thirds, i),
            price_vs_rating(ds, focus, rival, thirds, i),
            pricing_anomalies(ds, focus, rival, thirds, i, names=names),
        )
    )
    ok = any(f.status is Status.OK for f in shown)
    caveats = tuple(
        Caveat(code=CaveatCode.RETAILER_PARTIAL, params={"retailer": c.id})
        for c in ds.meta.contexts
        if view.status(ds, c.id) is RetailerStatus.PARTIAL
    )
    return Metric[Findings](
        status=Status.OK if ok else Status.NOT_ENOUGH_DATA,
        data=Findings(
            focus=focus,
            rival=rival,
            thirds=thirds,
            counted_pairs=len(pairs.counted),
            findings=shown,
        ),
        reason=None if ok else Reason.COHORT_TOO_SMALL,
        cohort=Cohort(description="counted exact pairs, approved or locked", n=len(pairs.counted)),
        caveats=caveats,
        as_of=as_of,
    )
