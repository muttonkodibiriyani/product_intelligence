"""First-pass product matching (blueprint §8, demo stage). See ``pi_match.match``."""

from pi_match.match import brand_overlap, match, name_score, prepare, score_pair, without_aggregates
from pi_match.model import BrandOverlap, Bucket, MatchPair, ProductRecord, UnitPrice

__all__ = [
    "BrandOverlap",
    "Bucket",
    "MatchPair",
    "ProductRecord",
    "UnitPrice",
    "brand_overlap",
    "match",
    "name_score",
    "prepare",
    "score_pair",
    "without_aggregates",
]
