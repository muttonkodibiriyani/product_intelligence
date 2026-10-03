"""``pi.matches/v1``: match edges between per-source files, keyed by stable listing ids (ADR-0012).

The file holds no products, offers or prices: only listing fingerprints, every scored candidate
pair, the human decisions, and the edges and review queue derived from them. Pairs are ordered
``a < b`` by ``(retailer, token)``. Reviewer identities are never stored (SEC-06).
"""

from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from pi_core.base import PiModel
from pi_core.enums import MatchClass, ReviewState
from pi_match.model import Bucket

SCHEMA: Final = "pi.matches/v1"


class MatchModel(PiModel):
    """camelCase on the wire, like the dataset contract."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ListingRef(MatchModel):
    """One retailer's listing: the exporter's group token, built from the retailer's own id."""

    retailer: str = Field(min_length=1)
    token: str = Field(min_length=1)

    def key(self) -> tuple[str, str]:
        return (self.retailer, self.token)


class PairModel(MatchModel):
    a: ListingRef
    b: ListingRef

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.a.retailer == self.b.retailer:
            msg = f"a pair needs two retailers, got {self.a.retailer} twice"
            raise ValueError(msg)
        if self.a.key() >= self.b.key():
            msg = f"pair must be ordered a < b, got {self.a.key()}, {self.b.key()}"
            raise ValueError(msg)
        return self

    def pair(self) -> tuple[tuple[str, str], tuple[str, str]]:
        return (self.a.key(), self.b.key())


class Candidate(PairModel):
    """A scored same-brand pair and the fingerprints it was scored on (reused while they hold)."""

    fingerprint_a: str
    fingerprint_b: str
    bucket: Bucket
    score: Decimal
    reasons: tuple[str, ...]


class Verdict(StrEnum):
    APPROVE = "approve"
    LOCK = "lock"
    REJECT = "reject"


class Decision(PairModel):
    """A human review decision. It outlives model and threshold changes (MAT-05, MAT-07)."""

    verdict: Verdict
    match_class: MatchClass = MatchClass.EXACT


class Edge(PairModel):
    """An edge compose may use. Only edges are evidence of identity; nothing is transitive."""

    match_class: MatchClass
    review_state: ReviewState
    decided_by: Literal["human", "auto"] | None
    confidence: Decimal | None
    method: str
    reasons: tuple[str, ...]

    @model_validator(mode="after")
    def _decided(self) -> Self:
        if (self.review_state is ReviewState.PROPOSED) != (self.decided_by is None):
            msg = "decided_by is required exactly when review_state is not proposed"
            raise ValueError(msg)
        if self.review_state is ReviewState.REJECTED:
            msg = "a rejected pair is a decision, never an edge"
            raise ValueError(msg)
        return self


class ReviewReason(StrEnum):
    """Why a candidate is queued for review instead of being an edge."""

    PROBABLE = "probable"  # below the exact score, or a concentration known on one side only
    ONE_TO_ONE = "one_to_one_conflict"  # a better exact pair already holds one of the listings
    FAMILY_WEAK = "family_weak"  # a size or shade differs and the name is not strong
    GTIN_CONFLICT = "gtin_conflict"  # equal GTINs, but a rule disagrees
    LOW = "low_score"
    NOT_CLIQUE = "edge_not_clique"  # joining would group listings without their own exact edges


class ReviewItem(PairModel):
    reason: ReviewReason
    bucket: Bucket
    score: Decimal
    reasons: tuple[str, ...]


class MatchFile(MatchModel):
    schema_id: Literal["pi.matches/v1"] = Field(alias="schema")
    scope: str = Field(min_length=1)
    vertical: str = Field(min_length=1)
    algo_version: str = Field(min_length=1)
    #: A recorded input of the run, never read from a clock.
    generated_at: str = Field(min_length=1)
    #: Categories whose exact edges are auto-approved (gold-set Wilson lower bound >= 98%).
    auto_accept: tuple[str, ...] = ()
    #: retailer -> token -> fingerprint of the features the score depends on.
    listings: dict[str, dict[str, str]]
    #: retailer -> offers that have no readable token (never guessed).
    unkeyed: dict[str, int]
    candidates: tuple[Candidate, ...]
    decisions: tuple[Decision, ...]
    edges: tuple[Edge, ...]
    review: tuple[ReviewItem, ...]
