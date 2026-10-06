"""Turn pi_capture readings into an ``offline_import`` JSON feed and its column mapping.

One row per captured page, keyed by the page's ``retailer_sku``. Only ``observed`` readings fill a
column; every other state leaves the column out, so ``offline_import`` records the gap (a missing
price is ``not_published``, never 0). Nothing is guessed:

- A page with no ``retailer_sku``, a duplicate key, or a price in a currency other than the feed's
  is left out of the feed and listed in ``excluded`` with its reason. Leaving a row out is absence,
  which the importer never reads as removal; a wrong-currency price is never relabelled.
- ``observed_at`` is the page's capture time, never the time the feed was built.
- Availability is only what the page itself stated in its structured product data, and only when
  the shop's settings trust that statement. Every statement on the page must agree (JSON-LD
  ``availability`` and a dataLayer ``item_in_stock`` flag alike); otherwise, or with none, the
  column is absent (``not_observed``). Absence is never read as a stock-out.
- Page content goes in as the page states it: the description, gender (the page's department),
  concentration, badges, the gift-with-purchase label as a promotion, and the whole gallery
  (``image_urls``, page order; ``image_url`` stays its first image). ``badges``, ``promotions``
  and ``image_urls`` are lists.
- The feed claims the whole catalogue (``complete_catalogue``) only when :func:`completeness`
  says one capture run fetched and read every product URL its sitemap lists. Anything less, or
  no sitemap, stays partial, so the importer records the run as ``partial``.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pi_capture.model import JsonValue, ProductCapture, Reading
from pi_core.money import CURRENCY_EXPONENTS

__all__ = [
    "AVAILABILITY_MAP",
    "COLUMNS",
    "SHOPS",
    "Completeness",
    "FeedResult",
    "Shop",
    "build_feed",
    "completeness",
    "mapping_for",
]

#: The feed's column names; each is also the ``offline_import`` field it maps to.
COLUMNS: tuple[str, ...] = (
    "listing_key",
    "sku",
    "gtin",
    "url",
    "name",
    "brand",
    "category_path",
    "size",
    "shade",
    "price_current",
    "price_regular",
    "price_promo",
    "availability",
    "image_url",
    "observed_at",
    "description",
    "gender",
    "concentration",
    "badges",
    "promotions",
    "image_urls",
)

#: Feed column -> the reading that fills it, as text.
_TEXT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("gtin", "gtin"),
    ("name", "title"),
    ("brand", "brand"),
    ("shade", "shade_name"),
    ("description", "description"),
    ("gender", "department"),
    ("concentration", "concentration"),
)

Row = dict[str, str | list[str]]

#: schema.org availability (the last path segment) to the importer's states. A value outside this
#: map is never written: the importer would reject the row, and guessing a state is worse.
AVAILABILITY_MAP: dict[str, str] = {
    "instock": "in_stock",
    "limitedavailability": "low_stock",
    "outofstock": "out_of_stock",
    "soldout": "out_of_stock",
}

#: A dataLayer ``item_in_stock`` flag in the same tokens as schema.org availability.
_STOCK_FLAG = {True: "instock", False: "outofstock"}


@dataclass(frozen=True)
class Shop:
    """One shop in one country: its own ``source.name`` and market settings."""

    source: str
    base_url: str
    country: str
    locale: str
    currency: str
    time_zone: str
    notes: str
    #: Use the availability the page states in its structured data.
    markup_availability: bool = False


SHOPS: dict[str, Shop] = {
    "faces_ae": Shop(
        source="faces_ae",
        base_url="https://www.faces.ae",
        country="AE",
        locale="en-AE",
        currency="AED",
        time_zone="Asia/Dubai",
        notes="Faces UAE (Chalhoub), product pages captured by pi_capture (task 01a0fc6d)",
        # per page, from the page's own JSON-LD and dataLayer only (coordinator ruling
        # 2026-10-06); the catalogue stays partial, so a missing page is never a stock-out
        markup_availability=True,
    ),
}


@dataclass
class FeedResult:
    rows: list[Row] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    #: per column: how many rows carry a value
    filled: Counter[str] = field(default_factory=Counter)
    #: availability values seen in markup that are not in ``AVAILABILITY_MAP``
    unmapped_availability: Counter[str] = field(default_factory=Counter)
    #: rows whose regular price was observed but not written, by reason
    regular_price_dropped: Counter[str] = field(default_factory=Counter)

    def report(self) -> dict[str, Any]:
        reasons = Counter(e["reason"] for e in self.excluded)
        return {
            "rows": len(self.rows),
            "excluded": len(self.excluded),
            "excluded_by_reason": dict(sorted(reasons.items())),
            "filled": {c: self.filled.get(c, 0) for c in COLUMNS},
            "unmapped_availability": dict(sorted(self.unmapped_availability.items())),
            "regular_price_dropped": dict(sorted(self.regular_price_dropped.items())),
        }


def _observed(by_key: Mapping[str, tuple[Reading, ...]], key: str) -> Reading | None:
    return next((r for r in by_key.get(key, ()) if r.state == "observed"), None)


def _text(value: JsonValue) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)
    return None


def _major(minor: JsonValue, currency: str) -> str | None:
    """``51500`` minor units of AED -> ``"515.00"``; non-integers and non-positives -> None."""
    if not isinstance(minor, int) or isinstance(minor, bool) or minor <= 0:
        return None
    exponent = CURRENCY_EXPONENTS[currency]
    return str(Decimal(minor).scaleb(-exponent).quantize(Decimal(1).scaleb(-exponent)))


def _availability(by_key: Mapping[str, tuple[Reading, ...]], unmapped: Counter[str]) -> str | None:
    """The single availability the structured data states; two different ones -> None.

    Read from schema.org ``availability`` values and from ``item_in_stock`` flags (the page's own
    stock flag), so a page whose JSON-LD and flag disagree states nothing usable. A flag that is
    present but not a boolean adds a token no map holds, so the page's stock is unknown and the
    token is counted in ``unmapped``.
    """
    found: set[str] = set()

    def walk(node: JsonValue) -> None:
        if isinstance(node, dict):
            value = node.get("availability")
            if isinstance(value, str) and value.strip():
                found.add(value.strip().rstrip("/").rsplit("/", 1)[-1].lower())
            if "item_in_stock" in node:
                flag = node["item_in_stock"]
                found.add(
                    _STOCK_FLAG[flag] if isinstance(flag, bool) else f"item_in_stock={flag!r}"
                )
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    for reading in by_key.get("structured_data", ()):
        if reading.state == "observed":
            walk(reading.value)
    for token in found - AVAILABILITY_MAP.keys():
        unmapped[token] += 1
    if len(found) != 1:
        return None
    (token,) = found
    return token if token in AVAILABILITY_MAP else None


def _price_columns(
    by_key: Mapping[str, tuple[Reading, ...]], currency: str, dropped: list[str]
) -> dict[str, str] | str:
    """The price columns, or the reason the row must be left out.

    A regular price is written (with the current price as the promotional one) only when it is
    strictly above the current price. offline_import stores any row with both columns as a
    promotion, so an equal or lower "was" price would invent one. Such cases are kept out and
    named in ``dropped`` instead.
    """
    current = _observed(by_key, "price_minor")
    regular = _observed(by_key, "regular_price_minor")
    for reading in (current, regular):
        if reading is not None and reading.currency != currency:
            return f"price in {reading.currency or 'no currency'}, feed is {currency}"
    out: dict[str, str] = {}
    now = _major(current.value, currency) if current else None
    was = _major(regular.value, currency) if regular else None
    if now is not None:
        out["price_current"] = now
    if was is not None and now is not None:
        if Decimal(was) > Decimal(now):
            out["price_regular"] = was
            out["price_promo"] = now
        elif Decimal(was) == Decimal(now):
            dropped.append("regular price equals current price")
        else:
            dropped.append("regular price below current price")
    return out


def _texts(value: JsonValue) -> list[str]:
    """A list reading's text items in page order, repeats left out."""
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = _text(item)
        if text is not None and text not in out:
            out.append(text)
    return out


def _row(
    capture: ProductCapture, shop: Shop, unmapped: Counter[str], dropped: list[str]
) -> Row | str:
    by_key = capture.by_key()
    sku = _observed(by_key, "retailer_sku")
    key = _text(sku.value) if sku else None
    if key is None:
        return "no retailer_sku on the page"
    prices = _price_columns(by_key, shop.currency, dropped)
    if isinstance(prices, str):
        return prices
    row: Row = {"listing_key": key, "sku": key}
    canonical = _observed(by_key, "canonical_url")
    row["url"] = (_text(canonical.value) if canonical else None) or capture.url
    for column, reading_key in _TEXT_COLUMNS:
        reading = _observed(by_key, reading_key)
        if reading is not None and (value := _text(reading.value)) is not None:
            row[column] = value
    category = _observed(by_key, "category_l1..l4")
    if category is not None and isinstance(category.value, list):
        parts = [p for p in (_text(v) for v in category.value) if p]
        if parts:
            row["category_path"] = " > ".join(parts)
    size = _observed(by_key, "size_label")
    if size is not None and (label := _text(size.value)) is not None:
        row["size"] = label
    images = _observed(by_key, "image_urls")
    gallery = _texts(images.value) if images is not None else []
    if gallery:
        row["image_url"] = gallery[0]
        row["image_urls"] = gallery
    badges = _observed(by_key, "badges")
    if badges is not None and (flags := _texts(badges.value)):
        row["badges"] = flags
    # the page's gift-with-purchase label (Faces: "Free Gifts"), a promotion, not a price
    gift = _observed(by_key, "gift_with_purchase")
    if gift is not None and (label := _text(gift.value)) is not None:
        row["promotions"] = [label]
    if shop.markup_availability and (state := _availability(by_key, unmapped)) is not None:
        row["availability"] = state
    row |= prices
    row["observed_at"] = capture.retrieved_at.isoformat()
    return row


#: :func:`build_feed` exclusion reasons that :func:`completeness` treats as read elsewhere
_OTHER_LOCALE = "locale "
_DUPLICATE_SKU = "duplicate retailer_sku"


def build_feed(captures: Iterable[ProductCapture], shop: Shop) -> FeedResult:
    """Feed rows for one shop and country, in capture order; the first page per key wins."""
    result = FeedResult()
    seen: set[str] = set()
    for capture in captures:
        if capture.locale != shop.locale:
            result.excluded.append(
                {"url": capture.url, "reason": f"{_OTHER_LOCALE}{capture.locale}"}
            )
            continue
        if capture.capture_state != "ok":
            result.excluded.append(
                {"url": capture.url, "reason": f"capture {capture.capture_state}"}
            )
            continue
        dropped: list[str] = []
        row = _row(capture, shop, result.unmapped_availability, dropped)
        if isinstance(row, str):
            result.excluded.append({"url": capture.url, "reason": row})
            continue
        key = str(row["listing_key"])
        if key in seen:
            result.excluded.append({"url": capture.url, "reason": _DUPLICATE_SKU})
            continue
        seen.add(key)
        result.regular_price_dropped.update(dropped)
        result.rows.append(row)
        result.filled.update(row.keys())
    return result


#: Feed exclusions that still leave the product read: the same page in another locale (the
#: shop's own locale is the one read) and a second URL of a SKU already in the feed.
#: :func:`build_feed` writes these reasons and :func:`completeness` reads them.
_READ_ELSEWHERE = (_OTHER_LOCALE, _DUPLICATE_SKU)


@dataclass(frozen=True)
class Completeness:
    """Did one capture run read the whole catalogue its sitemap lists?"""

    sitemap_urls: int
    #: why a sitemap product URL was not read, and how many: ``not_observed`` (no page row),
    #: a page state (``blocked``, ``rate_limited``, …), ``not_read`` (fetched, no readings) or
    #: a feed exclusion reason
    gaps: Mapping[str, int]

    @property
    def complete(self) -> bool:
        return self.sitemap_urls > 0 and not self.gaps

    def report(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "sitemap_urls": self.sitemap_urls,
            "gaps": dict(sorted(self.gaps.items())),
        }


def completeness(
    sitemap_urls: Iterable[str],
    pages: Iterable[Mapping[str, Any]],
    captures: Iterable[ProductCapture],
    result: FeedResult,
    shop: Shop,
) -> Completeness:
    """Complete only if every product URL of the measured sitemap was fetched ``ok`` in this one
    capture run (``pages``: the run's page rows), with none blocked or not observed, and each
    page in the shop's locale was read into the feed or left out only as a second URL of a SKU
    already in it (coordinator ruling 2026-10-06). The caller passes one run's page rows, i.e.
    one dated plan; the sitemap is the measured one, not the plan."""
    states: dict[str, set[str]] = {}
    fetched: dict[str, tuple[str, str]] = {}  # sitemap URL -> (URL read, page locale)
    for row in pages:
        url = str(row["url"])
        states.setdefault(url, set()).add(str(row.get("state")))
        if row.get("state") == "ok":
            fetched[url] = (str(row.get("final_url") or url), str(row.get("locale")))
    read = {c.url for c in captures if c.locale == shop.locale}
    gap_reasons: dict[str, set[str]] = {}  # URL -> every reason that leaves the product unread
    for e in result.excluded:
        reasons = gap_reasons.setdefault(e["url"], set())
        if not e["reason"].startswith(_READ_ELSEWHERE):
            reasons.add(e["reason"])
    gaps: Counter[str] = Counter()
    wanted = set(sitemap_urls)
    for url in wanted:
        if url not in states:
            gaps["not_observed"] += 1
            continue
        if url not in fetched:
            gaps[min(states[url])] += 1  # a stable name when one URL has several states
            continue
        final, locale = fetched[url]
        if locale != shop.locale:
            continue  # another locale's copy of a product: fetched is all it owes
        unread = gap_reasons.get(final)
        if unread:  # any real exclusion is a gap, whatever else the URL was excluded for
            gaps[min(unread)] += 1
        elif unread is None and final not in read:
            gaps["not_read"] += 1
    return Completeness(sitemap_urls=len(wanted), gaps=dict(gaps))


def mapping_for(shop: Shop, *, complete: bool = False) -> dict[str, Any]:
    """The ``offline_import`` mapping for a feed built by :func:`build_feed`; ``complete`` only
    from a :func:`completeness` that says so."""
    mapping: dict[str, Any] = {
        "source": {
            "name": shop.source,
            "kind": "web",
            "base_url": shop.base_url,
            "notes": shop.notes,
        },
        "country": shop.country,
        "locale": shop.locale,
        "currency": shop.currency,
        "time_zone": shop.time_zone,
        "complete_catalogue": complete,
        "format": "json",
        "json_items_path": "items",
        "columns": {c: c for c in COLUMNS},
    }
    if shop.markup_availability:
        mapping["availability_map"] = dict(AVAILABILITY_MAP)
    else:
        del mapping["columns"]["availability"]
    return mapping


def dump_feed(result: FeedResult, shop: Shop) -> str:
    """The feed file: ``{"shop": …, "items": [...]}``, keys sorted, UTF-8 kept readable."""
    return json.dumps(
        {"shop": shop.source, "items": result.rows}, ensure_ascii=False, sort_keys=True, indent=1
    )


def _page_rows(path: Path) -> list[dict[str, Any]]:
    """A page_capture ``pages/part-*.jsonl[.gz]`` file's rows."""
    raw = path.read_bytes()
    text = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m pi_capture.feed <shop> <readings.jsonl> <out_dir>``: feed, mapping, report.

    ``--sitemap-urls <file> --pages <part>...`` (one capture run's page rows) checks the run
    against the measured sitemap; only a complete one writes ``complete_catalogue: true``."""
    import argparse  # noqa: PLC0415 - CLI only

    from pi_capture.model import loads  # noqa: PLC0415 - CLI only

    parser = argparse.ArgumentParser(prog="python -m pi_capture.feed")
    parser.add_argument("shop", choices=sorted(SHOPS))
    parser.add_argument("readings", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--sitemap-urls", type=Path, help="product URLs, one per line")
    parser.add_argument("--pages", type=Path, nargs="+", help="one run's page rows")
    args = parser.parse_args(argv)
    if (args.sitemap_urls is None) != (args.pages is None):
        parser.error("--sitemap-urls and --pages go together")
    shop = SHOPS[args.shop]
    with args.readings.open(encoding="utf-8") as fh:
        captures = [loads(line) for line in fh if line.strip()]
    result = build_feed(captures, shop)
    summary = result.report()
    complete = False
    if args.sitemap_urls is not None:
        urls = [u.strip() for u in args.sitemap_urls.read_text("utf-8").splitlines() if u.strip()]
        pages = [row for part in args.pages for row in _page_rows(part)]
        check = completeness(urls, pages, captures, result, shop)
        complete = check.complete
        summary["catalogue"] = check.report()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{shop.source}.feed.json").write_text(dump_feed(result, shop), "utf-8")
    (args.out_dir / f"{shop.source}.mapping.json").write_text(
        json.dumps(mapping_for(shop, complete=complete), indent=1, sort_keys=True), "utf-8"
    )
    report = summary | {"excluded_rows": result.excluded}
    (args.out_dir / f"{shop.source}.feed-report.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), "utf-8"
    )
    print(json.dumps(summary))
    return 0
