"""A ``pi.matches/v1`` file applied to a composed view (ADR-0012 §6).

``PI_API_MATCHES`` names one match file; its scope and vertical must be the view's. The file is
only read, and so are the source files: the served view changes, never a file.

* **The file overrides in-file pairs.** A listing pair that an in-file product groups and the
  file rejects, or names with a class other than ``exact``, is split: the product becomes one
  product per retailer, with the ids the exporter gives the listing tokens (``pi_api.ids``
  resolves the old ``m-`` id to them). An in-file pair the file has an exact edge for takes the
  file's state.
* **Only human-accepted exact edges merge.** Exact edges in ``COUNTED_STATES`` (approved,
  locked) whose two listings are both in the view are taken in priority order (locked, approved,
  then confidence, then ids). An edge joins two products only when every two listings of the
  result, one per retailer, have their own accepted exact edge (the clique rule: nothing is
  transitive; an in-file product joins only if its own pair is accepted), and no retailer is in
  both. Otherwise it is skipped and counted
  (``edge_not_clique``, ``edge_conflict``). A ``proposed`` exact edge never merges (counted as
  ``unreviewed``): a product grouped on unreviewed evidence is the pattern the matched switch was
  paused for. Family and substitute edges never merge: products are per size.
* The merged product takes its fields and id from the member with the smallest retailer id
  (ADR-0010's precedence). The other members' ids are returned as aliases of it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from types import MappingProxyType

from pi_api.ids import product_id
from pi_core.enums import MatchClass, ReviewState
from pi_dataset import DatasetV3, ProductV3
from pi_dataset.models import DecidedBy, MatchEdge
from pi_match.listings import listing_tokens
from pi_match.matchfile import Edge, MatchFile, Verdict
from pi_metrics.model import COUNTED_STATES

#: ``MatchEdge.stage`` of an edge taken from a match file.
STAGE = "pi.matches/v1"
_STATE_RANK = {ReviewState.LOCKED: 0, ReviewState.APPROVED: 1, ReviewState.PROPOSED: 2}

Key = tuple[str, str]  # (retailer, token)
Pair = tuple[Key, Key]  # ordered a < b


class MatchFileError(ValueError):
    """The match file does not belong to this view."""


@dataclass(frozen=True)
class Applied:
    dataset: DatasetV3
    #: A merged member's old id -> the id of the product that holds it now.
    aliases: Mapping[str, str]
    #: In-file products split because the file rejects a pair they grouped.
    split: tuple[str, ...]
    #: ``merged`` (edges that joined products), ``edge_not_clique``, ``edge_conflict``,
    #: ``absent`` (an edge with a listing outside the view) and ``unreviewed`` (a proposed exact
    #: edge, which never merges).
    counts: Mapping[str, int]


def apply(ds: DatasetV3, file: MatchFile) -> Applied:
    """``ds`` with ``file``'s edges applied; see the module docstring for the rules."""
    if (file.scope, file.vertical) != (ds.meta.scope, ds.meta.vertical):
        msg = (
            f"match file {file.scope}/{file.vertical} is not for view "
            f"{ds.meta.scope}/{ds.meta.vertical}"
        )
        raise MatchFileError(msg)
    retailer_of = {c.id: c.retailer for c in ds.meta.contexts}
    tokens = listing_tokens([(p.id, {retailer_of[c] for c in p.offers}) for p in ds.products])
    exact = {e.pair(): e for e in file.edges if e.match_class is MatchClass.EXACT}
    rejected = {d.pair() for d in file.decisions if d.verdict is Verdict.REJECT}
    #: Pairs the file holds as another class: a family or substitute is never one product.
    other = {e.pair() for e in file.edges if e.match_class is not MatchClass.EXACT} | {
        d.pair()
        for d in file.decisions
        if d.verdict is not Verdict.REJECT and d.match_class is not MatchClass.EXACT
    }

    groups, split = _groups(ds, tokens, retailer_of, rejected | other)
    counts = _merge(groups, exact, rejected)

    products: list[ProductV3] = []
    aliases: dict[str, str] = {}
    for members, keys in groups:
        if not members:
            continue
        members.sort(key=lambda m: min(retailer_of[c] for c in m.offers))
        head = members[0]
        for m in members[1:]:
            aliases[m.id] = head.id
        products.append(_joined(head, members, keys, exact, file.algo_version))
    dataset = ds.model_copy(update={"products": tuple(products)})
    return Applied(
        dataset=dataset,
        aliases=MappingProxyType(aliases),
        split=tuple(split),
        counts=MappingProxyType({k: n for k, n in sorted(counts.items()) if n}),
    )


Group = tuple[list[ProductV3], dict[str, str]]  # products, and their listings by retailer


def _groups(
    ds: DatasetV3,
    tokens: Mapping[tuple[str, str], str],
    retailer_of: Mapping[str, str],
    apart: set[Pair],
) -> tuple[list[Group], list[str]]:
    """Each product as a group of its listings; an in-file grouping of a pair in ``apart`` is
    split into one product per retailer."""
    groups: list[Group] = []
    split: list[str] = []
    for p in ds.products:
        retailers = {retailer_of[c] for c in p.offers}
        keys = {r: tokens[(p.id, r)] for r in retailers if (p.id, r) in tokens}
        if len(keys) == len(retailers) > 1 and any(q in apart for q in _pairs(keys)):
            split.append(p.id)
            for r, token in sorted(keys.items()):
                offers = {c: o for c, o in p.offers.items() if retailer_of[c] == r}
                update = {"id": product_id(token), "offers": offers, "matches": ()}
                groups.append(([p.model_copy(update=update)], {r: token}))
            continue
        groups.append(([p], keys))
    return groups, split


def _merge(groups: list[Group], exact: Mapping[Pair, Edge], rejected: set[Pair]) -> Counter[str]:
    """Joins groups along accepted ``exact`` edges in priority order. Every pair of the result
    must be accepted exact evidence, including the pairs an in-file product already groups."""
    accepted = {q: e for q, e in exact.items() if e.review_state in COUNTED_STATES}
    evidence = set(accepted) | {
        q
        for products, keys in groups
        for q in _pairs(keys)
        if q not in rejected and q not in exact and _in_file_exact(products[0], q)
    }
    at: dict[Key, int] = {(r, t): i for i, (_, keys) in enumerate(groups) for r, t in keys.items()}
    counts: Counter[str] = Counter()
    counts["unreviewed"] = len(exact) - len(accepted)
    for edge in sorted(accepted.values(), key=_priority):
        a, b = edge.pair()
        if a not in at or b not in at:
            counts["absent"] += 1
            continue
        ga, gb = at[a], at[b]
        if ga == gb:
            continue
        left, right = groups[ga][1], groups[gb][1]
        if left.keys() & right.keys():
            counts["edge_conflict"] += 1
        elif not all(q in evidence for q in _pairs({**left, **right})):
            counts["edge_not_clique"] += 1
        else:
            counts["merged"] += 1
            groups[ga][0].extend(groups[gb][0])
            left.update(right)
            groups[gb] = ([], {})
            at.update(dict.fromkeys(right.items(), ga))
    return counts


def _pairs(keys: Mapping[str, str]) -> Iterable[Pair]:
    yield from combinations(sorted(keys.items()), 2)


def _in_file_exact(product: ProductV3, pair: Pair) -> bool:
    (ra, _), (rb, _) = pair
    return any(
        (m.a, m.b) == (ra, rb)
        and m.match_class is MatchClass.EXACT
        and m.review_state in COUNTED_STATES
        for m in product.matches
    )


def _priority(edge: Edge) -> tuple[int, Decimal, Pair]:
    return (_STATE_RANK[edge.review_state], -(edge.confidence or Decimal(0)), edge.pair())


def _joined(
    head: ProductV3,
    members: list[ProductV3],
    keys: Mapping[str, str],
    exact: Mapping[Pair, Edge],
    method: str,
) -> ProductV3:
    """The members as one product: ``head``'s fields, every offer, and the edges between them
    (the file's exact edge wins over an in-file one for the same retailers)."""
    taken = {(q[0][0], q[1][0]): _match_edge(exact[q], method) for q in _pairs(keys) if q in exact}
    if len(members) == 1 and not taken:
        return head
    edges = {**{(m.a, m.b): m for p in members for m in p.matches}, **taken}
    offers = {c: o for p in members for c, o in p.offers.items()}
    return head.model_copy(
        update={"offers": offers, "matches": tuple(sorted(edges.values(), key=_ab))}
    )


def _ab(edge: MatchEdge) -> tuple[str, str]:
    return (edge.a, edge.b)


def _match_edge(edge: Edge, method: str) -> MatchEdge:
    return MatchEdge(
        a=edge.a.retailer,
        b=edge.b.retailer,
        match_class=edge.match_class,
        review_state=edge.review_state,
        decided_by=None if edge.decided_by is None else DecidedBy(edge.decided_by),
        confidence=None if edge.confidence is None else f"{edge.confidence:f}",
        method=edge.method or method,
        stage=STAGE,
    )
