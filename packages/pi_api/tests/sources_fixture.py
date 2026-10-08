"""Synthetic per-source snapshots (ADR-0010), built as JSON on the metrics fixture's meta.

``snapshot({"p1": (ULTA, SEPHORA)}, ...)`` is one same-scope ``pi.dataset/v3`` file whose
products have an offer per listed retailer, priced ``price`` on every date. A product offered by
both gets an exact match edge. Each retailer carries its own window, fields and capabilities, as
the exporter writes them (ADR-0013), unless ``per_retailer=False`` (a file from before them).
Invented ids and prices; nothing here is real data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from pi_dataset import DatasetV3
from v3_fixture import doc

ULTA, SEPHORA = "ulta_ae", "sephora_me"
Doc = dict[str, Any]


def days(last: str, n: int) -> tuple[str, ...]:
    end = date.fromisoformat(last)
    return tuple(str(end - timedelta(days=k)) for k in reversed(range(n)))


def _offer(retailer: str, minor: int, n: int, captured: str) -> Doc:
    price = {"amount": f"{minor // 100}.{minor % 100:02d}", "minor": minor, "currency": "AED"}
    return {
        "currency": "AED",
        "sku": None,
        "url": None,
        "size": {"value": "50", "unit": "ml", "label": None, "system": None},
        "shadeCount": 0,
        "rating": None,
        "early": False,
        "series": {"price": [price] * n, "regular": None, "availability": None},
        "evidence": {
            "capturedAt": captured,
            "source": f"fixture:{retailer}",
            "runId": f"run-{retailer}",  # the run of its window (own_keys)
            "itemKey": None,
            "itemKeyKind": None,
        },
        "image": None,
        "attributes": {},
    }


def _edge(a: str, b: str) -> Doc:
    return {
        "a": a,
        "b": b,
        "matchClass": "exact",
        "reviewState": "proposed",
        "decidedBy": None,
        "confidence": "0.95",
        "method": "fixture",
        "stage": "reviewed",
    }


def snapshot_doc(
    products: Mapping[str, Sequence[str]],
    *,
    dates: Sequence[str],
    price: int = 10_000,
    scope: str = "beauty",
    stage: str = "reviewed",
    fields: Mapping[str, str] | None = None,
    per_retailer: bool = True,
    windows: bool = True,
) -> Doc:
    d = doc()
    meta = d["meta"]
    cutoff = f"{dates[-1]}T00:00:00Z"
    retailers = sorted({r for offered in products.values() for r in offered})
    template = meta["retailers"][0]
    meta |= {
        "cutoff": cutoff,
        "generatedAt": f"{dates[-1]}T01:00:00Z",
        "scope": scope,
        "dates": list(dates),
        "matchStage": stage,
        "test": False,
        "retailers": [template | {"id": r, "name": r} for r in retailers],
        "contexts": [
            {"id": r, "retailer": r, "channel": "online", "location": None, "label": {"en": r}}
            for r in retailers
        ],
    }
    if fields is not None:
        meta["fields"] = dict(fields)
    if per_retailer:
        window = {"start": f"{dates[-1]}T00:00:00Z", "end": cutoff}
        meta["retailers"] = [
            r
            | {
                "window": window | {"runId": f"run-{r['id']}"} if windows else None,
                "fields": dict(meta["fields"]),
                "capabilities": dict(meta["capabilities"]),
            }
            for r in meta["retailers"]
        ]
    d["notObserved"] = []
    d["products"] = [
        {
            "id": pid,
            "brand": "Brand",
            "name": f"Product {pid}",
            "category": ["skincare", "serum"],
            "unit": "ml",
            "offers": {r: _offer(r, price, len(dates), cutoff) for r in offered},
            "matches": [_edge(*sorted(offered))] if len(offered) == 2 else [],
            "shades": [],
            "attributes": {},
            "image": None,
        }
        for pid, offered in products.items()
    ]
    return d


def snapshot(products: Mapping[str, Sequence[str]], **kwargs: Any) -> DatasetV3:
    return DatasetV3.model_validate(snapshot_doc(products, **kwargs))
