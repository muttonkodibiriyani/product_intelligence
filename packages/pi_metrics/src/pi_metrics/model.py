"""Shared result types for every metric (service-layer design §5, §7).

Values are exact ``Decimal`` in Python. Rounding happens once, when a result is serialised to
JSON (``model_dump(mode="json")``): percentages and indexes at 1 dp, rating averages at 2 dp,
half away from zero. Money is a ``MoneyValue`` and is always exact, because the metrics only
add and subtract amounts in one currency.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import PlainSerializer

from pi_core import ReviewState
from pi_dataset import ContractModel, Product, ProductV3

#: Changes whenever a metric definition changes; recorded in docs/decision-log.md (design §7).
METRIC_VERSION = "2026-10-01.3"
#: Summary statistics need at least this many members (design §7.4).
MIN_COHORT = 5
#: Edge states a counted pair may have (design §7.2): approved (human or auto-accept) or locked.
COUNTED_STATES = frozenset({ReviewState.APPROVED, ReviewState.LOCKED})
#: The vertical profiles ADR-0008 names. Each metric states the ones it applies to; on any other
#: profile it answers ``not_enough_data`` / ``not_applicable``, never a 4xx or zeros (§3).
BEAUTY, FOOD_MENU, APPAREL = "beauty", "food_menu", "apparel"
EVERY_PROFILE = frozenset({BEAUTY, FOOD_MENU, APPAREL})


def fixed(places: int) -> Callable[[Decimal], str]:
    quantum = Decimal(1).scaleb(-places)

    def render(value: Decimal) -> str:
        return str(value.quantize(quantum, rounding=ROUND_HALF_UP))

    return render


#: A percentage (or share), exact in Python and ``"12.3"`` on the wire.
Pct = Annotated[Decimal, PlainSerializer(fixed(1), return_type=str, when_used="json")]
#: An index value (base = 100), 1 dp on the wire.
IndexValue = Annotated[Decimal, PlainSerializer(fixed(1), return_type=str, when_used="json")]
#: A rating average, 2 dp on the wire.
RatingValue = Annotated[Decimal, PlainSerializer(fixed(2), return_type=str, when_used="json")]


class Status(StrEnum):
    OK = "ok"
    NOT_ENOUGH_DATA = "not_enough_data"


class Reason(StrEnum):
    """The closed ``not_enough_data`` reasons (design §5)."""

    CAPABILITY_OFF = "capability_off"
    FIELD_NOT_COLLECTED = "field_not_collected"
    RETAILER_BLOCKED = "retailer_blocked"
    RETAILER_PARTIAL = "retailer_partial"
    COHORT_TOO_SMALL = "cohort_too_small"
    MATCHES_UNREVIEWED = "matches_unreviewed"
    NO_MATCH = "no_match"
    NOT_IN_SCOPE = "not_in_scope"
    CURRENCY_MISMATCH = "currency_mismatch"
    #: The metric doesn't apply to the snapshot's vertical profile (ADR-0008 §3).
    NOT_APPLICABLE = "not_applicable"


class Excluded(StrEnum):
    """Why a pair row is not counted. Every excluded row carries exactly one (design §7.2)."""

    NOT_OFFERED = "not_offered"
    EARLY = "early"
    NO_MATCH = "no_match"
    MATCH_REJECTED = "match_rejected"
    MATCH_UNREVIEWED = "match_unreviewed"
    MATCH_NOT_EXACT = "match_not_exact"
    UNPRICED = "unpriced"
    CURRENCY_MISMATCH = "currency_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    #: A size missing on either side: "same size" can't be shown, so the pair isn't counted.
    SIZE_UNKNOWN = "size_unknown"


class Cheaper(StrEnum):
    BASE = "base"
    OTHER = "other"
    EQUAL = "equal"


class CaveatCode(StrEnum):
    """Machine-readable caveats; the API renders their text per locale."""

    RETAILER_PARTIAL = "retailer_partial"
    EARLY_EXCLUDED = "early_excluded"
    LAUNCHES_WITHHELD = "launches_withheld"
    REMOVED_UNCONFIRMED = "removed_unconfirmed"
    NOT_OBSERVED_EXCLUDED = "not_observed_excluded"
    HISTORY_OFF = "history_off"
    RATING_SCALE_MIXED = "rating_scale_mixed"
    #: Counted pairs with equal measures but different published size labels (ADR-0008 §1).
    SIZE_LABELS_DIFFER = "size_labels_differ"
    #: The two sides of a comparison sell through different channels (ADR-0008 §2).
    CHANNEL_DIFFERS = "channel_differs"
    #: More distinct label pairs than ``LABEL_CAVEAT_CAP``: the totals, emitted first, so a
    #: client that shows only the first caveats never drops them.
    SIZE_LABELS_DIFFER_TOTAL = "size_labels_differ_total"


class Caveat(ContractModel):
    code: CaveatCode
    params: dict[str, str]


class Cohort(ContractModel):
    description: str
    n: int


class Metric[T](ContractModel):
    """One metric answer. ``data`` is always present; withheld parts inside it are ``None``."""

    status: Status
    data: T
    reason: Reason | None = None
    cohort: Cohort | None = None
    caveats: tuple[Caveat, ...] = ()
    as_of: date


class ProductFilter(ContractModel):
    """Optional narrowing; matching is case-insensitive. Empty means everything."""

    ids: tuple[str, ...] = ()
    brands: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()

    def matches(self, product: Product | ProductV3) -> bool:
        if self.ids and product.id not in self.ids:
            return False
        if self.brands and product.brand.casefold() not in {b.casefold() for b in self.brands}:
            return False
        if self.categories:
            wanted = {c.casefold() for c in self.categories}
            return any(level.casefold() in wanted for level in product.category)
        return True


EVERYTHING = ProductFilter()
