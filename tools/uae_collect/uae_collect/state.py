"""What earlier runs read, per product URL; the input to the next run's selection.

Stored as ``state/<source>/urls.json.gz`` in the capture bucket, outside the dated run prefixes,
so it outlives any run-output lifecycle. A URL advances only when a run actually read it: a page
that was blocked, skipped or not reached keeps its old entry and is picked up again by the next
``daily`` pass. Nothing here ever marks a product removed or out of stock.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from uae_collect.shops import AR, DAILY, Shop

IN, OUT = "in", "out"
VERSION = 1


@dataclass(frozen=True)
class Entry:
    #: date (YYYY-MM-DD) of the last run that read the page; None if never read
    read: str | None = None
    #: the sitemap lastmod the page had when it was read
    lastmod: str | None = None
    #: ``in`` / ``out`` of the collection's scope once a reader has seen it (Ounass: beauty)
    scope: str | None = None


@dataclass
class State:
    urls: dict[str, Entry] = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        doc = {
            "version": VERSION,
            "urls": {
                u: {k: v for k, v in vars(e).items() if v is not None}
                for u, e in sorted(self.urls.items())
            },
        }
        return gzip.compress(json.dumps(doc, separators=(",", ":")).encode())

    @classmethod
    def from_bytes(cls, raw: bytes) -> State:
        doc: Any = json.loads(gzip.decompress(raw))
        if not isinstance(doc, dict) or doc.get("version") != VERSION:
            raise ValueError("state: unsupported document")
        return cls({u: Entry(**e) for u, e in doc["urls"].items()})

    def select(self, shop: Shop, run_pass: str, listed: Mapping[str, str | None]) -> list[str]:
        """The product URLs this pass reads, in sitemap order.

        ``listed`` is this run's sitemap (URL -> lastmod). URLs a reader found out of scope are
        never read again; a URL the sitemap no longer lists is not read (and not marked gone).
        """
        lang = "ar" if run_pass == AR else "en"
        out: list[str] = []
        for url, lastmod in listed.items():
            if shop.lang(url) != lang:
                continue
            entry = self.urls.get(url, Entry())
            if entry.scope == OUT:
                continue
            changed = shop.use_lastmod and lastmod is not None and lastmod != entry.lastmod
            if run_pass != DAILY or entry.read is None or changed:
                out.append(url)
        return out

    def record(
        self,
        day: str,
        listed: Mapping[str, str | None],
        read_ok: Iterable[str],
        out_of_scope: Iterable[str],
    ) -> None:
        """Advance the URLs this run read; mark the ones a reader put out of scope."""
        for url in read_ok:
            self.urls[url] = Entry(read=day, lastmod=listed.get(url), scope=IN)
        for url in out_of_scope:
            self.urls[url] = replace(
                self.urls.get(url, Entry()), read=day, lastmod=listed.get(url), scope=OUT
            )
