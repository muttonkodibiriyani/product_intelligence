"""The shops the recurring collection covers, and which pass each one runs on a given day.

A pass is one of:

- ``daily``: product URLs the shop's sitemap lists that no earlier run has read yet (new
  products, and pages an earlier run did not get to); with ``use_lastmod``, also URLs whose
  sitemap ``<lastmod>`` changed since they were read.
- ``full``: every in-scope English product URL the sitemap lists. Only a full pass can show the
  whole catalogue, so only a full pass with no gap may say ``complete_catalogue``.
- ``ar``: every in-scope Arabic product URL; captured and read, but not fed (the feed and the
  importer take the shop's English locale only).

The schedule starts the job once a day; the job picks its pass from the date, so one Scheduler
job per shop needs only ``run.invoker`` (no per-run overrides).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

DAILY, FULL, AR = "daily", "full", "ar"
PASSES = (DAILY, FULL, AR)
LOCALES = {"en": "en-AE", "ar": "ar-AE"}


@dataclass(frozen=True)
class Shop:
    #: ``source.name`` in pi_db and the pi_capture.feed shop key
    source: str
    #: page_capture / capture_read retailer key (selects the reader)
    retailer: str
    #: sitemap (or sitemap index) URLs, read every run
    sitemaps: tuple[str, ...]
    #: a product page URL; group ``lang`` is the page language (``en`` / ``ar``)
    product: re.Pattern[str]
    #: weekdays (0 = Monday) with a full English pass
    full_weekdays: frozenset[int]
    #: day of the month with the Arabic pass
    ar_day: int
    #: whether ``<lastmod>`` is a usable change signal for this shop
    use_lastmod: bool
    #: seconds between requests (page_capture's floor is 1.0; robots Crawl-delay still wins)
    pace_s: float

    def pass_for(self, day: date) -> str:
        """The pass for ``day`` (UTC): Arabic beats full beats daily."""
        if day.day == self.ar_day:
            return AR
        if day.weekday() in self.full_weekdays:
            return FULL
        return DAILY

    def lang(self, url: str) -> str | None:
        """``en`` / ``ar`` for a product page URL, else None."""
        m = self.product.match(url)
        return m.group("lang") if m else None


SHOPS: dict[str, Shop] = {
    # Measured 2026-10-07: the EN sitemap index lists 5,878 URLs, 1,480 en/p and 1,480 ar/p,
    # every one with a lastmod, but 940 of the 1,458 products captured on 10-02 carry the same
    # 2026-10-06 lastmod: it is touched in bulk, so it is not a change signal. The catalogue is
    # small (~40 min at 1.5 s), so twice-weekly full passes plus daily new URLs.
    "faces_ae": Shop(
        source="faces_ae",
        retailer="faces",
        sitemaps=("https://www.faces.ae/en/sitemap_index.xml",),
        product=re.compile(r"^https://www\.faces\.ae/(?P<lang>en|ar)/p/[^/?#]+\.html$"),
        full_weekdays=frozenset({0, 3}),  # Monday, Thursday
        ar_day=1,
        use_lastmod=False,
        pace_s=1.5,
    ),
}
