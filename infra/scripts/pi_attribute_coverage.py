"""Deterministic whole-snapshot audit of the Product Detail attribute projection.

Run ``uv run python infra/scripts/pi_attribute_coverage.py retailer=dataset.json [...]``.
Canonical JSON is written to stdout and progress to stderr, so redirect stdout to retain a
replayable coverage receipt.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pi_api.attributes import (
    ATTRIBUTE_MANIFEST_VERSION,
    AttributeState,
    attribute_manifest,
    product_attribute_slots,
)
from pi_api.content import unpacked
from pi_dataset.validate import load_any
from pi_metrics.view import as_v3


def audit(  # noqa: PLR0912 - each branch is an independent fail-closed audit gate
    retailer: str, path: Path
) -> dict[str, Any]:
    raw = path.read_bytes()
    dataset = as_v3(load_any(raw))

    definitions = attribute_manifest()
    manifest_keys = tuple(definition.key for definition in definitions)
    products = len(dataset.products)
    offers = sum(len(product.offers) for product in dataset.products)
    variants = 0
    for product in dataset.products:
        for offer in product.offers.values():
            content = unpacked(offer.content)
            variants += (
                len(content.variants)
                if content is not None and content.variants
                else int(offer.sku is not None)
            )
    expected_targets = Counter(
        {"master": products, "product": products, "offer": offers, "variant": variants}
    )
    represented_targets: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    level_state_counts: dict[str, Counter[str]] = defaultdict(Counter)
    retailer_level_state_counts: dict[str, Counter[str]] = defaultdict(Counter)
    field_state_counts: dict[str, Counter[str]] = defaultdict(Counter)
    product_evidence_gaps: Counter[str] = Counter()
    offer_evidence_gaps: Counter[str] = Counter()
    target_ids: set[str] = set()

    for index, product in enumerate(dataset.products, start=1):
        product_evidence_gaps.update(product.attributes.keys() - product.attribute_evidence.keys())
        for offer in product.offers.values():
            offer_evidence_gaps.update(offer.attributes.keys() - offer.attribute_evidence.keys())
        projected = product_attribute_slots(dataset, product)
        for target, slots in projected:
            if target.id in target_ids:
                raise AssertionError(f"{retailer}: duplicate target {target.id}")
            target_ids.add(target.id)
            level = target.level.value
            represented_targets[level] += 1
            if len(slots) != 154:
                raise AssertionError(f"{retailer}: {target.id} has {len(slots)} slots")
            keys = tuple(slot.definition.key for slot in slots)
            if keys != manifest_keys:
                raise AssertionError(f"{retailer}: {target.id} manifest order/key drift")
            owner = target.retailer or "global"
            for slot in slots:
                state = slot.state.value
                state_counts[state] += 1
                level_state_counts[level][state] += 1
                retailer_level_state_counts[f"{owner}:{level}"][state] += 1
                field_state_counts[slot.definition.key][state] += 1
                if slot.state is AttributeState.OBSERVED and not slot.evidence:
                    raise AssertionError(
                        f"{retailer}: {target.id}/{slot.definition.key} observed without evidence"
                    )
        if index % 2_500 == 0:
            print(f"{retailer}: audited {index}/{products} products", file=sys.stderr)

    if represented_targets != expected_targets:
        raise AssertionError(
            f"{retailer}: represented {dict(represented_targets)} "
            f"!= source {dict(expected_targets)}"
        )
    total_targets = sum(represented_targets.values())
    if sum(state_counts.values()) != total_targets * 154:
        raise AssertionError(f"{retailer}: aggregate slot count drift")

    ordered_states = [state.value for state in AttributeState]

    def ordered(counter: Counter[str]) -> dict[str, int]:
        return {state: counter[state] for state in ordered_states}

    return {
        "retailer": retailer,
        "object": path.name,
        "objectSha256": hashlib.sha256(raw).hexdigest(),
        "source": {
            "products": products,
            "offers": offers,
            "variants": variants,
        },
        "sourceEvidenceGaps": {
            "product": dict(sorted(product_evidence_gaps.items())),
            "offer": dict(sorted(offer_evidence_gaps.items())),
        },
        "represented": {
            **dict(sorted(represented_targets.items())),
            "targets": total_targets,
            "missingProducts": 0,
            "missingTargets": 0,
        },
        "definitionCount": len(definitions),
        "slotCount": total_targets * len(definitions),
        "states": ordered(state_counts),
        "statesByLevel": {key: ordered(value) for key, value in sorted(level_state_counts.items())},
        "statesByRetailerAndLevel": {
            key: ordered(value) for key, value in sorted(retailer_level_state_counts.items())
        },
        "fieldStates": {key: ordered(field_state_counts[key]) for key in manifest_keys},
    }


def main() -> None:
    reports = []
    for spec in sys.argv[1:]:
        retailer, raw_path = spec.split("=", 1)
        reports.append(audit(retailer, Path(raw_path)))
    document = {
        "schema": "pi.attribute-coverage/v1",
        "manifestVersion": ATTRIBUTE_MANIFEST_VERSION,
        "definitionCount": len(attribute_manifest()),
        "datasets": reports,
    }
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    print(encoded)


if __name__ == "__main__":
    main()
