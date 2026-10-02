"""``/v1/export/{view}`` (design §6, S4): one view's rows as CSV or JSONL, plus a manifest.

The rows are exactly the ones the view's endpoint returns, from the same call: this module only
encodes them. Line 1 is the manifest (one quoted ``"# <JSON>"`` cell for CSV, a
``{"manifest": ...}`` object for JSONL). An export over ``MAX_EXPORT_ROWS`` is refused (422
``export_too_large``), never cut short; beyond ``MAX_CONCURRENT_EXPORTS`` running on an instance
it is refused with 429. Every export, refused or not, writes one ``pi_api.export`` audit entry,
which never carries row content.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sys
import threading
import weakref
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, TextIO

from pi_api.auth import Principal
from pi_api.wire import API_VERSION, ApiMeta, CaveatView, Envelope, Localized
from pi_dataset import ContractModel
from pi_metrics import Cohort, Reason, Status

MAX_EXPORT_ROWS = 50_000
#: Per instance. A 50 k-row CSV export peaks at ~220 MiB (measured), so two fit in 1 GiB.
MAX_CONCURRENT_EXPORTS = 2
#: Seconds a client should wait when every export slot is busy.
BUSY_RETRY = 5
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


class ExportBusyError(Exception):
    """Every export slot on this instance is in use (429 with Retry-After)."""


class Outcome(StrEnum):
    OK = "ok"
    TOO_LARGE = "too_large"
    BUSY = "busy"


class ExportSlots:
    """A non-blocking counter of running exports; a slot is held until its stream is done."""

    def __init__(self, size: int) -> None:
        self._slots = threading.BoundedSemaphore(size) if size > 0 else None

    def acquire(self) -> bool:
        return self._slots is not None and self._slots.acquire(blocking=False)

    def release(self) -> None:
        if self._slots is not None:
            self._slots.release()

    def hold(self, chunks: Iterator[bytes]) -> HeldStream:
        """``chunks`` holding an acquired slot until they end, fail, close or are dropped."""
        return HeldStream(chunks, self.release)


class HeldStream:
    """An iterator that releases its slot exactly once, however the download ends.

    A generator's ``finally`` is not enough: Starlette sends the response headers before it
    first iterates the body, so a client that goes away before then leaves the generator
    unstarted, and closing or collecting an unstarted generator skips its ``finally``. Here the
    release is a ``weakref.finalize``, which runs once on exhaustion, on an error, on ``close()``
    or when the stream is dropped unstarted, whichever comes first.

    "Dropped" relies on the response, and with it this stream, being freed. CPython frees it as
    soon as the last reference goes; if a reference cycle holds it, the slot waits for the cyclic
    garbage collector instead.
    """

    def __init__(self, chunks: Iterator[bytes], release: Callable[[], None]) -> None:
        self._chunks = chunks
        self._release = weakref.finalize(self, release)

    def __iter__(self) -> HeldStream:
        return self

    def __next__(self) -> bytes:
        try:
            return next(self._chunks)
        except BaseException:  # StopIteration included: the download is over either way
            self._release()
            raise

    def close(self) -> None:
        self._release()

    @property
    def held(self) -> bool:
        return self._release.alive


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


def too_large(rows: int) -> ExportTooLargeError | None:
    if rows <= MAX_EXPORT_ROWS:
        return None
    return ExportTooLargeError(
        f"{rows} rows is over the export cap of {MAX_EXPORT_ROWS}; narrow the filters"
    )


# ---------------------------------------------------------------- encoding


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """A JSON value as dotted columns; a list stays one cell of compact JSON (unambiguous)."""
    if isinstance(value, Mapping):
        if not value and prefix:
            return {prefix: ""}
        out: dict[str, str] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list | tuple):
        return {prefix: json.dumps(value, ensure_ascii=False, separators=(",", ":"))}
    return {prefix: _scalar(value)}


def safe_cell(text: str) -> str:
    """Neutralises a cell a spreadsheet would run as a formula."""
    if text.startswith(_FORMULA_START) and not _NUMBER.match(text):
        return "'" + text
    return text


#: Columns added after a view first shipped go last, whatever row they are first seen in, so a
#: reader that relied on the earlier column positions keeps them. An entry also covers the
#: columns nested under it (``sizeLabel`` covers ``sizeLabel.label``).
TRAILING: Mapping[ExportView, tuple[str, ...]] = {
    ExportView.COVERAGE: ("contexts",),  # ADR-0008 step 4
    ExportView.PRODUCTS: ("gap.sizeLabels", "sizeLabel", "sizeSystem"),  # API 1.2.0
}


def _trailing_rank(key: str, trailing: tuple[str, ...]) -> int | None:
    return next((i for i, t in enumerate(trailing) if key == t or key.startswith(t + ".")), None)


def columns_of(flat: Iterable[Mapping[str, str]], trailing: tuple[str, ...] = ()) -> list[str]:
    """Every key in first-seen order, minus a key that another key nests under, ``trailing`` last
    (in ``trailing``'s order, first-seen order within an entry).

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
    kept = [key for key in seen if key not in nested]
    ranks = {key: _trailing_rank(key, trailing) for key in kept}
    last = sorted((k for k in kept if ranks[k] is not None), key=lambda k: ranks[k] or 0)
    return [key for key in kept if ranks[key] is None] + last


def _line(writer_buffer: io.StringIO, writer: Any, cells: Sequence[str]) -> bytes:
    writer.writerow(cells)
    text = writer_buffer.getvalue()
    writer_buffer.seek(0)
    writer_buffer.truncate()
    return text.encode()


def _flat(row: ContractModel) -> dict[str, str]:
    return flatten(row.model_dump(mode="json", by_alias=True))


def encode_csv(head: ExportManifest, rows: Sequence[ContractModel]) -> Iterator[bytes]:
    """UTF-8 with a BOM (so spreadsheets read Arabic), the manifest, header, rows.

    The manifest is **one quoted cell**, ``"# <manifest JSON>"``. A spreadsheet shows it as a
    single cell starting with ``#``, so no filter value inside it (``=HYPERLINK(...)``, say) is
    ever a cell of its own that could run as a formula. Rows are flattened twice (once for the
    columns, once to write) so the flattened copy of every row is never held at once.
    """
    names = columns_of((_flat(row) for row in rows), TRAILING.get(head.view, ()))
    buffer = io.StringIO()
    cell = "# " + _json(head.model_dump(mode="json", by_alias=True)).decode()
    csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_ALL).writerow([cell])
    yield ("\ufeff" + buffer.getvalue()).encode()
    buffer.seek(0)
    buffer.truncate()
    writer = csv.writer(buffer, lineterminator="\r\n")
    yield _line(buffer, writer, [safe_cell(n) for n in names])
    for row in rows:
        flat = _flat(row)
        yield _line(buffer, writer, [safe_cell(flat.get(n, "")) for n in names])


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


def audit(who: Principal, head: ExportManifest, outcome: Outcome = Outcome.OK) -> None:
    """One structured entry per export, refused ones included: who, what, how many, never a row."""
    entry = {
        "outcome": str(outcome),
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
