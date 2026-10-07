"""A ``pi.dataset/v3`` snapshot with ``Offer.content`` at realistic sizes, scaled to the export's
120 MB compact budget, stays inside the resident share the deploy runbook gives one dataset at
3Gi (pi-api-deploy.md §6).

Text is cheaper per byte than the many small objects of a price-only product, so a snapshot
heavy with description/ingredients holds *less* per byte than the real Ounass mix the budget was
calibrated on; this pins that the content fields do not change that arithmetic. A 10 MB sample
is loaded and scaled linearly (resident memory grows with product count), so CI does not have
to hold a full-budget snapshot.
"""

from __future__ import annotations

import copy
import gc
import json
import tracemalloc
from pathlib import Path
from typing import Any

from api_fixture import DATASET_PATH, bearer, make_client, served_dataset
from pi_metrics import view

BUDGET = 120_000_000  # scripts/demo_export/export.py V3_MAX_BYTES, compact JSON bytes
SAMPLE = 10_000_000
# pi-api-deploy.md §6: a dataset's steady share at 3Gi (~1,990 MiB refresh peak / 2.68).
RESIDENT = 740 * 2**20
CAPTURED = ["description", "ingredients", "images", "shade", "gtin"]
WORDS = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 30


def product(template: dict[str, Any], i: int) -> dict[str, Any]:
    p = copy.deepcopy(template)
    p["id"] = f"x{i:06d}"
    for offer in p["offers"].values():
        offer["content"] = {
            "captured": CAPTURED,
            "description": f"{WORDS[:1500]}{i}",  # ~1.5 KB, a typical beauty description
            "ingredients": f"{WORDS[:1000]}{i}",  # ~1 KB INCI list
            "images": [f"https://media.example/{i}/{k}.jpg" for k in range(6)],
            "variants": [
                {"sku": f"{i}-{k}", "shade": f"Shade {k}", "gtin": "4006381333931"}
                for k in range(4)
            ],
            "family": f"family-{i // 3}",
        }
    return p


def budget_doc() -> bytes:
    doc: dict[str, Any] = view.as_v3(served_dataset()).model_dump(mode="json", by_alias=True)
    template = next(p for p in doc["products"] if p["id"] == "p01")
    count = SAMPLE // len(compact(product(template, 0)))
    doc["products"] = [product(template, i) for i in range(count)]
    return compact(doc).encode()


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def test_a_budget_size_snapshot_with_content_stays_inside_its_resident_share(
    tmp_path: Path,
) -> None:
    body = budget_doc()
    assert SAMPLE * 0.98 < len(body) <= SAMPLE * 1.02
    scale = BUDGET / len(body)
    target = tmp_path / DATASET_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    del body
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        client, _ = make_client(tmp_path)
        # The first detail request builds the lazy indexes (families, lookups) too.
        response = client.get("/api/v1/products/x000001", headers=bearer())
        assert response.status_code == 200, response.text
        assert [s["productId"] for s in response.json()["data"]["offers"][0]["content"]["sizes"]]
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    at_budget = retained * scale
    assert at_budget < RESIDENT, f"{at_budget / 2**20:.0f} MiB at the budget"
