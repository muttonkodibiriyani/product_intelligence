"""Load, validate, dump and describe ``pi.dataset/v2`` and ``v3`` documents.

``load_dataset`` is the only way a consumer should read a document: it refuses JSON floats,
credential-like content and synthetic data (unless allowed) before the model rules run, and it
reports every problem it finds with its path. It reads v2 only; ``load_any`` reads v2 and v3
(ADR-0008 §0). Both check the ``schema`` id before any model rule runs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from pi_dataset.models import SCHEMA_ID, Dataset
from pi_dataset.v3 import SCHEMA_ID_V3, DatasetV3

SCHEMA_URI = "https://github.com/muttonkodibiriyani/product_intelligence/docs/contracts/pi-dataset-v2.schema.json"
SCHEMA_URI_V3 = SCHEMA_URI.replace("-v2.", "-v3.")

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
        super().__init__("invalid pi.dataset document: " + "; ".join(errors))


def _refuse_float(text: str) -> Any:
    msg = f"JSON float {text} is not allowed: use a decimal string or money object"
    raise DatasetError([msg])


def _parse(raw: bytes | str, accepts: tuple[str, ...]) -> str:
    """Credential scan, float refusal and the schema id, before any model rule.

    The decoded text and its parse are dropped on return: the caller validates ``raw`` itself,
    so a large document is never held as bytes, text and a JSON tree at once (tm8 01a11763-dc85).
    """
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
    schema = doc.get("schema") if isinstance(doc, dict) else None
    if schema not in accepts:
        shown = schema if isinstance(schema, str) else repr(schema)
        raise DatasetError(
            [f"unsupported schema {shown}; this reader accepts {', '.join(accepts)}"]
        )
    return str(schema)


def _validate[M: (Dataset, DatasetV3)](model: type[M], raw: bytes | str, allow_test: bool) -> M:
    try:
        # Strict: no coercion, so "false", "12900" or 0 never stand in for false, 12900 or false.
        # Bytes as given: a str would add a UTF-8 copy for the validator to read.
        dataset = model.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        raise DatasetError(
            [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()]
        ) from exc
    if dataset.meta.test and not allow_test:
        raise DatasetError(["meta.test is true: synthetic data is refused unless allowed"])
    return dataset


def load_dataset(raw: bytes | str, *, allow_test: bool = False) -> Dataset:
    """Parse and validate a v2 document; raise ``DatasetError`` rather than return a partial one."""
    _parse(raw, (SCHEMA_ID,))
    return _validate(Dataset, raw, allow_test)


def load_any(raw: bytes | str, *, allow_test: bool = False) -> Dataset | DatasetV3:
    """A v2 or v3 document, each parsed with its own model (ADR-0008 §0)."""
    schema = _parse(raw, (SCHEMA_ID, SCHEMA_ID_V3))
    if schema == SCHEMA_ID_V3:
        return _validate(DatasetV3, raw, allow_test)
    return _validate(Dataset, raw, allow_test)


def dump_dataset(dataset: Dataset | DatasetV3, *, compact: bool = False) -> bytes:
    """Canonical UTF-8 JSON: aliases, explicit nulls, no floats (there are none to emit).

    ``compact`` drops the indentation: the form the exporter writes and the publisher uploads,
    since whitespace is a third of an indented snapshot and none of it is data."""
    return (dataset.model_dump_json(indent=None if compact else 2) + "\n").encode("utf-8")


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


def json_schema_v3() -> dict[str, Any]:
    """The JSON Schema committed as ``docs/contracts/pi-dataset-v3.schema.json``."""
    schema = DatasetV3.model_json_schema(by_alias=True)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URI_V3,
        "title": "pi.dataset/v3",
        "description": (
            "Published snapshot contract v3 (ADR-0008). Generated from pi_dataset; do not edit. "
            "Cross-field rules (context ids, identity rules, declared attributes, profile size "
            "rules, plus every v2 rule) are in docs/contracts/pi-dataset-v3.md and enforced by "
            "pi_dataset.load_any."
        ),
        **{k: v for k, v in schema.items() if k != "title"},
    }


def schema_text(version: int = 2) -> str:
    schema = json_schema_v3() if version == 3 else json_schema()
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
