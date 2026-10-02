"""Readings and page captures: raw text beside the normalised value, with an explicit state.

A ``Reading`` is one attribute read from one page. Its invariants are the registry's storage
rules plus the capture principle's "record what we expected and did not find":

* the key must be registered and the level must be the attribute's own level;
* ``observed`` carries the retailer's raw text and/or a normalised value;
* ``parse_failed`` keeps the raw text that could not be normalised and no value;
* ``not_shown``, ``blocked`` and ``not_applicable`` carry neither;
* values are JSON-shaped, money and other exact numbers are ``Decimal`` (floats and non-finite
  decimals are refused); a money reading carries its ``currency`` as a field beside the amount.

A ``ProductCapture`` is everything read from one page in one visit, plus ``looked_for``: the
keys the extractor that produced it knows how to read, so a coverage report can tell "not on the
page" from "nobody looked". JSON serialisation keeps ``Decimal`` exact as ``{"$decimal": "12.500"}``
and datetimes as UTC ISO-8601 strings; any scraped object key that starts with ``$`` is escaped
with a second ``$`` on the way out, so scraped content can never be mistaken for the tag.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast, get_args

from pi_capture.registry import AttributeLevel, get
from pi_core.markets import check_locale

ReadingState = Literal["observed", "not_shown", "blocked", "parse_failed", "not_applicable"]
READING_STATES: tuple[ReadingState, ...] = get_args(ReadingState)

CaptureState = Literal["ok", "blocked", "unparsed"]
CAPTURE_STATES: tuple[CaptureState, ...] = get_args(CaptureState)

type JsonValue = str | int | bool | Decimal | list[JsonValue] | dict[str, JsonValue] | None

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
DECIMAL_TAG = "$decimal"


class ReadingError(ValueError):
    """A reading that breaks a storage rule."""


def check_json_value(value: object, path: str = "value") -> None:
    """Refuse floats (and anything not JSON-shaped) anywhere inside ``value``."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ReadingError(f"{path}: NaN or infinite Decimal is not accepted")
        return
    if isinstance(value, bool | int | str) or value is None:
        return
    if isinstance(value, float):
        raise ReadingError(f"{path}: float is not accepted; use Decimal for exact numbers")
    if isinstance(value, list):
        for i, item in enumerate(value):
            check_json_value(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for k, item in value.items():
            if not isinstance(k, str):
                raise ReadingError(f"{path}: object keys must be strings")
            check_json_value(item, f"{path}.{k}")
        return
    raise ReadingError(f"{path}: {type(value).__name__} is not a JSON value")


@dataclass(frozen=True, slots=True)
class Reading:
    key: str
    level: AttributeLevel
    state: ReadingState
    raw_text: str | None = None
    value: JsonValue = None
    #: Where on the page it came from, e.g. ``jsonld[0].offers.price`` or ``meta[og:title]``.
    source_path: str | None = None
    note: str | None = None
    #: ISO 4217 code beside a money amount; only an observed or parse_failed reading carries one.
    currency: str | None = None

    def __post_init__(self) -> None:
        attribute = get(self.key)  # UnknownAttributeError for an unregistered key
        if self.level != attribute.level:
            raise ReadingError(f"{self.key} belongs to level {attribute.level}, not {self.level}")
        if self.state not in READING_STATES:
            raise ReadingError(f"{self.key}: unknown state {self.state!r}")
        check_json_value(self.value, f"{self.key}.value")
        if self.currency is not None:
            if not _CURRENCY_RE.match(self.currency):
                raise ReadingError(
                    f"{self.key}: currency must be a 3-letter code, not {self.currency!r}"
                )
            if self.state not in {"observed", "parse_failed"}:
                raise ReadingError(f"{self.key}: state {self.state} cannot carry a currency")
        if self.state == "observed":
            if self.raw_text is None and self.value is None:
                raise ReadingError(f"{self.key}: an observed reading needs raw text or a value")
            return
        if self.value is not None:
            raise ReadingError(f"{self.key}: state {self.state} cannot carry a value")
        if self.state == "parse_failed" and self.raw_text is None:
            raise ReadingError(f"{self.key}: parse_failed must keep the raw text that failed")
        if self.state != "parse_failed" and self.raw_text is not None:
            raise ReadingError(f"{self.key}: state {self.state} cannot carry raw text")


@dataclass(frozen=True, slots=True)
class ProductCapture:
    """One page, one visit: where it was read from and every reading taken."""

    source: str
    retailer: str
    url: str
    locale: str
    retrieved_at: datetime
    egress: str
    page_sha256: str
    readings: tuple[Reading, ...] = ()
    capture_state: CaptureState = "ok"
    #: Registry keys the extractor tried to read on this page; empty means "not recorded".
    looked_for: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("source", "retailer", "url", "egress"):
            if not getattr(self, name):
                raise ReadingError(f"capture {name} must not be empty")
        check_locale(self.locale)
        if self.retrieved_at.tzinfo is None:
            raise ReadingError("retrieved_at must be timezone-aware")
        object.__setattr__(self, "retrieved_at", self.retrieved_at.astimezone(UTC))
        if not _SHA256_RE.match(self.page_sha256):
            raise ReadingError("page_sha256 must be a lowercase SHA-256 hex digest")
        if self.capture_state not in CAPTURE_STATES:
            raise ReadingError(f"unknown capture_state {self.capture_state!r}")
        if self.capture_state != "ok" and self.readings:
            raise ReadingError(f"a {self.capture_state} capture has no readings")
        for key in self.looked_for:
            get(key)  # UnknownAttributeError for an unregistered key
        object.__setattr__(self, "looked_for", tuple(sorted(set(self.looked_for))))
        seen: set[tuple[str, str | None]] = set()
        for r in self.readings:
            if (r.key, r.source_path) in seen:
                raise ReadingError(f"duplicate reading {r.key} from {r.source_path!r}")
            seen.add((r.key, r.source_path))

    def by_key(self) -> Mapping[str, tuple[Reading, ...]]:
        out: dict[str, list[Reading]] = {}
        for r in self.readings:
            out.setdefault(r.key, []).append(r)
        return {k: tuple(v) for k, v in out.items()}


# ---------------------------------------------------------------------------- JSON
def encode_value(value: JsonValue) -> Any:
    """``Decimal`` -> ``{"$decimal": "…"}``; containers recursively; scalars unchanged.

    A scraped object key that starts with ``$`` gets one more ``$`` so it can never be read back
    as the decimal tag: ``{"$decimal": "x"}`` from a page round-trips as that very dict.
    """
    if isinstance(value, Decimal):
        return {DECIMAL_TAG: str(value)}
    if isinstance(value, list):
        return [encode_value(v) for v in value]
    if isinstance(value, dict):
        return {("$" + k if k.startswith("$") else k): encode_value(v) for k, v in value.items()}
    return value


def decode_value(data: Any, path: str = "value") -> JsonValue:
    """Inverse of :func:`encode_value`; floats in the input are refused, not rounded."""
    if isinstance(data, float):
        raise ReadingError(f"{path}: float is not accepted")
    if isinstance(data, list):
        return [decode_value(v, f"{path}[{i}]") for i, v in enumerate(data)]
    if isinstance(data, dict):
        if set(data) == {DECIMAL_TAG}:
            try:
                dec = Decimal(str(data[DECIMAL_TAG]))
            except InvalidOperation:
                raise ReadingError(f"{path}: bad decimal {data[DECIMAL_TAG]!r}") from None
            if not dec.is_finite():
                raise ReadingError(f"{path}: bad decimal {data[DECIMAL_TAG]!r}")
            return dec
        out: dict[str, JsonValue] = {}
        for k, v in data.items():
            key = str(k)
            if key.startswith("$$"):
                key = key[1:]
            elif key.startswith("$"):
                raise ReadingError(f"{path}: unescaped tag key {key!r}")
            out[key] = decode_value(v, f"{path}.{key}")
        return out
    return cast(JsonValue, data)


def reading_to_json(reading: Reading) -> dict[str, Any]:
    data = asdict(reading)
    data["level"] = str(reading.level)
    data["value"] = encode_value(reading.value)
    return data


def reading_from_json(data: Mapping[str, Any]) -> Reading:
    return Reading(
        key=str(data["key"]),
        level=AttributeLevel(str(data["level"])),
        state=cast(ReadingState, data["state"]),
        raw_text=data.get("raw_text"),
        value=decode_value(data.get("value")),
        source_path=data.get("source_path"),
        note=data.get("note"),
        currency=data.get("currency"),
    )


def capture_to_json(capture: ProductCapture) -> dict[str, Any]:
    return {
        "source": capture.source,
        "retailer": capture.retailer,
        "url": capture.url,
        "locale": capture.locale,
        "retrieved_at": capture.retrieved_at.isoformat(),
        "egress": capture.egress,
        "page_sha256": capture.page_sha256,
        "capture_state": capture.capture_state,
        "looked_for": list(capture.looked_for),
        "readings": [reading_to_json(r) for r in capture.readings],
    }


def capture_from_json(data: Mapping[str, Any]) -> ProductCapture:
    return ProductCapture(
        source=str(data["source"]),
        retailer=str(data["retailer"]),
        url=str(data["url"]),
        locale=str(data["locale"]),
        retrieved_at=datetime.fromisoformat(str(data["retrieved_at"])),
        egress=str(data["egress"]),
        page_sha256=str(data["page_sha256"]),
        readings=tuple(reading_from_json(r) for r in data.get("readings", [])),
        capture_state=cast(CaptureState, data.get("capture_state", "ok")),
        looked_for=tuple(str(k) for k in data.get("looked_for", [])),
    )


def _refuse_constant(token: str) -> Any:
    raise ReadingError(f"{token} is not accepted in a capture line")


def dumps(capture: ProductCapture) -> str:
    """One JSON line per capture (no float can appear: Decimals are tagged strings)."""
    return json.dumps(capture_to_json(capture), ensure_ascii=False, separators=(",", ":"))


def loads(line: str) -> ProductCapture:
    data = json.loads(line, parse_float=Decimal, parse_constant=_refuse_constant)
    if not isinstance(data, dict):
        raise ReadingError("a capture line must be a JSON object")
    return capture_from_json(data)


def load_lines(lines: Iterable[str]) -> list[ProductCapture]:
    return [loads(line) for line in lines if line.strip()]
