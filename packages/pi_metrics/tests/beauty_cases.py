"""Every metric call the beauty equality guard pins (ADR-0008 §4, "Pinning upgrade").

``cases()`` runs each public metric over the v2 fixture and its variants: every retailer pair,
every date, every grouping, the capability and field switches, a currency mismatch and an
unreviewed matching stage. ``golden/beauty_v2.json`` holds, per case, the first 16 hex digits
of the SHA-256 of its canonical JSON output (sorted keys, no whitespace), computed on v2 by the
``pi_metrics`` that predates v3 (metricVersion 2026-10-01.1); the full outputs are ~5 MB. The
test runs the same calls on ``upgrade(v2, beauty@1)`` and requires identical output. To see a
difference, run this module at the commit that generated the golden and diff the JSON.

Re-pinned once, for metricVersion 2026-10-06.1 (compare ``only_here`` counts the ``observed``
population). Only compare cases changed; with the old ``only_here`` the golden was reproduced
exactly, and both v2 and its upgrade still give the same hashes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from functools import partial
from itertools import permutations
from typing import Any

from metrics_fixture import (
    metrics_dataset,
    rebuild,
    with_capabilities,
    with_dates,
    with_fields,
    with_saudi_shop,
)
from pi_dataset import Dataset, FieldStatus
from pi_metrics import (
    EVERYTHING,
    GroupBy,
    ProductFilter,
    assortment_gaps,
    availability,
    compare,
    coverage,
    launches,
    price_index,
    promotions,
    reviews_summary,
)

Call = Callable[[Dataset], Any]
FILTERS = {
    "all": EVERYTHING,
    "makeup": ProductFilter(categories=("makeup",)),
    "ids": ProductFilter(ids=("p01", "p10", "p11", "p16")),
}


def variants() -> dict[str, Dataset]:
    ds = metrics_dataset()
    return {
        "base": ds,
        "history_off": with_capabilities(ds, history=False),
        "flags_off": with_capabilities(ds, promotions=False, stock=False, ratings=False),
        "fields_missing": with_fields(
            ds, regular=FieldStatus.NOT_COLLECTED, rating=FieldStatus.NOT_COLLECTED
        ),
        "saudi": with_saudi_shop(ds),
        "unreviewed": rebuild(ds, match_stage="proposed"),
        "one_date": with_dates(ds, 1),
    }


def _calls(ds: Dataset) -> Iterator[tuple[str, Call]]:
    shops = tuple(r.id for r in ds.meta.retailers)
    first, last = ds.meta.dates[0], ds.meta.dates[-1]
    for f, where in FILTERS.items():
        for base, other in permutations(shops, 2):
            for day in ds.meta.dates if f == "all" else (last,):
                yield (
                    f"compare/{f}/{base}/{other}/{day}",
                    partial(compare, base=base, other=other, where=where, on=day),
                )
            for by in GroupBy if f == "all" else ():
                yield (
                    f"compare/{f}/{base}/{other}/by-{by}",
                    partial(compare, base=base, other=other, where=where, group_by=by),
                )
            yield (
                f"index/{f}/{base}/{other}",
                partial(price_index, base=base, other=other, where=where),
            )
            yield (
                f"index/{f}/{base}/{other}/last",
                partial(price_index, base=base, other=other, where=where, start=last),
            )
            yield (
                f"assortment/{f}/{base}/{other}",
                partial(assortment_gaps, missing_at=base, present_at=other, where=where),
            )
        for ids in ((), *((s,) for s in shops)):
            name = "+".join(ids) or "all"
            yield f"promotions/{f}/{name}", partial(promotions, retailers=ids, where=where)
            yield (
                f"promotions/{f}/{name}/min10/first",
                partial(promotions, retailers=ids, where=where, min_pct=Decimal(10), on=first),
            )
            yield f"availability/{f}/{name}", partial(availability, retailers=ids, where=where)
            yield (
                f"availability/{f}/{name}/first",
                partial(availability, retailers=ids, where=where, on=first),
            )
            yield f"launches/{f}/{name}", partial(launches, retailers=ids, where=where)
            yield (
                f"launches/{f}/{name}/since",
                partial(launches, retailers=ids, where=where, since=last),
            )
            yield f"reviews/{f}/{name}", partial(reviews_summary, retailers=ids, where=where)
    for ids in ((), *((s,) for s in shops)):
        yield f"coverage/{'+'.join(ids) or 'all'}", partial(coverage, retailers=ids)


def cases() -> Iterator[tuple[str, Dataset, Call]]:
    for variant, ds in variants().items():
        for name, call in _calls(ds):
            yield f"{variant}/{name}", ds, call


def outputs(convert: Callable[[Dataset], Any]) -> dict[str, Any]:
    """Every case's JSON output, with each dataset passed through ``convert`` first."""
    converted: dict[int, Any] = {}
    result = {}
    for name, ds, call in cases():
        if id(ds) not in converted:
            converted[id(ds)] = convert(ds)
        result[name] = _pre_v3(call(converted[id(ds)]).model_dump(mode="json", by_alias=True))
    return result


def _pre_v3(output: Any) -> Any:
    """The output without fields added since v2, so it can equal the pre-v3 golden.

    ``coverage`` rows gained ``contexts`` in ADR-0008 step 4, and compare summaries ``gapHist``
    and summaries ``meanPrice`` (additive, API 1.7.1). Promotion rows gained ``bands`` and
    ``groups``, and promotion items ``brand``, ``category``, ``saved`` and ``image`` (additive,
    API 1.17.0), and compare rows ``match`` (additive, API 1.19.0) and ``image`` (additive,
    API 1.21.0); every other field is unchanged.
    """
    data = output.get("data") if isinstance(output, dict) else None
    retailers = data.get("retailers") if isinstance(data, dict) else None
    if isinstance(retailers, list):
        for row in retailers:
            if isinstance(row, dict):
                row.pop("contexts", None)
                row.pop("bands", None)
                row.pop("groups", None)
    items = data.get("items") if isinstance(data, dict) else None
    if isinstance(items, list) and isinstance(retailers, list):  # promotions: rows and items
        for item in items:
            if isinstance(item, dict) and "depthPct" in item:
                for key in ("brand", "category", "saved", "image"):
                    item.pop(key, None)
    return _without(output, frozenset({"gapHist", "meanPrice", "match", "image"}))


def _without(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {k: _without(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_without(v, keys) for v in value]
    return value


def digest(output: Any) -> str:
    canonical = json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]  # 64 bits: equality, not security


if __name__ == "__main__":  # regenerate only from a pi_metrics that predates v3
    from pathlib import Path

    path = Path(__file__).parent / "golden" / "beauty_v2.json"
    hashes = {name: digest(out) for name, out in outputs(lambda d: d).items()}
    path.write_text(json.dumps(hashes, indent=1, sort_keys=True) + "\n")
