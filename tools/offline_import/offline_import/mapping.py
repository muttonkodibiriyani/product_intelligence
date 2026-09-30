"""Column-mapping config: which feed column holds which of our fields, and how to read it.

Loaded from JSON, or from YAML when PyYAML is installed (it is not a workspace dependency).
Unknown keys are an error everywhere (``PiModel``), so a typo cannot silently drop a column.
"""

import importlib
import json
import re
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from pi_core import AvailabilityState, Channel, Market, PiModel, SourceKind
from pi_core.types import CurrencyCode, UtcDatetime

# States a feed value may map to. REMOVED and BLOCKED are never read from a partner file:
# absence from an import is not removal, and nothing was fetched that could be blocked.
FEED_AVAILABILITY: frozenset[AvailabilityState] = frozenset(
    {
        AvailabilityState.IN_STOCK,
        AvailabilityState.LOW_STOCK,
        AvailabilityState.OUT_OF_STOCK,
        AvailabilityState.NOT_DELIVERABLE,
        AvailabilityState.NOT_OBSERVED,
        AvailabilityState.UNKNOWN,
    }
)

Format = Literal["csv", "xlsx", "json"]
FORMAT_BY_SUFFIX: dict[str, Format] = {".csv": "csv", ".xlsx": "xlsx", ".json": "json"}


class SourceSpec(PiModel):
    """The ``source`` row the feed belongs to (matched by name, created when missing)."""

    name: str = Field(min_length=1)
    kind: SourceKind = SourceKind.OFFLINE
    base_url: str | None = None
    notes: str | None = None


class Columns(PiModel):
    """Our field -> feed column name. Only ``listing_key`` is required."""

    listing_key: str
    sku: str | None = None
    gtin: str | None = None
    url: str | None = None
    name: str | None = None
    name_ar: str | None = None
    brand: str | None = None
    category_path: str | None = None
    size: str | None = None
    shade: str | None = None
    price_current: str | None = None
    price_regular: str | None = None
    price_promo: str | None = None
    availability: str | None = None
    stock_qty: str | None = None
    image_url: str | None = None
    observed_at: str | None = None

    def mapped(self) -> dict[str, str]:
        """Field -> column for every mapped field."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class CsvOptions(PiModel):
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    # utf-8-sig also reads plain UTF-8 and drops the BOM spreadsheet exports often add.
    encoding: str = "utf-8-sig"


class ImportMapping(PiModel):
    """Everything needed to turn one feed file into pi_db rows."""

    source: SourceSpec
    country: str = Field(pattern=r"^[A-Z]{2}$")
    locale: str = Field(min_length=2)  # plain tag, e.g. "en-AE"
    currency: CurrencyCode
    time_zone: str
    channel: Channel = Channel.ONLINE
    # When the feed's prices were valid. A fixed instant here, or a per-row column
    # (``columns.observed_at``); never the import time, so a replay keeps the same key.
    observed_at: UtcDatetime | None = None
    # Only a feed the partner states is its whole catalogue closes the run as 'succeeded'.
    # Otherwise the run is 'partial': absence from a feed is never read as removal.
    complete_catalogue: bool = False
    columns: Columns
    format: Format | None = None  # default: from the file suffix
    csv: CsvOptions = Field(default_factory=CsvOptions)
    # JSON: dotted path to the item array ("items", "data.products"); None = top-level array.
    json_items_path: str | None = None
    xlsx_sheet: str | None = None  # default: the first sheet
    decimal_separator: Literal[".", ","] = "."
    # Feed value (case-insensitive, stripped) -> availability state.
    availability_map: dict[str, AvailabilityState] = Field(default_factory=dict)
    # Used when the feed has no url column; {listing_key} and {sku} are substituted.
    url_template: str | None = None

    @field_validator("time_zone")
    @classmethod
    def _check_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown time zone {value!r}"
            raise ValueError(msg) from exc
        return value

    @field_validator("availability_map")
    @classmethod
    def _check_availability_map(
        cls, value: dict[str, AvailabilityState]
    ) -> dict[str, AvailabilityState]:
        bad = sorted(k for k, v in value.items() if v not in FEED_AVAILABILITY)
        if bad:
            msg = f"availability values {bad} map to a state a feed cannot assert"
            raise ValueError(msg)
        return {k.strip().lower(): v for k, v in value.items()}

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.observed_at is None and self.columns.observed_at is None:
            msg = "set observed_at or map columns.observed_at (import time is never used)"
            raise ValueError(msg)
        if self.columns.availability is not None and not self.availability_map:
            msg = "columns.availability needs an availability_map"
            raise ValueError(msg)
        market = next((m for m in Market if m.value == self.country), None)
        if market is not None and market.currency != self.currency:
            msg = f"{self.country} prices are in {market.currency}, not {self.currency}"
            raise ValueError(msg)
        if self.url_template is not None and re.search(
            r"\{(?!listing_key\}|sku\})", self.url_template
        ):
            msg = "url_template may only use {listing_key} and {sku}"
            raise ValueError(msg)
        # Listing URLs are published; a local path or other scheme must never become one.
        if self.columns.url is None and self.url_template is None:
            msg = "map columns.url or set url_template (an http(s) listing URL is required)"
            raise ValueError(msg)
        if self.url_template is not None and not is_http_url(self.url_template):
            msg = "url_template must be an http(s) URL"
            raise ValueError(msg)
        return self

    @property
    def prices_mapped(self) -> bool:
        c = self.columns
        return any(col is not None for col in (c.price_current, c.price_regular, c.price_promo))

    def format_for(self, path: Path) -> Format:
        if self.format is not None:
            return self.format
        try:
            return FORMAT_BY_SUFFIX[path.suffix.lower()]
        except KeyError:
            msg = f"cannot tell the format of {path.name}; set 'format' in the mapping"
            raise ValueError(msg) from None


def is_http_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def load_mapping(path: Path) -> ImportMapping:
    """Read a mapping from ``.json``, or ``.yaml``/``.yml`` (needs PyYAML)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            yaml = importlib.import_module("yaml")
        except ModuleNotFoundError:
            msg = "YAML mappings need PyYAML, which is not installed; use a .json mapping"
            raise ValueError(msg) from None
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return ImportMapping.model_validate(data)
