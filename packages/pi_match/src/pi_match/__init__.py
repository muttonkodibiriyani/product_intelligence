"""First-pass product matching (blueprint §8, demo stage). See ``pi_match.match``."""

from pi_match.match import brand_overlap, match, name_score, prepare, score_pair, without_aggregates
from pi_match.model import BrandOverlap, Bucket, MatchPair, ProductRecord, UnitPrice
from pi_match.unit_price import BasePrice, Basis, derive_unit_price, price_per_base

__all__ = [
    "BasePrice",
    "Basis",
    "BrandOverlap",
    "Bucket",
    "MatchPair",
    "ProductRecord",
    "UnitPrice",
    "brand_overlap",
    "derive_unit_price",
    "match",
    "name_score",
    "prepare",
    "price_per_base",
    "score_pair",
    "without_aggregates",
]
