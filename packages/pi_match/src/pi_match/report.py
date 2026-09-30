"""Outputs: the matches file, brand overlap, summary and a labelling sheet for precision."""

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pi_match.model import BrandOverlap, Bucket, MatchPair

SAMPLE_SIZE = 50
SAMPLE_FIELDS = (
    "sample_id", "bucket", "score", "brand_key", "left_key", "left_name", "right_key",
    "right_name", "reasons", "label", "labelled_by", "note",
)  # fmt: skip


def _sample_order(pair: MatchPair) -> str:
    return hashlib.sha256(f"{pair.left_key}\x1f{pair.right_key}".encode()).hexdigest()


def precision_sample(pairs: Sequence[MatchPair], size: int = SAMPLE_SIZE) -> tuple[MatchPair, ...]:
    """A deterministic sample, round-robin across buckets (exact first), hash-ordered within.

    Rows are for hand-labelling (``label`` = correct / wrong / unsure); nothing is pre-labelled.
    """
    queues = {
        bucket: sorted((p for p in pairs if p.bucket is bucket), key=_sample_order)
        for bucket in Bucket
    }
    sample: list[MatchPair] = []
    while len(sample) < size and any(queues.values()):
        for bucket in Bucket:
            if queues[bucket] and len(sample) < size:
                sample.append(queues[bucket].pop(0))
    return tuple(sample)


def summary(
    pairs: Sequence[MatchPair], overlap: BrandOverlap, left_count: int, right_count: int
) -> dict[str, object]:
    """Counts for the demo: products, brands, pairs per bucket, and priced pairs."""
    buckets = Counter(p.bucket.value for p in pairs)
    return {
        "left_products": left_count,
        "right_products": right_count,
        "brands_both": len(overlap.both),
        "brands_only_left": len(overlap.only_left),
        "brands_only_right": len(overlap.only_right),
        "pairs": {bucket.value: buckets.get(bucket.value, 0) for bucket in Bucket},
        "pairs_with_price_gap": sum(p.price_gap_pct is not None for p in pairs),
    }


def write_outputs(
    out_dir: Path,
    pairs: Sequence[MatchPair],
    overlap: BrandOverlap,
    stats: dict[str, object],
    meta: dict[str, str],
) -> None:
    """Write matches.json, brand_overlap.json, summary.json and precision_sample.csv."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(name: str, payload: object) -> None:
        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        (out_dir / name).write_text(text + "\n", encoding="utf-8")

    dump("matches.json", {"meta": meta, "pairs": [p.model_dump(mode="json") for p in pairs]})
    dump("brand_overlap.json", {"meta": meta, **overlap.model_dump(mode="json")})
    dump("summary.json", {"meta": meta, **stats})
    with (out_dir / "precision_sample.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for index, pair in enumerate(precision_sample(pairs), start=1):
            writer.writerow(
                {
                    "sample_id": index,
                    "bucket": pair.bucket.value,
                    "score": str(pair.score),
                    "brand_key": pair.brand_key,
                    "left_key": pair.left_key,
                    "left_name": pair.left_name,
                    "right_key": pair.right_key,
                    "right_name": pair.right_name,
                    "reasons": ";".join(pair.reasons),
                    "label": "",
                    "labelled_by": "",
                    "note": "",
                }
            )
