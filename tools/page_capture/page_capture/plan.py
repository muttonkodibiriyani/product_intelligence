"""The capture plan: what to fetch, read once and validated before the first request."""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

KINDS = ("html", "json", "xml")
GZIP_MAGIC = b"\x1f\x8b"


@dataclass(frozen=True)
class Item:
    id: str
    url: str
    locale: str  # xx-RR, e.g. en-AE
    kind: str  # html | json | xml
    ref: Mapping[str, Any] = field(default_factory=dict)
    images: tuple[str, ...] = ()
    headers: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "url": self.url, "locale": self.locale}
        out["kind"] = self.kind
        out["ref"] = dict(self.ref)
        out["images"] = list(self.images)
        if self.headers:
            out["headers"] = dict(self.headers)
        return out


@dataclass(frozen=True)
class Plan:
    source: str
    retailer: str
    items: tuple[Item, ...]
    version: int = 1
    default_headers: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "retailer": self.retailer,
            "version": self.version,
            "default_headers": dict(self.default_headers),
            "items": [it.to_json() for it in self.items],
        }


def _http_url(url: Any, where: str) -> str:
    if not isinstance(url, str):
        raise ValueError(f"{where}: url must be a string")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{where}: not an http(s) URL: {url!r}")
    return url


def _str_map(value: Any, where: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ValueError(f"{where}: must be a string-to-string object")
    return dict(value)


def item_from_json(raw: Mapping[str, Any], where: str) -> Item:
    item_id = raw.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise ValueError(f"{where}: id must be a non-empty string")
    locale = raw.get("locale")
    if not isinstance(locale, str) or len(locale.split("-")) != 2:
        raise ValueError(f"{where}: locale must look like en-AE")
    kind = raw.get("kind", "html")
    if kind not in KINDS:
        raise ValueError(f"{where}: kind must be one of {KINDS}")
    ref = raw.get("ref")
    if ref is None:
        ref = {}
    if not isinstance(ref, dict):
        raise ValueError(f"{where}: ref must be an object")
    images_raw = raw.get("images") or []
    if not isinstance(images_raw, list):
        raise ValueError(f"{where}: images must be a list")
    images = tuple(_http_url(u, f"{where}.images") for u in images_raw)
    return Item(
        id=item_id,
        url=_http_url(raw.get("url"), where),
        locale=locale,
        kind=kind,
        ref=ref,
        images=images,
        headers=_str_map(raw.get("headers"), f"{where}.headers"),
    )


def plan_from_json(doc: Mapping[str, Any]) -> Plan:
    source, retailer = doc.get("source"), doc.get("retailer")
    if not isinstance(source, str) or not source or not isinstance(retailer, str) or not retailer:
        raise ValueError("plan: source and retailer must be non-empty strings")
    version = doc.get("version", 1)
    if version != 1:
        raise ValueError(f"plan: unsupported version {version!r}")
    items_raw = doc.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise ValueError("plan: items must be a non-empty list")
    items = tuple(item_from_json(it, f"items[{i}]") for i, it in enumerate(items_raw))
    ids = [it.id for it in items]
    if len(set(ids)) != len(ids):
        dup = next(i for i in ids if ids.count(i) > 1)
        raise ValueError(f"plan: duplicate item id {dup!r}")
    return Plan(
        source=source,
        retailer=retailer,
        items=items,
        version=1,
        default_headers=_str_map(doc.get("default_headers"), "plan.default_headers"),
    )


def parse_plan(raw: bytes) -> Plan:
    """A plan document, plain or gzipped JSON."""
    data = gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise ValueError("plan: top level must be an object")
    return plan_from_json(doc)


def shard(items: Sequence[Item], index: int, count: int) -> list[Item]:
    """Item ``i`` belongs to task ``i mod count`` (Cloud Run task sharding)."""
    if count < 1 or not 0 <= index < count:
        raise ValueError(f"shard {index}/{count} is not a valid task index")
    return [it for i, it in enumerate(items) if i % count == index]
