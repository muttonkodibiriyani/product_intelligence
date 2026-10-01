"""Feed readers: every format yields ``(row_number, {column: value})``.

Row numbers are what a person opening the file sees: CSV and XLSX count the header as row 1,
JSON counts items from 1. Values are strings, numbers, booleans or None as the file has them;
``validate`` does all interpretation.

XLSX is read with the standard library (zipfile) and defusedxml; openpyxl is not a workspace
dependency. Only cell values are read (shared strings, inline strings, numbers, booleans);
styles, formulas and dates as serial numbers are not interpreted.
"""

import csv
import json
import posixpath
import re
import zipfile
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from defusedxml import ElementTree  # type: ignore[import-untyped]

from offline_import.mapping import Format, ImportMapping

Row = dict[str, object]
NumberedRow = tuple[int, Row]

# Refuse archives that would expand past this (zip-bomb guard); real feeds are far smaller.
MAX_XLSX_MEMBER_BYTES = 256 * 1024 * 1024
_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


class FeedError(ValueError):
    """The file cannot be read as the configured format."""


def read_rows(path: Path, mapping: ImportMapping) -> Iterator[NumberedRow]:
    """Rows of ``path`` in the mapping's (or the suffix's) format."""
    fmt: Format = mapping.format_for(path)
    if fmt == "csv":
        return read_csv(path, delimiter=mapping.csv.delimiter, encoding=mapping.csv.encoding)
    if fmt == "xlsx":
        return read_xlsx(path, sheet=mapping.xlsx_sheet)
    return read_json(path, items_path=mapping.json_items_path)


# ---------------------------------------------------------------- CSV
def read_csv(
    path: Path, *, delimiter: str = ",", encoding: str = "utf-8-sig"
) -> Iterator[NumberedRow]:
    with path.open(newline="", encoding=encoding) as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if not reader.fieldnames:
            return
        for row in reader:
            extra = row.pop(None, None)
            if extra:
                raise FeedError(f"row {reader.line_num}: more values than header columns")
            yield reader.line_num, dict(row)


# ---------------------------------------------------------------- JSON
def read_json(path: Path, *, items_path: str | None = None) -> Iterator[NumberedRow]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    for part in items_path.split(".") if items_path else []:
        if not isinstance(data, dict) or part not in data:
            raise FeedError(f"JSON has no {items_path!r}")
        data = data[part]
    if not isinstance(data, list):
        raise FeedError("JSON feed must be an array of objects (set json_items_path)")
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise FeedError(f"item {i} is not an object")
        yield i, {str(k): v for k, v in item.items()}


# ---------------------------------------------------------------- XLSX
def _xml(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise FeedError(f"xlsx is missing {name}") from None
    if info.file_size > MAX_XLSX_MEMBER_BYTES:
        raise FeedError(f"xlsx member {name} is too large ({info.file_size} bytes)")
    return ElementTree.fromstring(archive.read(info))


def _text(node: Any) -> str:
    """Concatenated <t> runs of a shared or inline string (rich text has several)."""
    return "".join(t.text or "" for t in node.iter(f"{{{_NS['m']}}}t"))


def _sheet_member(archive: zipfile.ZipFile, sheet: str | None) -> str:
    workbook = _xml(archive, "xl/workbook.xml")
    sheets = workbook.findall("m:sheets/m:sheet", _NS)
    chosen = next((s for s in sheets if sheet is None or s.get("name") == sheet), None)
    if chosen is None:
        raise FeedError(f"xlsx has no sheet {sheet!r}")
    rels = _xml(archive, "xl/_rels/workbook.xml.rels")
    target = next(
        (
            r.get("Target")
            for r in rels.findall("rel:Relationship", _NS)
            if r.get("Id") == chosen.get(_R_ID)
        ),
        None,
    )
    if not target:
        raise FeedError("xlsx workbook relationship for the sheet is missing")
    target = str(target)
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")


def _column_index(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch) - ord("A") + 1
    return index - 1


def _number(raw: str) -> object:
    """A numeric cell as an exact string (integers without '.0', GTINs without exponent)."""
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return raw
    if value == value.to_integral_value():
        return str(int(value))
    return str(value.normalize())


def _cell(cell: Any, shared: list[str]) -> object:
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        node = cell.find("m:is", _NS)
        return _text(node) if node is not None else None
    value = cell.find("m:v", _NS)
    if value is None or value.text is None:
        return None
    raw: str = value.text
    if kind == "s":
        return shared[int(raw)]
    if kind == "b":
        return raw == "1"
    if kind in {"str", "e"}:
        return raw
    return _number(raw)


def read_xlsx(path: Path, *, sheet: str | None = None) -> Iterator[NumberedRow]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise FeedError(f"{path.name} is not an xlsx file") from exc
    with archive:
        shared = (
            [_text(si) for si in _xml(archive, "xl/sharedStrings.xml").findall("m:si", _NS)]
            if "xl/sharedStrings.xml" in archive.namelist()
            else []
        )
        rows = _xml(archive, _sheet_member(archive, sheet)).findall("m:sheetData/m:row", _NS)
    header: list[str] | None = None
    for row in rows:
        cells: dict[int, object] = {}
        for cell in row.findall("m:c", _NS):
            match = _CELL_REF.match(cell.get("r", ""))
            if match is None:
                raise FeedError(f"xlsx cell without a reference in row {row.get('r')}")
            cells[_column_index(match.group(1))] = _cell(cell, shared)
        number = int(row.get("r"))
        if header is None:
            header = [str(cells.get(i) or "").strip() for i in range(max(cells, default=-1) + 1)]
            continue
        if any(i >= len(header) or not header[i] for i, v in cells.items() if v is not None):
            raise FeedError(f"row {number}: value in a column without a header")
        yield number, {name: cells.get(i) for i, name in enumerate(header) if name}
