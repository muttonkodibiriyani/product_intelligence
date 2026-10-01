"""``/v1/export/{view}`` (design §6, S4): one view's rows as CSV or JSONL, plus a manifest.

The rows are exactly the ones the view's endpoint returns, from the same call: this module only
encodes them. Line 1 is the manifest (a ``#`` comment for CSV, a ``{"manifest": ...}`` object
for JSONL). An export over ``MAX_EXPORT_ROWS`` is refused (422 ``export_too_large``), never cut
short. Every export writes one ``pi_api.export`` audit entry, which never carries row content.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, TextIO

from pi_api.auth import Principal
from pi_api.wire import API_VERSION, ApiMeta, CaveatView, Envelope, Localized
from pi_dataset import ContractModel
from pi_metrics import Cohort, Reason, Status

MAX_EXPORT_ROWS = 50_000
MANIFEST_SCHEMA = "pi-api.export/v1"
AUDIT_EVENT = "pi_api.export"
audit_log = logging.getLogger("pi_api.audit")

#: Spreadsheet formula triggers (OWASP CSV injection). A plain signed number is left alone.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


class ExportFormat(StrEnum):
    CSV = "csv"
    JSONL = "jsonl"


class ExportView(StrEnum):
    PRODUCTS = "products"
    COMPARE = "compare"
    INDEX = "index"
    PROMOTIONS = "promotions"
    ASSORTMENT_GAPS = "assortment-gaps"
    COVERAGE = "coverage"


class FormatQuery(ContractModel):
    format: ExportFormat = ExportFormat.CSV


class ExportTooLargeError(Exception):
    """More rows than ``MAX_EXPORT_ROWS`` (422); the caller narrows the filters."""


class ExportManifest(ContractModel):
    """Everything the envelope says except ``data``, plus what the rows are."""

    schema_id: str = MANIFEST_SCHEMA
    view: ExportView
    format: ExportFormat
    rows: int
    status: Status
    reason: Reason | None
    detail: Localized | None
    cohort: Cohort | None
    caveats: tuple[CaveatView, ...]
    meta: ApiMeta


def manifest(
    view: ExportView, fmt: ExportFormat, rows: int, envelope: Envelope[Any]
) -> ExportManifest:
    return ExportManifest(
        view=view,
        format=fmt,
        rows=rows,
        status=envelope.status,
        reason=envelope.reason,
        detail=envelope.detail,
        cohort=envelope.cohort,
        caveats=envelope.caveats,
        meta=envelope.meta,
    )


def check_size(rows: Sequence[ContractModel]) -> None:
    if len(rows) > MAX_EXPORT_ROWS:
        msg = f"{len(rows)} rows is over the export cap of {MAX_EXPORT_ROWS}; narrow the filters"
        raise ExportTooLargeError(msg)


# ---------------------------------------------------------------- encoding


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """A JSON value as dotted columns. Lists of scalars join with ``|``; other lists stay JSON."""
    if isinstance(value, Mapping):
        if not value and prefix:
            return {prefix: ""}
        out: dict[str, str] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list | tuple):
        if all(not isinstance(v, Mapping | list | tuple) for v in value):
            return {prefix: "|".join(_scalar(v) for v in value)}
        return {prefix: json.dumps(value, ensure_ascii=False, separators=(",", ":"))}
    return {prefix: _scalar(value)}


def safe_cell(text: str) -> str:
    """Neutralises a cell a spreadsheet would run as a formula."""
    if text.startswith(_FORMULA_START) and not _NUMBER.match(text):
        return "'" + text
    return text


def columns(flat: Sequence[Mapping[str, str]]) -> list[str]:
    """Every key in first-seen order, minus a key that another key nests under.

    A null object (say an uncounted row's ``gap``) flattens to one empty ``gap`` cell, while a
    present one gives ``gap.amount.amount`` and so on; the nested columns win, and the null row
    leaves them empty.
    """
    seen = list(dict.fromkeys(key for row in flat for key in row))
    parents = {key.rsplit(".", 1)[0] for key in seen if "." in key}
    nested: set[str] = set()
    for parent in parents:
        parts = parent.split(".")
        nested.update(".".join(parts[: i + 1]) for i in range(len(parts)))
    return [key for key in seen if key not in nested]


def _line(writer_buffer: io.StringIO, writer: Any, cells: Sequence[str]) -> bytes:
    writer.writerow(cells)
    text = writer_buffer.getvalue()
    writer_buffer.seek(0)
    writer_buffer.truncate()
    return text.encode()


def encode_csv(head: ExportManifest, rows: Sequence[ContractModel]) -> Iterator[bytes]:
    """UTF-8 with a BOM (so spreadsheets read Arabic), ``# <manifest JSON>``, header, rows."""
    flat = [flatten(row.model_dump(mode="json", by_alias=True)) for row in rows]
    names = columns(flat)
    yield "\ufeff# ".encode() + _json(head.model_dump(mode="json", by_alias=True)) + b"\r\n"
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    yield _line(buffer, writer, [safe_cell(n) for n in names])
    for row in flat:
        yield _line(buffer, writer, [safe_cell(row.get(n, "")) for n in names])


def encode_jsonl(head: ExportManifest, rows: Sequence[ContractModel]) -> Iterator[bytes]:
    """``{"manifest": ...}`` then one row per line, each as the endpoint serialises it."""
    yield _json({"manifest": head.model_dump(mode="json", by_alias=True)}) + b"\n"
    for row in rows:
        yield _json(row.model_dump(mode="json", by_alias=True)) + b"\n"


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


MEDIA_TYPES = {
    ExportFormat.CSV: "text/csv; charset=utf-8",
    ExportFormat.JSONL: "application/x-ndjson",
}


def encode(head: ExportManifest, rows: Sequence[ContractModel]) -> Iterator[bytes]:
    return encode_csv(head, rows) if head.format is ExportFormat.CSV else encode_jsonl(head, rows)


def filename(view: ExportView, fmt: ExportFormat, cutoff: datetime) -> str:
    return f"pi-{view}-{cutoff:%Y%m%dT%H%MZ}.{fmt}"


# ---------------------------------------------------------------- audit


def audit(who: Principal, head: ExportManifest) -> None:
    """One structured entry per export: who, what and how many, never a row."""
    entry = {
        "severity": "NOTICE",
        "message": AUDIT_EVENT,
        "event": AUDIT_EVENT,
        "uid": who.uid,
        "role": str(who.role),
        "view": str(head.view),
        "format": str(head.format),
        "filters": head.meta.filters,
        "rows": head.rows,
        "generation": head.meta.generation,
        "apiVersion": API_VERSION,
    }
    audit_log.info(json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def configure_audit(stream: TextIO = sys.stdout) -> None:
    """Bare JSON lines on stdout, so Cloud Run logs each entry as a structured ``jsonPayload``."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_log.handlers = [handler]
    audit_log.setLevel(logging.INFO)
    audit_log.propagate = False
