"""Row validation and the import report. Pure: nothing here touches the database.

A row is rejected (never loaded) for a missing listing key, a duplicate listing key, a price or
stock quantity that does not parse, a price that is zero or negative, an availability value the
mapping does not know, or an unreadable observed_at. Everything else that is merely incomplete
is a warning: missing is data, recorded later as a field_state reason, never as zero.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from offline_import.mapping import ImportMapping, is_http_url
from offline_import.readers import NumberedRow, Row, read_rows
from pi_core import AvailabilityState, is_valid_gtin

PRICE_FIELDS = ("price_current", "price_regular", "price_promo")
# numeric(18,4): refuse anything the column would round or overflow.
_MAX_PRICE = Decimal(10) ** 14
_PRICE_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class ImportRow:
    """One accepted row, normalised. Prices are None (not published) or > 0."""

    row: int
    listing_key: str
    observed_at: datetime
    availability: AvailabilityState
    availability_observed: bool
    price_current: Decimal | None
    price_regular: Decimal | None
    price_promo: Decimal | None
    stock_qty: int | None
    text: dict[str, str | None]  # sku, gtin, url, name, name_ar, brand, category_path, ...


@dataclass
class Issue:
    row: int
    listing_key: str | None
    message: str


@dataclass
class Rejection:
    row: int
    listing_key: str | None
    reasons: list[str]


@dataclass
class ImportReport:
    file: str
    sha256: str
    format: str
    rows: int = 0
    accepted: list[ImportRow] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "sha256": self.sha256,
            "format": self.format,
            "rows": self.rows,
            "accepted": len(self.accepted),
            "rejected": [
                {"row": r.row, "listing_key": r.listing_key, "reasons": r.reasons}
                for r in self.rejected
            ],
            "warnings": [
                {"row": w.row, "listing_key": w.listing_key, "message": w.message}
                for w in self.warnings
            ],
        }

    def summary(self) -> str:
        lines = [
            f"{self.file} ({self.format}, sha256 {self.sha256[:12]}…): {self.rows} rows,"
            f" {len(self.accepted)} accepted, {len(self.rejected)} rejected,"
            f" {len(self.warnings)} warnings",
        ]
        lines += [f"  rejected row {r.row}: {'; '.join(r.reasons)}" for r in self.rejected[:20]]
        lines += [f"  warning row {w.row}: {w.message}" for w in self.warnings[:20]]
        if len(self.rejected) > 20 or len(self.warnings) > 20:
            lines.append("  … (see the JSON report for the full list)")
        return "\n".join(lines)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object) -> str | None:
    """Stripped text; blank is None."""
    if value is None:
        return None
    text = str(value).lower() if isinstance(value, bool) else str(value).strip()
    return text or None


def parse_decimal(value: object, decimal_separator: str) -> Decimal | None:
    """None for blank; raises ValueError when present but not a number."""
    if isinstance(value, bool):
        raise ValueError(f"{value!r} is not a number")
    if isinstance(value, int | Decimal):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = _text(value)
    if text is None:
        return None
    thousands = "," if decimal_separator == "." else "."
    cleaned = text.replace(" ", "").replace("\N{NO-BREAK SPACE}", "").replace(thousands, "")
    if decimal_separator == ",":
        cleaned = cleaned.replace(",", ".")
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"{text!r} is not a number") from None
    if not number.is_finite():
        raise ValueError(f"{text!r} is not a number")
    return number


def _price(value: object, name: str, mapping: ImportMapping, reasons: list[str]) -> Decimal | None:
    try:
        price = parse_decimal(value, mapping.decimal_separator)
    except ValueError as exc:
        reasons.append(f"bad {name}: {exc}")
        return None
    if price is None:
        return None
    if price <= 0:
        reasons.append(f"{name} must be > 0 (got {price}); leave it blank when not published")
        return None
    if price >= _MAX_PRICE or price != price.quantize(_PRICE_QUANTUM):
        reasons.append(f"{name} {price} does not fit numeric(18,4)")
        return None
    return price


def _observed_at(value: object, mapping: ImportMapping, reasons: list[str]) -> datetime | None:
    if mapping.columns.observed_at is None:
        return mapping.observed_at
    text = _text(value)
    if text is None:
        if mapping.observed_at is None:
            reasons.append("missing observed_at")
        return mapping.observed_at
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        reasons.append(f"bad observed_at {text!r} (ISO 8601 expected)")
        return None
    if at.tzinfo is None:  # a local time in the feed's market
        at = at.replace(tzinfo=ZoneInfo(mapping.time_zone))
    return at.astimezone(UTC)


class _Validator:
    def __init__(self, mapping: ImportMapping, report: ImportReport) -> None:
        self.m = mapping
        self.report = report
        self.cols = mapping.columns.mapped()
        self.seen: dict[str, int] = {}
        self.columns_seen: set[str] = set()

    def row(self, number: int, raw: Row) -> None:
        self.report.rows += 1
        self.columns_seen.update(raw)
        get = {f: raw.get(c) for f, c in self.cols.items()}
        key = _text(get.get("listing_key"))
        reasons: list[str] = []
        warnings: list[str] = []
        if key is None:
            reasons.append("missing listing_key")
        elif key in self.seen:
            reasons.append(f"duplicate listing_key (first at row {self.seen[key]})")
        else:
            self.seen[key] = number
        prices = {f: _price(get.get(f), f, self.m, reasons) for f in PRICE_FIELDS}
        stock = self._stock(get.get("stock_qty"), reasons)
        state, observed = self._availability(get.get("availability"), stock, reasons)
        at = _observed_at(get.get("observed_at"), self.m, reasons)
        text = {
            f: _text(get.get(f))
            for f in self.cols
            if f not in {*PRICE_FIELDS, "listing_key", "stock_qty", "availability", "observed_at"}
        }
        url = text.get("url")
        if url is not None and not is_http_url(url):
            if self.m.url_template is None:
                reasons.append(f"url {url!r} is not an http(s) URL")
            else:
                warnings.append(f"url {url!r} is not an http(s) URL; url_template used")
                text["url"] = None
        elif url is None and self.m.url_template is None:
            reasons.append("missing url and no url_template")
        gtin = text.get("gtin")
        if gtin is not None and not is_valid_gtin(gtin):
            warnings.append(f"gtin {gtin!r} is not a valid GTIN; dropped")
            text["gtin"] = None
        if reasons or key is None or at is None:
            self.report.rejected.append(Rejection(number, key, reasons))
            return
        current = prices["price_current"] or prices["price_promo"] or prices["price_regular"]
        if current is None:
            warnings.append("no price published")
        promo, regular = prices["price_promo"], prices["price_regular"]
        if promo is not None and regular is not None and promo >= regular:
            warnings.append(f"price_promo {promo} is not below price_regular {regular}")
        if not text.get("name"):
            warnings.append("no product name")
        self.report.warnings += [Issue(number, key, w) for w in warnings]
        self.report.accepted.append(
            ImportRow(
                row=number,
                listing_key=key,
                observed_at=at,
                availability=state,
                availability_observed=observed,
                price_current=current,
                price_regular=regular,
                price_promo=promo,
                stock_qty=stock,
                text=text,
            )
        )

    def _stock(self, value: object, reasons: list[str]) -> int | None:
        try:
            qty = parse_decimal(value, self.m.decimal_separator)
        except ValueError as exc:
            reasons.append(f"bad stock_qty: {exc}")
            return None
        if qty is None:
            return None
        if qty < 0 or qty != qty.to_integral_value():
            reasons.append(f"bad stock_qty: {qty} is not a whole number >= 0")
            return None
        return int(qty)

    def _availability(
        self, value: object, stock: int | None, reasons: list[str]
    ) -> tuple[AvailabilityState, bool]:
        """(state, observed). Nothing published -> NOT_OBSERVED, never out of stock."""
        text = _text(value)
        if text is not None:
            state = self.m.availability_map.get(text.lower())
            if state is None:
                reasons.append(f"unknown availability value {text!r}")
                return AvailabilityState.NOT_OBSERVED, False
            known = state not in {AvailabilityState.NOT_OBSERVED, AvailabilityState.UNKNOWN}
            return state, known
        if stock is not None:  # the feed states a quantity: zero is an explicit stock-out
            return (
                AvailabilityState.IN_STOCK if stock > 0 else AvailabilityState.OUT_OF_STOCK
            ), True
        return AvailabilityState.NOT_OBSERVED, False

    def finish(self) -> None:
        if self.report.rows == 0:
            return
        for f, column in self.cols.items():
            if column not in self.columns_seen:
                self.report.warnings.append(
                    Issue(0, None, f"mapped column {column!r} ({f}) is not in the file")
                )


def validate_rows(
    rows: Iterable[NumberedRow], mapping: ImportMapping, report: ImportReport
) -> ImportReport:
    validator = _Validator(mapping, report)
    for number, raw in rows:
        validator.row(number, raw)
    validator.finish()
    return report


def validate_file(path: Path, mapping: ImportMapping) -> ImportReport:
    """Read and validate ``path``; the dry run. Never connects to a database."""
    report = ImportReport(file=str(path), sha256=file_sha256(path), format=mapping.format_for(path))
    return validate_rows(read_rows(path, mapping), mapping, report)
