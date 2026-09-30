"""Load, validate, dump and describe ``pi.dataset/v2`` documents.

``load_dataset`` is the only way a consumer should read a document: it refuses JSON floats,
credential-like content and synthetic data (unless allowed) before the model rules run, and it
reports every problem it finds with its path.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from pi_dataset.models import SCHEMA_ID, Dataset

SCHEMA_URI = "https://github.com/muttonkodibiriyani/product_intelligence/docs/contracts/pi-dataset-v2.schema.json"

#: Never publish third-party credentials (the same patterns as ``publish_dataset``, #23). The scan
#: covers the whole document, scraped text included, and fails closed: a false positive in a
#: product name blocks publication until the producer is fixed, which is the intended trade-off.
FORBIDDEN = (
    re.compile(r"x-algolia-(api-key|application-id)", re.IGNORECASE),
    re.compile(r"algolia[^\"]{0,40}\"\s*:\s*\"[A-Za-z0-9]{10,}\"", re.IGNORECASE),
    re.compile(r"\"(api_?key|app_?id|application_?id)\"\s*:", re.IGNORECASE),
)


class DatasetError(ValueError):
    """A document that must not be served or published; ``errors`` lists every problem."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("invalid pi.dataset/v2 document: " + "; ".join(errors))


def _refuse_float(text: str) -> Any:
    msg = f"JSON float {text} is not allowed: use a decimal string or money object"
    raise DatasetError([msg])


def load_dataset(raw: bytes | str, *, allow_test: bool = False) -> Dataset:
    """Parse and validate a document; raise ``DatasetError`` rather than return a partial one."""
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    forbidden = [
        f"forbidden credential-like content: /{p.pattern}/" for p in FORBIDDEN if p.search(text)
    ]
    if forbidden:
        raise DatasetError(forbidden)
    try:
        doc = json.loads(text, parse_float=_refuse_float, parse_constant=_refuse_float)
    except json.JSONDecodeError as exc:
        raise DatasetError([f"not JSON: {exc.msg} at line {exc.lineno}"]) from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA_ID:
        raise DatasetError([f"schema must be {SCHEMA_ID!r}"])
    try:
        # Strict: no coercion, so "false", "12900" or 0 never stand in for false, 12900 or false.
        dataset = Dataset.model_validate_json(text, strict=True)
    except ValidationError as exc:
        raise DatasetError(
            [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()]
        ) from exc
    if dataset.meta.test and not allow_test:
        raise DatasetError(["meta.test is true: synthetic data is refused unless allowed"])
    return dataset


def dump_dataset(dataset: Dataset) -> bytes:
    """Canonical UTF-8 JSON: aliases, explicit nulls, no floats (there are none to emit)."""
    return (dataset.model_dump_json(indent=2) + "\n").encode("utf-8")


def json_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) committed as ``docs/contracts/pi-dataset-v2.schema.json``."""
    schema = Dataset.model_json_schema(by_alias=True)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URI,
        "title": "pi.dataset/v2",
        "description": (
            "Published snapshot contract (ADR-0007 §6). Generated from pi_dataset; do not edit. "
            "Cross-field rules (market currencies, series lengths, references, exact money) are "
            "in docs/contracts/pi-dataset-v2.md and enforced by pi_dataset.load_dataset."
        ),
        **{k: v for k, v in schema.items() if k != "title"},
    }


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
