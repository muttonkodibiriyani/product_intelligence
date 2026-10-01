"""Metric endpoints (design §6, S3): query models and the views ``pi_metrics`` doesn't own.

Every number comes from ``pi_metrics``; this module only validates input, maps it to the metric
call and pages the match list. Retailer pairs are ``retailers=<base>,<other>`` (one parameter,
order significant); N-retailer endpoints repeat ``retailer``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from pi_api.catalog import (
    MAX_LIMIT,
    DecimalText,
    InvalidQueryError,
    ScopeQuery,
    Values,
    decode_cursor,
    encode_cursor,
    filters_digest,
    fold,
)
from pi_api.wire import SourceText
from pi_core import MatchClass, ReviewState
from pi_dataset import ContractModel, Dataset
from pi_dataset.models import DecidedBy
from pi_metrics import COUNTED_STATES, GroupBy, Metric, ProductFilter, Status

RetailerId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")]
RetailerIds = Annotated[tuple[RetailerId, ...], Field(max_length=25)]
#: ``<base>,<other>``: source keys can't contain commas (design §5, query encoding).
RetailerPair = Annotated[
    str,
    Field(
        pattern=r"^[a-z][a-z0-9_]{1,62},[a-z][a-z0-9_]{1,62}$",
        description="Ordered pair <base>,<other>; the first is the base.",
    ),
]


class FilterQuery(ScopeQuery):
    brand: Values = ()
    category: Values = ()

    def where(self) -> ProductFilter:
        return ProductFilter(brands=self.brand, categories=self.category)


class PairQuery(FilterQuery):
    retailers: RetailerPair

    def pair(self) -> tuple[str, str]:
        base, other = self.retailers.split(",")
        return base, other


class CompareQuery(PairQuery):
    id: Values = ()
    on: date | None = Field(default=None, alias="date")
    group_by: GroupBy | None = None

    def where(self) -> ProductFilter:
        return ProductFilter(ids=self.id, brands=self.brand, categories=self.category)


class IndexQuery(PairQuery):
    start: date | None = Field(default=None, alias="from")
    end: date | None = Field(default=None, alias="to")


class RetailersQuery(FilterQuery):
    retailer: RetailerIds = ()


class PromotionsQuery(RetailersQuery):
    min_pct: DecimalText | None = None
    on: date | None = Field(default=None, alias="date")

    def min_depth(self) -> Decimal | None:
        return None if self.min_pct is None else Decimal(self.min_pct)


class AvailabilityQuery(RetailersQuery):
    on: date | None = Field(default=None, alias="date")


class LaunchesQuery(RetailersQuery):
    since: date | None = None


class ReviewsQuery(RetailersQuery):
    id: Values = ()

    def where(self) -> ProductFilter:
        return ProductFilter(ids=self.id, brands=self.brand, categories=self.category)


class AssortmentQuery(FilterQuery):
    missing_at: RetailerId
    present_at: RetailerId
    on: date | None = Field(default=None, alias="date")


# ---------------------------------------------------------------- matches


class MatchesQuery(ScopeQuery):
    """Viewers see counted states only (approved, locked); admins see every state."""

    retailers: RetailerPair | None = None
    match_class: MatchClass | None = Field(default=None, alias="class")
    review_state: ReviewState | None = None
    brand: Values = ()
    limit: int = Field(default=25, ge=1, le=MAX_LIMIT)
    cursor: Annotated[str, Field(max_length=512)] | None = None


class MatchRow(ContractModel):
    product_id: str
    brand: SourceText
    name: SourceText
    a: str
    b: str
    match_class: MatchClass
    review_state: ReviewState
    decided_by: DecidedBy | None
    confidence: str | None
    method: SourceText
    stage: SourceText


class MatchPage(ContractModel):
    total: int
    next_cursor: str | None
    items: tuple[MatchRow, ...]


class StatesForbiddenError(Exception):
    """A viewer asked for review states only admins may list (403)."""


def matches(ds: Dataset, generation: str, query: MatchesQuery, *, admin: bool) -> Metric[MatchPage]:
    """Match edges in a stable order (product id, a, b), paged with a generation-bound cursor."""
    if not admin and query.review_state is not None and query.review_state not in COUNTED_STATES:
        raise StatesForbiddenError
    known = {r.id for r in ds.meta.retailers}
    pair: tuple[str, str] | None = None
    if query.retailers is not None:
        first, second = query.retailers.split(",")
        unknown = sorted({first, second} - known)
        if unknown:
            msg = f"unknown retailer {unknown[0]!r}"
            raise InvalidQueryError(msg)
        if first == second:
            msg = "retailers must be two different retailers"
            raise InvalidQueryError(msg)
        low, high = sorted((first, second))
        pair = (low, high)
    brands = {fold(b) for b in query.brand}
    rows = [
        MatchRow(
            product_id=p.id,
            brand=p.brand,
            name=p.name,
            a=e.a,
            b=e.b,
            match_class=e.match_class,
            review_state=e.review_state,
            decided_by=e.decided_by,
            confidence=e.confidence,
            method=e.method,
            stage=e.stage,
        )
        for p in sorted(ds.products, key=lambda p: p.id)
        if not brands or fold(p.brand) in brands
        for e in sorted(p.matches, key=lambda e: (e.a, e.b))
        if (admin or e.review_state in COUNTED_STATES)
        and (pair is None or (e.a, e.b) == pair)
        and (query.match_class is None or e.match_class is query.match_class)
        and (query.review_state is None or e.review_state is query.review_state)
    ]
    # The role is part of the digest: a viewer's and an admin's pages hold different rows.
    digest = filters_digest(query, extra="admin" if admin else "viewer")
    offset = 0 if query.cursor is None else decode_cursor(query.cursor, generation, digest)
    page = rows[offset : offset + query.limit]
    end = offset + len(page)
    return Metric[MatchPage](
        status=Status.OK,
        data=MatchPage(
            total=len(rows),
            next_cursor=encode_cursor(generation, end, digest) if end < len(rows) else None,
            items=tuple(page),
        ),
        as_of=ds.meta.dates[-1],
    )
