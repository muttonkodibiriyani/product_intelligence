"""A ``pi.dataset/v3`` snapshot at the export's 50 MB budget, with ``Offer.content`` at realistic
sizes, loads inside the memory headroom the deploy runbook leaves (pi-api-deploy.md §6).

Text is cheaper per byte than the many small objects of a price-only product, so a budget-size
snapshot heavy with description/ingredients holds *less* than a price-only one; this pins that
the content fields do not change the arithmetic the 1Gi limit rests on.
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

BUDGET = 50_000_000  # scripts/demo_export/export.py V3_MAX_BYTES
HEADROOM = 200 * 2**20  # pi-api-deploy.md §6: ~200 MiB left inside 1Gi at the budget
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
    count = BUDGET // len(json.dumps(product(template, 0)))
    doc["products"] = [product(template, i) for i in range(count)]
    return json.dumps(doc).encode()


def test_a_budget_size_snapshot_with_content_loads_inside_the_headroom(tmp_path: Path) -> None:
    body = budget_doc()
    assert BUDGET * 0.98 < len(body) <= BUDGET * 1.02
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
    assert retained < HEADROOM, f"{retained / 2**20:.0f} MiB retained"
