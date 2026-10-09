"""Deterministic product-family projection over accepted, direct match evidence.

The builder reads already-published datasets and optional ``pi.matches/v1`` evidence. It never
changes either input. Proposed edges only create ``ambiguous`` matrix cells; only approved or
locked exact/family edges join retailers. Retailer-owned family ids join that retailer's sizes.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from pi_compare.models import (
    Axis,
    AxisValue,
    CaptureCompleteness,
    CommercialSnapshot,
    ComparisonProjection,
    LaunchBasis,
    LaunchEvidence,
    ListingRef,
    ListingTokenState,
    MatchEvidence,
    ProductFamily,
    ProjectionIssue,
    RetailerFamilyEvidence,
    ValueState,
    VariantIdentityBasis,
    VariantRef,
)
from pi_compare.normalise import discount, normalise_size, normalise_text_axis
from pi_compare.presence import retailer_cell
from pi_core.enums import MatchClass, ReviewState
from pi_dataset import DatasetV3, ProductV3
from pi_dataset.models import MatchEdge
from pi_dataset.v3 import OfferV3
from pi_match.listings import listing_tokens
from pi_match.matchfile import Edge, MatchFile, Verdict
from pi_match.normalise import normalise_brand

ALGORITHM_VERSION = "pi_compare.projection/1"
_ACCEPTED = frozenset({ReviewState.APPROVED, ReviewState.LOCKED})
_FAMILY_CLASSES = frozenset({MatchClass.EXACT, MatchClass.FAMILY})
Key = tuple[str, str]
Pair = tuple[Key, Key]


@dataclass(frozen=True, slots=True)
class _Node:
    key: Key
    product: ProductV3
    contexts: tuple[str, ...]
    offers: tuple[tuple[str, OfferV3], ...]
    token_state: ListingTokenState

    @property
    def listing_key(self) -> str:
        return _listing_key(self.key)

    @property
    def brand_key(self) -> str:
        return normalise_brand(self.product.brand)


class _Groups:
    def __init__(self, keys: Sequence[Key]) -> None:
        self.parent = dict(zip(keys, keys, strict=True))

    def find(self, key: Key) -> Key:
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, left: Key, right: Key) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def build_projection(
    dataset: DatasetV3,
    *,
    generation: str,
    completeness: Mapping[str, CaptureCompleteness],
    match_file: MatchFile | None = None,
) -> ComparisonProjection:
    """Build every family and retailer matrix deterministically from immutable inputs."""
    retailers = tuple(sorted(r.id for r in dataset.meta.retailers))
    missing = sorted(set(retailers) - set(completeness))
    if missing:
        msg = f"capture completeness is required for every retailer: {missing}"
        raise ValueError(msg)
    if match_file is not None and (match_file.scope, match_file.vertical) != (
        dataset.meta.scope,
        dataset.meta.vertical,
    ):
        msg = (
            f"match file {match_file.scope}/{match_file.vertical} is not for "
            f"{dataset.meta.scope}/{dataset.meta.vertical}"
        )
        raise ValueError(msg)

    nodes, by_product, unkeyed = _nodes(dataset)
    groups = _Groups(tuple(nodes))
    issues: list[ProjectionIssue] = []
    retailer_families = _retailer_families(nodes)
    for (retailer, family_id), members in retailer_families.items():
        _union_members(
            groups,
            nodes,
            members,
            issues,
            detail=f"retailer family {retailer}/{family_id}",
        )

    evidence = _in_file_evidence(dataset, by_product, nodes)
    blocked = _blocked_pairs(match_file)
    if match_file is not None:
        evidence.update(_file_evidence(match_file, nodes, issues))
    for pair, item in sorted(evidence.items()):
        if pair in blocked or item.match_class not in _FAMILY_CLASSES:
            continue
        if item.review_state in _ACCEPTED:
            _union_pair(groups, nodes, pair, issues, detail=f"match {item.method}")

    families: dict[Key, list[_Node]] = defaultdict(list)
    for key, node in nodes.items():
        families[groups.find(key)].append(node)
    proposed = _proposed_neighbours(evidence, blocked)
    rows = tuple(
        _family(
            members,
            retailers,
            completeness,
            generation,
            dataset,
            evidence,
            retailer_families,
            proposed,
        )
        for _, members in sorted(families.items())
    )
    return ComparisonProjection(
        generation=generation,
        as_of=dataset.meta.dates[-1],
        families=tuple(sorted(rows, key=lambda family: family.id)),
        issues=tuple(sorted(issues, key=lambda issue: (issue.code, issue.listing_keys))),
        unkeyed_listings=unkeyed,
    )


def _nodes(dataset: DatasetV3) -> tuple[dict[Key, _Node], dict[tuple[str, str], Key], int]:
    retailer_of = {context.id: context.retailer for context in dataset.meta.contexts}
    offered = [
        (product.id, {retailer_of[cid] for cid in product.offers if cid in retailer_of})
        for product in dataset.products
    ]
    tokens = listing_tokens(offered)
    nodes: dict[Key, _Node] = {}
    by_product: dict[tuple[str, str], Key] = {}
    unkeyed = 0
    for product in dataset.products:
        contexts: dict[str, list[tuple[str, OfferV3]]] = defaultdict(list)
        for cid, offer in product.offers.items():
            if cid in retailer_of and not offer.early:
                contexts[retailer_of[cid]].append((cid, offer))
        for retailer, values in sorted(contexts.items()):
            token = tokens.get((product.id, retailer))
            state = ListingTokenState.KEYED
            if token is None:
                token = f"unkeyed:{product.id}:{retailer}"
                state = ListingTokenState.UNKEYED
                unkeyed += 1
            key = (retailer, token)
            if key in nodes:
                msg = f"listing {key} occurs in more than one product"
                raise ValueError(msg)
            values.sort(key=lambda item: item[0])
            nodes[key] = _Node(
                key=key,
                product=product,
                contexts=tuple(cid for cid, _ in values),
                offers=tuple(values),
                token_state=state,
            )
            by_product[(product.id, retailer)] = key
    return nodes, by_product, unkeyed


def _retailer_families(nodes: Mapping[Key, _Node]) -> dict[tuple[str, str], tuple[Key, ...]]:
    found: dict[tuple[str, str], set[Key]] = defaultdict(set)
    for key, node in nodes.items():
        for _, offer in node.offers:
            if offer.content is not None and offer.content.family is not None:
                found[(key[0], offer.content.family)].add(key)
    return {family: tuple(sorted(keys)) for family, keys in sorted(found.items())}


def _union_members(
    groups: _Groups,
    nodes: Mapping[Key, _Node],
    members: Sequence[Key],
    issues: list[ProjectionIssue],
    *,
    detail: str,
) -> None:
    if not members:
        return
    head = members[0]
    for member in members[1:]:
        _union_pair(groups, nodes, _ordered(head, member), issues, detail=detail)


def _union_pair(
    groups: _Groups,
    nodes: Mapping[Key, _Node],
    pair: Pair,
    issues: list[ProjectionIssue],
    *,
    detail: str,
) -> None:
    left, right = pair
    if nodes[left].brand_key != nodes[right].brand_key:
        issues.append(
            ProjectionIssue(
                code="brand_conflict",
                listing_keys=(_listing_key(left), _listing_key(right)),
                detail=detail,
            )
        )
        return
    groups.union(left, right)


def _in_file_evidence(
    dataset: DatasetV3,
    by_product: Mapping[tuple[str, str], Key],
    nodes: Mapping[Key, _Node],
) -> dict[Pair, MatchEvidence]:
    found: dict[Pair, MatchEvidence] = {}
    for product in dataset.products:
        for edge in product.matches:
            a = by_product.get((product.id, edge.a))
            b = by_product.get((product.id, edge.b))
            if a is None or b is None:
                continue
            pair = _ordered(a, b)
            found[pair] = _dataset_evidence(edge, pair, nodes)
    return found


def _dataset_evidence(edge: MatchEdge, pair: Pair, nodes: Mapping[Key, _Node]) -> MatchEvidence:
    return MatchEvidence(
        left_listing_key=nodes[pair[0]].listing_key,
        right_listing_key=nodes[pair[1]].listing_key,
        match_class=edge.match_class,
        review_state=edge.review_state,
        confidence=edge.confidence,
        method=f"{edge.method}:{edge.stage}",
        reasons=(),
        left_fingerprint=None,
        right_fingerprint=None,
    )


def _blocked_pairs(match_file: MatchFile | None) -> frozenset[Pair]:
    if match_file is None:
        return frozenset()
    return frozenset(
        decision.pair() for decision in match_file.decisions if decision.verdict is Verdict.REJECT
    )


def _file_evidence(
    match_file: MatchFile,
    nodes: Mapping[Key, _Node],
    issues: list[ProjectionIssue],
) -> dict[Pair, MatchEvidence]:
    found: dict[Pair, MatchEvidence] = {}
    for edge in match_file.edges:
        pair = edge.pair()
        missing = tuple(_listing_key(key) for key in pair if key not in nodes)
        if missing:
            issues.append(
                ProjectionIssue(
                    code="edge_listing_absent",
                    listing_keys=missing,
                    detail=f"{edge.method} edge is outside the loaded dataset",
                )
            )
            continue
        found[pair] = _match_file_evidence(edge, match_file, nodes)
    for decision in match_file.decisions:
        if decision.verdict is not Verdict.REJECT:
            continue
        pair = decision.pair()
        if any(key not in nodes for key in pair):
            continue
        found[pair] = MatchEvidence(
            left_listing_key=nodes[pair[0]].listing_key,
            right_listing_key=nodes[pair[1]].listing_key,
            match_class=decision.match_class,
            review_state=ReviewState.REJECTED,
            confidence=None,
            method=match_file.algo_version,
            reasons=("human_decision",),
            left_fingerprint=match_file.listings.get(pair[0][0], {}).get(pair[0][1]),
            right_fingerprint=match_file.listings.get(pair[1][0], {}).get(pair[1][1]),
        )
    return found


def _match_file_evidence(
    edge: Edge, match_file: MatchFile, nodes: Mapping[Key, _Node]
) -> MatchEvidence:
    pair = edge.pair()
    return MatchEvidence(
        left_listing_key=nodes[pair[0]].listing_key,
        right_listing_key=nodes[pair[1]].listing_key,
        match_class=edge.match_class,
        review_state=edge.review_state,
        confidence=None if edge.confidence is None else _confidence(edge.confidence),
        method=edge.method,
        reasons=edge.reasons,
        left_fingerprint=match_file.listings.get(pair[0][0], {}).get(pair[0][1]),
        right_fingerprint=match_file.listings.get(pair[1][0], {}).get(pair[1][1]),
    )


def _confidence(value: Decimal) -> str:
    return format(value, "f")


def _proposed_neighbours(
    evidence: Mapping[Pair, MatchEvidence], blocked: frozenset[Pair]
) -> dict[Key, set[Key]]:
    found: dict[Key, set[Key]] = defaultdict(set)
    for pair, item in evidence.items():
        if (
            pair not in blocked
            and item.match_class in _FAMILY_CLASSES
            and item.review_state is ReviewState.PROPOSED
        ):
            found[pair[0]].add(pair[1])
            found[pair[1]].add(pair[0])
    return found


def _family(  # noqa: PLR0913, PLR0917 - immutable inputs to one projection row
    members: Sequence[_Node],
    retailers: Sequence[str],
    completeness: Mapping[str, CaptureCompleteness],
    generation: str,
    dataset: DatasetV3,
    evidence: Mapping[Pair, MatchEvidence],
    retailer_families: Mapping[tuple[str, str], tuple[Key, ...]],
    proposed: Mapping[Key, set[Key]],
) -> ProductFamily:
    ordered = tuple(sorted(members, key=lambda node: node.key))
    member_keys = {node.key for node in ordered}
    head = ordered[0]
    matrix = []
    for retailer in retailers:
        accepted = tuple(node.key[1] for node in ordered if node.key[0] == retailer)
        ambiguous = tuple(
            sorted(
                {
                    other[1]
                    for key in member_keys
                    for other in proposed.get(key, set())
                    if other[0] == retailer and other not in member_keys
                }
            )
        )
        coverage = completeness[retailer]
        matrix.append(
            retailer_cell(
                retailer=retailer,
                as_of=dataset.meta.dates[-1],
                generation=generation,
                accepted_tokens=accepted,
                ambiguous_tokens=ambiguous,
                complete_capture=coverage.complete,
                completeness_basis=coverage.basis,
            )
        )
    direct = tuple(
        item
        for pair, item in sorted(evidence.items())
        if pair[0] in member_keys and pair[1] in member_keys
    )
    suggestions = tuple(
        item
        for pair, item in sorted(evidence.items())
        if item.review_state is ReviewState.PROPOSED
        and ((pair[0] in member_keys) != (pair[1] in member_keys))
    )
    exclusions = tuple(
        item
        for pair, item in sorted(evidence.items())
        if item.review_state is ReviewState.REJECTED
        and ((pair[0] in member_keys) != (pair[1] in member_keys))
    )
    owned = tuple(
        RetailerFamilyEvidence(
            retailer=retailer,
            retailer_family_id=family_id,
            listing_keys=tuple(_listing_key(key) for key in keys if key in member_keys),
        )
        for (retailer, family_id), keys in retailer_families.items()
        if len([key for key in keys if key in member_keys]) > 1
    )
    return ProductFamily(
        id=_family_id(member_keys),
        brand_key=head.brand_key,
        name=head.product.name,
        category=head.product.category,
        listings=tuple(_listing(node, dataset) for node in ordered),
        matrix=tuple(matrix),
        evidence=direct,
        suggestions=suggestions,
        exclusions=exclusions,
        retailer_family_evidence=owned,
    )


def _listing(node: _Node, dataset: DatasetV3) -> ListingRef:
    return ListingRef(
        retailer=node.key[0],
        contexts=node.contexts,
        token=node.key[1],
        token_state=node.token_state,
        source_product_id=node.product.id,
        variants=_variants(node),
        commercial=tuple(_commercial(cid, offer, dataset) for cid, offer in node.offers),
    )


@dataclass(slots=True)
class _Variant:
    basis: VariantIdentityBasis
    contexts: set[str]
    gtins: set[str]
    axes: dict[str, AxisValue]


def _variants(node: _Node) -> tuple[VariantRef, ...]:
    found: dict[str, _Variant] = {}
    for cid, offer in node.offers:
        content = offer.content
        if content is not None and content.variants:
            for item in content.variants:
                variant = found.setdefault(
                    item.sku,
                    _Variant(VariantIdentityBasis.CONTENT_VARIANT, set(), set(), {}),
                )
                variant.contexts.add(cid)
                if item.gtin is not None:
                    variant.gtins.add(item.gtin)
                _add_axis(variant, normalise_size(offer.size))
                if item.shade is not None:
                    _add_axis(
                        variant,
                        normalise_text_axis(item.shade, Axis.SHADE, field="content.variants.shade"),
                    )
        else:
            sku = offer.sku or node.key[1]
            basis = (
                VariantIdentityBasis.OFFER_SKU
                if offer.sku is not None
                else VariantIdentityBasis.LISTING_TOKEN
            )
            variant = found.setdefault(sku, _Variant(basis, set(), set(), {}))
            variant.contexts.add(cid)
            _add_axis(variant, normalise_size(offer.size))
    return tuple(
        VariantRef(
            key=f"{node.listing_key}:{sku}",
            retailer_sku=sku,
            identity_basis=item.basis,
            contexts=tuple(sorted(item.contexts)),
            gtins=tuple(sorted(item.gtins)),
            axes=tuple(item.axes[key] for key in sorted(item.axes)),
        )
        for sku, item in sorted(found.items())
    )


def _add_axis(variant: _Variant, axis: AxisValue) -> None:
    dumped = axis.model_dump(mode="json", by_alias=True)
    variant.axes[json.dumps(dumped, sort_keys=True, separators=(",", ":"))] = axis


def _commercial(context: str, offer: OfferV3, dataset: DatasetV3) -> CommercialSnapshot:
    current = offer.series.price[-1]
    regular = None if offer.series.regular is None else offer.series.regular[-1]
    available = None if offer.series.availability is None else offer.series.availability[-1]
    reason = None if offer.not_observed_reason is None else offer.not_observed_reason.value
    if reason is not None:
        availability_state = ValueState.NOT_OBSERVED
        available = None
    elif available is None:
        availability_state = ValueState.UNKNOWN
    else:
        availability_state = ValueState.OBSERVED if available.is_known else ValueState.UNKNOWN
    first = next(
        (
            dataset.meta.dates[index]
            for index in range(len(dataset.meta.dates))
            if offer.series.price[index] is not None
            or (offer.series.regular is not None and offer.series.regular[index] is not None)
            or (
                offer.series.availability is not None
                and offer.series.availability[index] is not None
            )
        ),
        None,
    )
    launch = LaunchEvidence(
        state=ValueState.OBSERVED
        if first is not None
        else ValueState.NOT_OBSERVED
        if reason is not None
        else ValueState.UNKNOWN,
        observed_on=first,
        basis=LaunchBasis.FIRST_OBSERVED if first is not None else None,
    )
    return CommercialSnapshot(
        context=context,
        current=current,
        regular=regular,
        discount=discount(current, regular),
        availability=available,
        availability_state=availability_state,
        launch=launch,
        captured_at=offer.evidence.captured_at,
        not_observed_reason=reason,
    )


def _ordered(left: Key, right: Key) -> Pair:
    return (left, right) if left < right else (right, left)


def _listing_key(key: Key) -> str:
    return f"{key[0]}:{key[1]}"


def _family_id(keys: set[Key]) -> str:
    raw = json.dumps([ALGORITHM_VERSION, sorted(keys)], separators=(",", ":"))
    return "fam-" + hashlib.sha256(raw.encode()).hexdigest()[:24]
