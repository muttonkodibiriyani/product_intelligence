"""First-pass matching (blueprint §8, demo stage): brand blocking, rules, a name score.

Pure and deterministic: the same inputs give byte-identical outputs. Rules, blueprint §8.4:

- GTIN: two valid, equal GTINs are an exact match; two valid, different GTINs never match.
- Concentration (EDP/EDT/parfum/...), when both are known, must agree or the pair is dropped.
- Item kind (regular/mini/refill/set) must agree or the pair is dropped.
- Exact needs a strong name score, the same size and a compatible shade. A known size or shade
  code that differs caps the pair at ``candidate`` (same family, not the same item).

Each product is used in at most one pair: pairs are assigned greedily, best first.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from difflib import SequenceMatcher

from pi_match.model import BrandOverlap, Bucket, MatchPair, ProductRecord, UnitPrice
from pi_match.normalise import (
    Concentration,
    ItemKind,
    Shade,
    Size,
    concentration,
    item_kind,
    name_tokens,
    normalise_brand,
    parse_shade,
    parse_size,
    valid_gtin,
)

EXACT_MIN = Decimal("0.85")
PROBABLE_MIN = Decimal("0.70")
CANDIDATE_MIN = Decimal("0.50")
_SCORE_Q = Decimal("0.0001")
_BUCKET_RANK = {Bucket.EXACT: 0, Bucket.PROBABLE: 1, Bucket.CANDIDATE: 2}


@dataclass(frozen=True, slots=True)
class Prepared:
    """A record with its normalised features."""

    record: ProductRecord
    brand_key: str
    tokens: frozenset[str]
    size: Size | None
    shade: Shade | None
    concentration: Concentration | None
    kind: ItemKind
    gtin: str | None


def prepare(record: ProductRecord) -> Prepared:
    """Normalise one record. The size comes from ``size`` if given, else from the name."""
    brand_key = normalise_brand(record.brand)
    text = f"{record.name} {record.size or ''}"
    return Prepared(
        record=record,
        brand_key=brand_key,
        tokens=name_tokens(record.name, brand_key),
        size=parse_size(record.size) or parse_size(record.name),
        shade=parse_shade(record.shade),
        concentration=concentration(text),
        kind=item_kind(record.name),
        gtin=valid_gtin(record.gtin),
    )


def name_score(left: frozenset[str], right: frozenset[str]) -> Decimal:
    """0..1: 0.6 * token Jaccard + 0.4 * sequence ratio of the sorted tokens."""
    if not left or not right:
        return Decimal(0)
    jaccard = Decimal(len(left & right)) / Decimal(len(left | right))
    ratio = SequenceMatcher(None, " ".join(sorted(left)), " ".join(sorted(right))).ratio()
    score = Decimal("0.6") * jaccard + Decimal("0.4") * Decimal(str(round(ratio, 6)))
    return score.quantize(_SCORE_Q, rounding=ROUND_HALF_EVEN)


def _shade_relation(left: Shade | None, right: Shade | None) -> str:
    """ "same", "differs", or "unknown" (missing on either side)."""
    if left is None or right is None:
        return "unknown"
    if left.code is not None and right.code is not None:
        return "same" if left.code == right.code else "differs"
    if left.name is not None and right.name is not None:
        return "same" if left.name == right.name else "differs"
    return "unknown"


def _size_relation(left: Size | None, right: Size | None) -> str:
    if left is None or right is None:
        return "unknown"
    return "same" if left.same_as(right) else "differs"


def _excluded(left: Prepared, right: Prepared) -> bool:
    """Hard rules: a different item kind, or two known concentrations that differ."""
    if left.kind is not right.kind:
        return True
    return (
        left.concentration is not None
        and right.concentration is not None
        and left.concentration is not right.concentration
    )


def _bucket(left: Prepared, right: Prepared, score: Decimal, size: str, shade: str) -> Bucket:
    if size == "differs" or shade == "differs":
        return Bucket.CANDIDATE
    any_shaded = left.shade is not None or right.shade is not None
    if score >= EXACT_MIN and size == "same" and (shade == "same" or not any_shaded):
        return Bucket.EXACT
    return Bucket.PROBABLE if score >= PROBABLE_MIN else Bucket.CANDIDATE


def score_pair(left: Prepared, right: Prepared) -> tuple[Bucket, Decimal, tuple[str, ...]] | None:
    """Bucket, score and reasons for one same-brand pair, or None when rules exclude it."""
    reasons: list[str] = [f"brand={left.brand_key}"]
    if left.gtin is not None and right.gtin is not None:
        if left.gtin != right.gtin:
            return None
        return Bucket.EXACT, Decimal(1), (*reasons, "gtin_equal")
    score = name_score(left.tokens, right.tokens)
    if _excluded(left, right) or score < CANDIDATE_MIN:
        return None
    reasons.append(f"name={score}")
    if left.kind is not ItemKind.REGULAR:
        reasons.append(f"kind={left.kind.value}")
    if left.concentration is not None and left.concentration is right.concentration:
        reasons.append(f"concentration={left.concentration.value}")
    size = _size_relation(left.size, right.size)
    shade = _shade_relation(left.shade, right.shade)
    reasons.extend((f"size_{size}", f"shade_{shade}"))
    if "differs" in {size, shade}:
        reasons.append("family_only")
    return _bucket(left, right, score, size, shade), score, tuple(reasons)


def unit_price(item: Prepared) -> UnitPrice | None:
    """Price per 1 ml or 1 g, when price, currency and size are all known."""
    record = item.record
    if record.price is None or record.currency is None or item.size is None or not item.size.amount:
        return None
    amount = (record.price / item.size.amount).quantize(_SCORE_Q, rounding=ROUND_HALF_EVEN)
    return UnitPrice(amount=amount, currency=record.currency, unit=item.size.unit)


def _price_gap(
    left: Prepared, right: Prepared
) -> tuple[UnitPrice | None, UnitPrice | None, Decimal | None, str | None]:
    lu, ru = unit_price(left), unit_price(right)
    lp, rp = left.record.price, right.record.price
    if left.record.currency is None or left.record.currency != right.record.currency:
        return lu, ru, None, None
    if lu is not None and ru is not None and lu.unit == ru.unit and lu.amount:
        gap = (ru.amount - lu.amount) / lu.amount * 100
        return lu, ru, gap.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), "unit"
    if lp is not None and rp is not None and lp:
        gap = (rp - lp) / lp * 100
        return lu, ru, gap.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), "item"
    return lu, ru, None, None


def _pair(
    left: Prepared, right: Prepared, bucket: Bucket, score: Decimal, why: tuple[str, ...]
) -> MatchPair:
    lu, ru, gap, basis = _price_gap(left, right)
    return MatchPair(
        left_source=left.record.source,
        left_key=left.record.source_key,
        right_source=right.record.source,
        right_key=right.record.source_key,
        brand_key=left.brand_key,
        left_name=left.record.name,
        right_name=right.record.name,
        bucket=bucket,
        score=score,
        reasons=why,
        left_price=left.record.price,
        right_price=right.record.price,
        currency=left.record.currency if left.record.currency == right.record.currency else None,
        left_unit_price=lu,
        right_unit_price=ru,
        price_gap_pct=gap,
        price_basis=basis,
    )


def match(left: Sequence[ProductRecord], right: Sequence[ProductRecord]) -> tuple[MatchPair, ...]:
    """One-to-one pairs between two snapshots, best first, within shared brands only."""
    by_brand: dict[str, list[Prepared]] = defaultdict(list)
    for item in map(prepare, right):
        by_brand[item.brand_key].append(item)
    scored: list[tuple[int, Decimal, str, str, Prepared, Prepared, tuple[str, ...]]] = []
    for lp in map(prepare, left):
        for rp in by_brand.get(lp.brand_key, ()):
            result = score_pair(lp, rp)
            if result is None:
                continue
            bucket, score, why = result
            scored.append(
                (
                    _BUCKET_RANK[bucket],
                    -score,
                    lp.record.source_key,
                    rp.record.source_key,
                    lp,
                    rp,
                    why,
                )
            )
    scored.sort(key=lambda s: s[:4])
    used_left: set[str] = set()
    used_right: set[str] = set()
    pairs: list[MatchPair] = []
    for rank, neg_score, lkey, rkey, lp, rp, why in scored:
        if lkey in used_left or rkey in used_right:
            continue
        used_left.add(lkey)
        used_right.add(rkey)
        bucket = next(b for b, r in _BUCKET_RANK.items() if r == rank)
        pairs.append(_pair(lp, rp, bucket, -neg_score, why))
    return tuple(pairs)


def brand_overlap(left: Iterable[ProductRecord], right: Iterable[ProductRecord]) -> BrandOverlap:
    """Normalised brand keys in both snapshots and in only one of them."""
    lb = {normalise_brand(r.brand) for r in left}
    rb = {normalise_brand(r.brand) for r in right}
    return BrandOverlap(
        both=tuple(sorted(lb & rb)),
        only_left=tuple(sorted(lb - rb)),
        only_right=tuple(sorted(rb - lb)),
        left_brand_count=len(lb),
        right_brand_count=len(rb),
    )
