"""Metric rules over ``pi.dataset/v2`` (service-layer design §7).

Every function takes a validated ``Dataset`` plus typed filters, does no I/O, and returns a
``Metric``: status, data (always present; withheld parts are ``None``), the ``not_enough_data``
reason, the cohort and caveats. The API assembles its envelope from that mechanically.
"""

from pi_metrics.assortment import AssortmentGaps, GapLabel, assortment_gaps
from pi_metrics.availability import Availability, availability
from pi_metrics.compare import (
    GAP_CONVENTION,
    Comparison,
    GroupBy,
    PairRow,
    compare,
    gap,
    pair_row,
)
from pi_metrics.coverage import Coverage, coverage
from pi_metrics.gated import Gated, ModelId, gated
from pi_metrics.index import INDEX_DEFINITION, PriceIndex, price_index
from pi_metrics.launches import Launches, launches
from pi_metrics.model import (
    COUNTED_STATES,
    EVERYTHING,
    METRIC_VERSION,
    MIN_COHORT,
    Caveat,
    CaveatCode,
    Cheaper,
    Cohort,
    Excluded,
    Metric,
    ProductFilter,
    Reason,
    Status,
)
from pi_metrics.pricing import (
    RULE_LABEL,
    Band,
    Guardrails,
    PricePosition,
    PriceSuggestion,
    price_position,
    price_suggestion,
)
from pi_metrics.promotions import Promotions, promotions
from pi_metrics.reviews import ReviewsSummary, reviews_summary
from pi_metrics.summary import Summary, summary
from pi_metrics.view import AmbiguousContext, UnknownInput

__all__ = [
    "COUNTED_STATES",
    "EVERYTHING",
    "GAP_CONVENTION",
    "INDEX_DEFINITION",
    "METRIC_VERSION",
    "MIN_COHORT",
    "RULE_LABEL",
    "AmbiguousContext",
    "AssortmentGaps",
    "Availability",
    "Band",
    "Caveat",
    "CaveatCode",
    "Cheaper",
    "Cohort",
    "Comparison",
    "Coverage",
    "Excluded",
    "GapLabel",
    "Gated",
    "GroupBy",
    "Guardrails",
    "Launches",
    "Metric",
    "ModelId",
    "PairRow",
    "PriceIndex",
    "PricePosition",
    "PriceSuggestion",
    "ProductFilter",
    "Promotions",
    "Reason",
    "ReviewsSummary",
    "Status",
    "Summary",
    "UnknownInput",
    "assortment_gaps",
    "availability",
    "compare",
    "coverage",
    "gap",
    "gated",
    "launches",
    "pair_row",
    "price_index",
    "price_position",
    "price_suggestion",
    "promotions",
    "reviews_summary",
    "summary",
]
