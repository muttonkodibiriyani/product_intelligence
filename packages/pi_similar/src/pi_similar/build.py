"""Build ``pi.similar/v1`` from published datasets (design §3).

For each item, candidates are the items at every **other** retailer in the same department, of
the same kind (mini, refill, set or regular), with no conflicting form, concentration or gender,
and not the same product under any identity. The text model pre-selects the ``preselect``
nearest per other retailer (numpy, chunked); those are scored on every present signal and the
best ``k`` per other retailer are kept. Ties break on retailer, then product id, so a run is
deterministic for the same inputs.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from decimal import Decimal

import numpy as np

from pi_similar.items import Department, Doc, Item, items
from pi_similar.model import SCHEMA, Competitor, Meta, Signals, Similar, SimilarFile
from pi_similar.signals import (
    WEIGHTS,
    WEIGHTS_VERSION,
    ConflictError,
    PriceBands,
    Signal,
    attributes,
    combine,
    cosine,
    price,
    q,
)
from pi_similar.text import FloatArray, TextEmbedder, unit_rows

K = 5
PRESELECT = 50
_CHUNK = 512

#: Unordered product id pairs that are the same product (exact, family or substitute edges).
Identity = Collection[frozenset[str]]


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(q(value))


def _rank(c: Competitor) -> tuple[Decimal, str, str]:
    return (-Decimal(c.score), c.retailer, c.product)


def _competitor(
    a: Item, b: Item, text: float, bands: PriceBands, identity: Identity
) -> Competitor | None:
    if a.product == b.product or frozenset((a.product, b.product)) in identity:
        return None
    try:
        attr, attr_reasons = attributes(a, b)
    except ConflictError:
        return None
    price_signal, price_reason = price(a, b, bands)
    found = {
        Signal.TEXT: cosine(text),
        Signal.IMAGE: None,  # phase 2 (design §5): no image fetch yet
        Signal.PRICE: price_signal,
        Signal.ATTRIBUTES: attr,
    }
    score = combine(found)
    if score is None:
        return None
    same_brand = a.brand == b.brand
    reasons = (*attr_reasons, *((price_reason,) if price_reason else ()))
    return Competitor(
        product=b.product,
        retailer=b.retailer,
        score=str(score),
        signals=Signals(
            text=_text(found[Signal.TEXT]),
            image=_text(found[Signal.IMAGE]),
            price=_text(found[Signal.PRICE]),
            attributes=_text(found[Signal.ATTRIBUTES]),
        ),
        reasons=(*reasons, "same_brand" if same_brand else "other_brand"),
        same_brand=same_brand,
    )


def _nearest(left: FloatArray, right: FloatArray, n: int) -> list[list[tuple[int, float]]]:
    """Per left row, the ``n`` right rows with the highest cosine, best first, ties by index."""
    out: list[list[tuple[int, float]]] = []
    for start in range(0, len(left), _CHUNK):
        sims = left[start : start + _CHUNK] @ right.T
        for row in sims:
            order = np.lexsort((np.arange(len(row)), -row))[:n]
            out.append([(int(j), float(row[j])) for j in order])
    return out


def _groups(found: Sequence[Item]) -> dict[tuple[Department, str], list[int]]:
    groups: defaultdict[tuple[Department, str], list[int]] = defaultdict(list)
    for index, it in enumerate(found):
        if it.department is not None:
            groups[(it.department, it.retailer)].append(index)
    return groups


def build_similar(  # noqa: PLR0913 - the inputs, then keyword-only run options
    docs: Iterable[Doc],
    embedder: TextEmbedder,
    *,
    scope: str,
    generated_at: str,
    identity: Identity = frozenset(),
    k: int = K,
    preselect: int = PRESELECT,
) -> SimilarFile:
    found = items(docs)
    vectors = unit_rows(embedder.embed([it.text for it in found])) if found else None
    bands = PriceBands.of(found)
    groups = _groups(found)
    lists: dict[int, list[Competitor]] = defaultdict(list)
    for (dept, retailer), left in sorted(groups.items()):
        for (other_dept, other), right in sorted(groups.items()):
            if other_dept is not dept or other == retailer or vectors is None:
                continue
            nearest = _nearest(vectors[left], vectors[right], preselect)
            for i, row in zip(left, nearest, strict=True):
                kept = [
                    c
                    for j, text in row
                    if found[i].kind is found[right[j]].kind
                    and (c := _competitor(found[i], found[right[j]], text, bands, identity))
                ]
                kept.sort(key=_rank)
                lists[i].extend(kept[:k])
    similar = [
        Similar(
            product=found[i].product,
            retailer=found[i].retailer,
            competitors=tuple(sorted(competitors, key=_rank)),
        )
        for i, competitors in sorted(lists.items())
        if competitors
    ]
    similar.sort(key=lambda s: (s.product, s.retailer))
    return SimilarFile.model_validate(
        {
            "schema": SCHEMA,
            "meta": Meta(
                scope=scope,
                generated_at=generated_at,
                models={Signal.TEXT.value: embedder.model_id},
                weights_version=WEIGHTS_VERSION,
                weights={s.value: str(w) for s, w in WEIGHTS.items()},
                k=k,
            ),
            "similar": similar,
        }
    )
