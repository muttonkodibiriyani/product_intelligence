"""Incremental three-retailer matching into a ``pi.matches/v1`` file (ADR-0012).

A run takes every retailer's listings, the previous match file and new human decisions, and
returns the next match file. Pure: the same inputs give an equal file.

1. **Fingerprints.** Each listing's fingerprint covers every feature ``score_pair`` reads (brand
   key, name tokens, size, shade, concentration, kind, GTIN). A previous candidate is reused when
   both fingerprints are unchanged and ``algo_version`` is the same. Every other same-brand pair
   that touches a new or changed listing is scored again. Every scored pair is kept, and the
   assignment below re-runs over all of them, so an incremental run equals a full one.
2. **Decisions** are human and persist. ``reject`` is a hard negative: the pair never becomes an
   edge or a review item again. ``approve`` and ``lock`` make an edge with ``decided_by=human``.
   An exact approval that breaks a hard rule (:func:`hard_conflicts`) is refused. A decision
   records the listings' fingerprints; every run re-checks it, and an approval whose listing has
   changed, or which now breaks a hard rule, is not an edge but a review item until a human
   decides again.
3. **Edges, accuracy first.** One exact edge per listing and other retailer, best first (bucket,
   score, then ids). Machine edges are ``proposed``: ``auto_accept`` is refused until the
   gold-set gate of ADR-0012 §8 exists. A size or shade
   difference under a strong name is a ``family`` edge, which is not one-to-one. Everything else
   goes to the review queue, never an edge. Nothing is transitive: an edge names one pair.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations

from pi_core.enums import MatchClass, ReviewState
from pi_match.match import (
    EXACT_MIN,
    Prepared,
    concentration_relation,
    prepare,
    related_pair,
    rule_conflicts,
    score_pair,
)
from pi_match.matchfile import (
    SCHEMA,
    Candidate,
    Decision,
    Edge,
    ListingRef,
    MatchFile,
    ReviewItem,
    ReviewReason,
    Verdict,
)
from pi_match.model import Bucket, ProductRecord

#: Bump on any change to scoring, rules or assignment: every pair without a human decision is
#: re-scored, and the gold-set gate re-runs.
ALGO_VERSION = "pi_match.incremental/2"

Key = tuple[str, str]  # (retailer, token)
Pair = tuple[Key, Key]
_RANK = {Bucket.EXACT: 0, Bucket.PROBABLE: 1, Bucket.CANDIDATE: 2}


class DecisionError(ValueError):
    """A decision names an unknown listing or would override a hard rule."""


def fingerprint(item: Prepared) -> str:
    """A short digest of the features the score depends on (and nothing else)."""
    size = None if item.size is None else [str(item.size.amount), item.size.unit]
    shade = None if item.shade is None else [item.shade.code, item.shade.name]
    features = [
        item.brand_key,
        sorted(item.tokens),
        size,
        shade,
        None if item.concentration is None else item.concentration.value,
        item.kind.value,
        item.gtin,
        None if item.form is None else item.form.value,
        list(item.flags),
        item.concentration_from_url,
        sorted(item.numbers),
    ]
    raw = json.dumps(features, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def hard_conflicts(left: Prepared, right: Prepared) -> tuple[str, ...]:
    """Rules no score, model or reviewer may override for an exact pair (blueprint §8.4)."""
    out: list[str] = []
    if left.brand_key != right.brand_key:
        out.append("brand_differs")
    if left.gtin is not None and right.gtin is not None and left.gtin != right.gtin:
        out.append("gtin_differs")
    out.extend(rule_conflicts(left, right))
    if left.size is not None and right.size is not None and not left.size.same_as(right.size):
        out.append("size_differs")
    if _shades_differ(left, right):
        out.append("shade_differs")
    return tuple(out)


def _shades_differ(left: Prepared, right: Prepared) -> bool:
    """Codes decide when both sides have one; otherwise both names must be stated and differ."""
    ls, rs = left.shade, right.shade
    if ls is None or rs is None:
        return False
    if ls.code is not None and rs.code is not None:
        return ls.code != rs.code
    return bool(ls.name and rs.name and ls.name != rs.name)


def _ref(key: Key) -> ListingRef:
    return ListingRef(retailer=key[0], token=key[1])


def _ordered(x: Key, y: Key) -> Pair:
    return (x, y) if x < y else (y, x)


def _prepare_all(
    listings: Mapping[str, Sequence[ProductRecord]],
) -> dict[Key, Prepared]:
    prepared: dict[Key, Prepared] = {}
    for retailer, records in listings.items():
        for record in records:
            if record.aggregate:
                continue
            if record.source != retailer:
                msg = f"listing {record.source_key} is {record.source}, given as {retailer}"
                raise ValueError(msg)
            key = (retailer, record.source_key)
            if key in prepared:
                msg = f"listing {key} given twice"
                raise ValueError(msg)
            prepared[key] = prepare(record)
    return prepared


def _score(prepared: Mapping[Key, Prepared], pairs: Iterable[Pair]) -> list[Candidate]:
    out: list[Candidate] = []
    fp = {k: fingerprint(p) for k, p in prepared.items()}
    for a, b in pairs:
        result = score_pair(prepared[a], prepared[b])  # always a < b: the score's orientation
        if result is None:
            related = related_pair(prepared[a], prepared[b])
            if related is None:
                continue
            result = (Bucket.CANDIDATE, *related)
        bucket, score, reasons = result
        out.append(
            Candidate(
                a=_ref(a),
                b=_ref(b),
                fingerprint_a=fp[a],
                fingerprint_b=fp[b],
                bucket=bucket,
                score=score,
                reasons=reasons,
            )
        )
    return out


def _pairs_to_score(prepared: Mapping[Key, Prepared], dirty: set[Key]) -> list[Pair]:
    """Same-brand pairs of two retailers with at least one new or changed listing."""
    blocks: dict[str, dict[str, list[Key]]] = defaultdict(lambda: defaultdict(list))
    for key, item in prepared.items():
        blocks[item.brand_key][key[0]].append(key)
    pairs: list[Pair] = []
    for by_retailer in blocks.values():
        for ra, rb in combinations(sorted(by_retailer), 2):
            for a in by_retailer[ra]:
                for b in by_retailer[rb]:
                    if a in dirty or b in dirty:
                        pairs.append(_ordered(a, b))
    return pairs


def _merge_decisions(
    old: Iterable[Decision],
    new: Iterable[Decision],
    prepared: Mapping[Key, Prepared],
    fps: Mapping[Key, str],
) -> dict[Pair, Decision]:
    """Old decisions, then new ones (a later decision on a pair replaces the earlier one).

    A new decision is stamped with the listings' current fingerprints unless it carries its own.
    """
    merged = {d.pair(): d for d in old}
    for d in new:
        a, b = d.pair()
        missing = [k for k in (a, b) if k not in prepared]
        if missing:
            msg = f"decision on {d.pair()} names listings not in this run: {missing}"
            raise DecisionError(msg)
        if d.verdict is not Verdict.REJECT and d.match_class is MatchClass.EXACT:
            conflicts = hard_conflicts(prepared[a], prepared[b])
            if conflicts:
                msg = f"exact {d.verdict.value} of {d.pair()} breaks hard rules: {conflicts}"
                raise DecisionError(msg)
        stamped = d
        if d.fingerprint_a is None and d.fingerprint_b is None:
            stamped = d.model_copy(update={"fingerprint_a": fps[a], "fingerprint_b": fps[b]})
        merged[d.pair()] = stamped
    return merged


def _decision_problem(
    d: Decision, prepared: Mapping[Key, Prepared], fps: Mapping[Key, str]
) -> ReviewReason | None:
    """Why a persisted approval is not an edge in this run, else None.

    Re-checked every run: the listings under a token can change after a human saw them.
    """
    a, b = d.pair()
    if a not in prepared or b not in prepared:
        return ReviewReason.DECISION_STALE  # a listing is gone: no edge until it returns
    if (d.fingerprint_a, d.fingerprint_b) != (fps[a], fps[b]):
        return ReviewReason.DECISION_STALE
    if d.match_class is MatchClass.EXACT and hard_conflicts(prepared[a], prepared[b]):
        return ReviewReason.DECISION_BREAKS_RULE
    if d.match_class is MatchClass.FAMILY and _family_blocked(prepared, a, b):
        return ReviewReason.DECISION_BREAKS_RULE
    return None


def _category(prepared: Mapping[Key, Prepared], a: Key, b: Key) -> str | None:
    """The pair's category when both listings are present and agree on it."""
    pa, pb = prepared.get(a), prepared.get(b)
    if pa is None or pb is None or pa.record.category != pb.record.category:
        return None
    return pa.record.category


def _assign(  # noqa: PLR0912, PLR0913 -- the class ladder of ADR-0012 §3, one branch per rung
    candidates: Sequence[Candidate],
    decisions: Mapping[Pair, Decision],
    prepared: Mapping[Key, Prepared],
    fps: Mapping[Key, str],
    *,
    algo_version: str,
    auto_accept: frozenset[str],
) -> tuple[list[Edge], list[ReviewItem]]:
    by_pair = {c.pair(): c for c in candidates}
    edges: list[Edge] = []
    review: list[ReviewItem] = []
    #: (listing, other retailer) slots already holding an exact edge.
    held: set[tuple[Key, str]] = set()
    for pair, d in sorted(decisions.items()):
        if d.verdict is Verdict.REJECT:
            continue
        a, b = pair
        c = by_pair.get(pair)
        problem = _decision_problem(d, prepared, fps)
        if problem is not None:
            # The pair stays out of the machine ladder below: a human must look again.
            review.append(
                ReviewItem(
                    a=_ref(a),
                    b=_ref(b),
                    reason=problem,
                    bucket=None if c is None else c.bucket,
                    score=None if c is None else c.score,
                    reasons=("human_decision",) if c is None else c.reasons,
                )
            )
            continue
        edges.append(
            Edge(
                a=_ref(a),
                b=_ref(b),
                match_class=d.match_class,
                review_state=ReviewState.LOCKED
                if d.verdict is Verdict.LOCK
                else ReviewState.APPROVED,
                decided_by="human",
                confidence=None if c is None else c.score,
                method=algo_version,
                reasons=("human_decision",) if c is None else c.reasons,
            )
        )
        if d.match_class is MatchClass.EXACT:
            held.update(((a, b[0]), (b, a[0])))
    ranked = sorted(
        (c for c in candidates if c.pair() not in decisions),
        key=lambda c: (_RANK[c.bucket], -c.score, c.a.key(), c.b.key()),
    )
    for c in ranked:
        a, b = c.pair()
        reason: ReviewReason | None = None
        if c.bucket is Bucket.EXACT:
            if (a, b[0]) in held or (b, a[0]) in held:
                reason = ReviewReason.ONE_TO_ONE
            else:
                held.update(((a, b[0]), (b, a[0])))
                auto = _category(prepared, a, b) in auto_accept
                edges.append(
                    Edge(
                        a=c.a,
                        b=c.b,
                        match_class=MatchClass.EXACT,
                        review_state=ReviewState.APPROVED if auto else ReviewState.PROPOSED,
                        decided_by="auto" if auto else None,
                        confidence=c.score,
                        method=algo_version,
                        reasons=c.reasons,
                    )
                )
        elif "gtin_conflict" in c.reasons:
            reason = ReviewReason.GTIN_CONFLICT
        elif "related_only" in c.reasons:
            edges.append(_machine_edge(c, MatchClass.SUBSTITUTE, algo_version))
        elif _unsized_family(c, prepared):
            # A listing without a size (or an unobserved shade) is the line, not one variant:
            # it links to the line's variants, never as exact (Coordinator ruling (b)).
            edges.append(_machine_edge(c, MatchClass.FAMILY, algo_version))
        elif "family_only" in c.reasons:
            if c.score >= EXACT_MIN and not _family_blocked(prepared, a, b):
                edges.append(_machine_edge(c, MatchClass.FAMILY, algo_version))
            else:
                reason = ReviewReason.FAMILY_WEAK
        elif c.bucket is Bucket.PROBABLE:
            reason = ReviewReason.PROBABLE
        else:
            reason = ReviewReason.LOW
        if reason is not None:
            review.append(
                ReviewItem(
                    a=c.a, b=c.b, reason=reason, bucket=c.bucket, score=c.score, reasons=c.reasons
                )
            )
    edges, dropped = _cliques(edges)
    review.extend(
        ReviewItem(
            a=e.a,
            b=e.b,
            reason=ReviewReason.NOT_CLIQUE,
            bucket=None if (c := by_pair.get(e.pair())) is None else c.bucket,
            score=None if c is None else c.score,
            reasons=e.reasons,
        )
        for e in dropped
    )
    edges.sort(key=lambda e: (e.a.key(), e.b.key()))
    review.sort(key=lambda r: (r.a.key(), r.b.key()))
    return edges, review


_STATE_RANK = {ReviewState.LOCKED: 0, ReviewState.APPROVED: 1, ReviewState.PROPOSED: 2}


def _cliques(edges: Sequence[Edge]) -> tuple[list[Edge], list[Edge]]:
    """Exact edges that keep every group a clique, and the auto edges that would not (ADR-0012 §6).

    Edges join groups in priority order (locked, approved, proposed, then confidence, then ids).
    A join is allowed only when the two groups share no retailer and every cross pair has its
    own exact edge, so u-s and s-f never group u with f without a u-f edge. A human edge is a
    decision and stays an edge even when it cannot join (compose skips and logs it); an auto edge
    that cannot join goes to review.
    """
    exact = [e for e in edges if e.match_class is MatchClass.EXACT]
    pairs = {e.pair() for e in exact}
    group: dict[Key, frozenset[Key]] = {}
    kept: list[Edge] = [e for e in edges if e.match_class is not MatchClass.EXACT]
    dropped: list[Edge] = []
    ranked = sorted(
        exact,
        key=lambda e: (_STATE_RANK[e.review_state], -(e.confidence or 0), e.a.key(), e.b.key()),
    )
    for e in ranked:
        a, b = e.pair()
        ga, gb = group.get(a, frozenset({a})), group.get(b, frozenset({b}))
        joinable = ga == gb or (
            not {k[0] for k in ga} & {k[0] for k in gb}
            and all(_ordered(x, y) in pairs for x in ga for y in gb)
        )
        if joinable:
            merged = ga | gb
            for k in merged:
                group[k] = merged
            kept.append(e)
        elif e.decided_by == "human":
            kept.append(e)
        else:
            dropped.append(e)
    return kept, dropped


def _machine_edge(c: Candidate, match_class: MatchClass, algo_version: str) -> Edge:
    """A proposed edge from a candidate: a human approves it, the machine never does."""
    return Edge(
        a=c.a,
        b=c.b,
        match_class=match_class,
        review_state=ReviewState.PROPOSED,
        decided_by=None,
        confidence=c.score,
        method=algo_version,
        reasons=c.reasons,
    )


def _unsized_family(c: Candidate, prepared: Mapping[Key, Prepared]) -> bool:
    """A strong, unflagged pair whose only gap is a size or shade that one side does not state."""
    a, b = c.pair()
    unknown = "size_unknown" in c.reasons or "shade_unknown" in c.reasons
    flagged = any(r.startswith("name_") and r.endswith("_conflict") for r in c.reasons)
    return (
        unknown
        and not flagged
        and c.score >= EXACT_MIN
        and "concentration_unknown_one_side" not in c.reasons
        and not _family_blocked(prepared, a, b)
    )


def _family_blocked(prepared: Mapping[Key, Prepared], a: Key, b: Key) -> bool:
    """A family edge still needs kind, form and concentration to agree (known on both sides or
    on neither)."""
    left, right = prepared[a], prepared[b]
    known = left.concentration is not None or right.concentration is not None
    if known and concentration_relation(left, right) == "unknown":
        return True  # "Bloom" vs "Bloom Parfum": the line is not known to agree
    conflicts = set(hard_conflicts(left, right))
    return bool(conflicts - {"size_differs", "shade_differs"})


def run(  # noqa: PLR0913 -- the inputs of ADR-0012 §5, the knobs keyword-only
    listings: Mapping[str, Sequence[ProductRecord]],
    previous: MatchFile | None = None,
    decisions: Sequence[Decision] = (),
    *,
    scope: str,
    vertical: str,
    algo_version: str,
    generated_at: str,
    auto_accept: Iterable[str] = (),
    unkeyed: Mapping[str, int] | None = None,
) -> MatchFile:
    """The next match file. See the module docstring for the rules."""
    if auto_accept:
        # ADR-0012 §8: a category is auto-accepted only once the gold-set gate shows its precision
        # lower bound >= 98%. Until that gate exists (PR4) every exact edge stays proposed.
        msg = "auto_accept needs the ADR-0012 §8 gold-set gate, which does not exist yet"
        raise ValueError(msg)
    if previous is not None and (previous.scope, previous.vertical) != (scope, vertical):
        msg = f"previous file is {previous.scope}/{previous.vertical}, not {scope}/{vertical}"
        raise ValueError(msg)
    prepared = _prepare_all(listings)
    fps = {k: fingerprint(p) for k, p in prepared.items()}
    reusable = previous is not None and previous.algo_version == algo_version
    old_fps: dict[Key, str] = {}
    if previous is not None and reusable:
        old_fps = {(r, t): f for r, toks in previous.listings.items() for t, f in toks.items()}
    dirty = {k for k, f in fps.items() if old_fps.get(k) != f}
    kept = [
        c
        for c in (previous.candidates if previous is not None and reusable else ())
        if c.a.key() not in dirty
        and c.b.key() not in dirty
        and fps.get(c.a.key()) == c.fingerprint_a
        and fps.get(c.b.key()) == c.fingerprint_b
    ]
    candidates = sorted(
        [*kept, *_score(prepared, _pairs_to_score(prepared, dirty))],
        key=lambda c: (c.a.key(), c.b.key()),
    )
    merged = _merge_decisions(previous.decisions if previous else (), decisions, prepared, fps)
    accept = frozenset(auto_accept)
    edges, review = _assign(
        candidates, merged, prepared, fps, algo_version=algo_version, auto_accept=accept
    )
    by_retailer: dict[str, dict[str, str]] = defaultdict(dict)
    for (retailer, token), f in sorted(fps.items()):
        by_retailer[retailer][token] = f
    return MatchFile(
        schema_id=SCHEMA,
        scope=scope,
        vertical=vertical,
        algo_version=algo_version,
        generated_at=generated_at,
        auto_accept=tuple(sorted(accept)),
        listings=dict(sorted(by_retailer.items())),
        unkeyed=dict(sorted((unkeyed or {}).items())),
        candidates=tuple(candidates),
        decisions=tuple(d for _, d in sorted(merged.items())),
        edges=tuple(edges),
        review=tuple(review),
    )


def dump(file: MatchFile) -> str:
    """Canonical JSON: camelCase, sorted keys, one trailing newline (byte-identical reruns)."""
    data = file.model_dump(mode="json", by_alias=True)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + "\n"
