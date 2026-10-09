"""A ``pi.dataset/v3`` snapshot with ``Offer.content`` at realistic sizes, scaled to the export's
compact budget, stays inside the resident share the deploy runbook gives one dataset at 3Gi
(pi-api-deploy.md §6).

The content is synthetic with a real shape: ``fixtures/ounass_offer_content_sample.json`` is
written by ``make_offer_content_sample.py`` from a profile of 200 real Ounass offers taken at a
fixed stride from the snapshot the budget was calibrated on (each description's length, UTF-8
size and character width; each offer's images, ids and what repeats inside it), with no retailer
text. Its per-offer zlib ratio is pinned to the range of real data, because packed content's
memory is its compressed size and repetitive filler text compresses ~10x better than real
descriptions. A 10 MB sample is loaded and
scaled linearly (resident memory grows with product count), so CI does not have to hold a
full-budget snapshot.
"""

from __future__ import annotations

import copy
import gc
import json
import tracemalloc
import zlib
from pathlib import Path
from typing import Any

from api_fixture import DATASET_PATH, bearer, make_client, own_keys, served_dataset
from make_offer_content_sample import sample
from pi_dataset import V3_MAX_BYTES, OfferContent

BUDGET = V3_MAX_BYTES  # compact JSON bytes
SAMPLE = 10_000_000
# pi-api-deploy.md §6: the gate's steady share at 3Gi (its fitted refresh peak, 70 + 31.48 MiB/MB
# x 51 MB = 1,676 MiB, / 2.68 the measured peak-to-steady ratio).
RESIDENT = 625 * 2**20
CONTENT = Path(__file__).parent / "fixtures" / "ounass_offer_content_sample.json"
# Real Ounass offer content compresses 2.09x in aggregate (per offer: p1 1.41, p99 3.55); the
# synthetic sample 2.14x (p1 1.44, p99 3.72).
RATIO = (1.6, 2.6)


def contents() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads(CONTENT.read_text(encoding="utf-8"))
    return loaded


def product(template: dict[str, Any], content: dict[str, Any], i: int) -> dict[str, Any]:
    p = copy.deepcopy(template)
    p["id"] = f"x{i:06d}"
    for offer in p["offers"].values():
        offer["content"] = copy.deepcopy(content)
        offer["content"]["family"] = f"family-{i // 3}"
    return p


def budget_doc() -> bytes:
    doc: dict[str, Any] = own_keys(served_dataset()).model_dump(mode="json", by_alias=True)
    template = next(p for p in doc["products"] if p["id"] == "p01")
    sample = contents()
    mean = sum(len(compact(product(template, c, 0))) for c in sample) / len(sample)
    count = int(SAMPLE // mean)
    doc["products"] = [product(template, sample[i % len(sample)], i) for i in range(count)]
    return compact(doc).encode()


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def zlib_ratio(sample: list[dict[str, Any]]) -> float:
    bodies = [OfferContent.model_validate(c).model_dump_json().encode() for c in sample]
    return sum(map(len, bodies)) / sum(len(zlib.compress(b)) for b in bodies)


def test_the_sample_is_what_its_generator_writes() -> None:
    assert contents() == sample()


def test_the_sample_carries_no_retailer_host() -> None:
    assert "ounass" not in CONTENT.read_text(encoding="utf-8").lower()


def test_the_sample_compresses_like_real_offer_content() -> None:
    assert RATIO[0] <= zlib_ratio(contents()) <= RATIO[1]


def test_the_ratio_check_rejects_repetitive_filler_text() -> None:
    words = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 30
    filler = {"captured": ["description", "ingredients"], "description": words[:1500]}
    assert zlib_ratio([{**filler, "ingredients": words[:1000]}]) > RATIO[1]


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
        assert response.json()["data"]["offers"][0]["content"]["description"]
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    at_budget = retained * scale
    assert at_budget < RESIDENT, f"{at_budget / 2**20:.0f} MiB at the budget"
