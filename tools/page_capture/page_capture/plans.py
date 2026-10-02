"""Plan builders: pure functions turning a product list or downloaded sitemaps into capture plans.

Nothing here fetches anything. ``ksa_radar`` reads the KSA price-radar ``products.csv`` and writes
one plan per retailer: the English product page plus its Arabic twin where the platform exposes a
locale path (``AR_RULES``, each verified with one request on 2 Oct 2026 where the host allowed it; a
retailer mapped to ``None`` has no known Arabic path and gets English only). ``sitemap_plan``
turns already-downloaded sitemap XML (or plain URL lists) into a plan.

CLI::

    python -m page_capture.plans ksa-radar <products.csv> <out-dir>
    python -m page_capture.plans sitemap <source> <retailer> <list-file> <regex> <out.json> [RR]

``list-file`` names one local sitemap file (XML, optionally gzipped) or URL-list file per line.
``regex`` selects product URLs; a named group ``lang`` sets the locale language (default en).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from defusedxml import ElementTree  # type: ignore[import-untyped]

from page_capture.plan import GZIP_MAGIC, Item, Plan

# retailer -> (English marker, Arabic marker), first occurrence in the URL is replaced.
AR_RULES: dict[str, tuple[str, str] | None] = {
    "aldo": None,  # /ar/ answered 404 on 2 Oct 2026; English only until a path is verified
    "american_eagle": ("/en/", "/ar/"),
    "centrepoint": ("/sa/en/", "/sa/ar/"),
    "charles_keith": ("/sa-en/", "/sa/"),  # /sa-ar/ redirects to /sa/, which is Arabic
    "cos": ("/en/", "/ar/"),
    "foot_locker": ("/en/", "/ar/"),
    "mamas_papas": None,  # ar.mamasandpapas.com.sa does not resolve; English only
    "marks_spencer": ("/en/", "/ar/"),
    "max_fashion": ("/sa/en/", "/sa/ar/"),
    "milano": ("/products/", "/ar/products/"),
    "mothercare": ("/en/", "/ar/"),
    "muji": ("/en/", "/ar/"),
    "nayomi": ("/en/", "/"),  # /ar/ redirects to the unprefixed path, which is Arabic
    "nike": ("/en/", "/ar/"),
    "steve_madden": ("/products/", "/ar/products/"),
    "victorias_secret": ("/en/", "/ar/"),
    "zara": ("/sa/en/", "/sa/ar/"),
}
REF_FIELDS = ("retailer", "source_product_id", "item", "item_label", "name")


def arabic_twin(retailer: str, url: str) -> str | None:
    """The Arabic URL derived from an English one, or None when the platform has no known path."""
    rule = AR_RULES.get(retailer)
    if rule is None or rule[0] not in url:
        return None
    return url.replace(rule[0], rule[1], 1)


def item_id(retailer: str, url: str, lang: str) -> str:
    return f"{retailer}-{hashlib.sha256(url.encode()).hexdigest()[:16]}-{lang}"


def row_images(row: Mapping[str, str]) -> tuple[str, ...]:
    """Union of the JSON ``images`` list and ``image_url``, order kept, duplicates dropped."""
    out: list[str] = []
    raw = (row.get("images") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"row {row.get('id')!r}: images is not JSON: {exc}") from exc
        if not isinstance(parsed, list) or not all(isinstance(u, str) for u in parsed):
            raise ValueError(f"row {row.get('id')!r}: images must be a JSON list of strings")
        out.extend(parsed)
    single = (row.get("image_url") or "").strip()
    if single:
        out.append(single)
    return tuple(dict.fromkeys(u for u in out if u.startswith(("http://", "https://"))))


def ksa_radar(rows: Iterable[Mapping[str, str]], region: str = "SA") -> dict[str, Plan]:
    """One plan per retailer from radar rows; URLs deduplicated, first row's reference kept."""
    by_url: dict[str, dict[str, Any]] = {}
    images_by_url: dict[str, tuple[str, ...]] = {}
    for row in rows:
        retailer, url = row.get("retailer", "").strip(), row.get("url", "").strip()
        if not retailer or not url:
            raise ValueError(f"row {row.get('id')!r}: retailer and url are required")
        if url in by_url:
            by_url[url]["radar_row_ids"].append(row.get("id", ""))
            continue
        ref = {k: row.get(k, "") for k in REF_FIELDS}
        by_url[url] = {
            **ref,
            "radar_row_id": row.get("id", ""),
            "radar_row_ids": [row.get("id", "")],
        }
        images_by_url[url] = row_images(row)
    items: dict[str, list[Item]] = {}
    for url, ref in by_url.items():
        retailer = str(ref["retailer"])
        images = images_by_url[url]
        en = Item(item_id(retailer, url, "en"), url, f"en-{region}", "html", ref, images)
        items.setdefault(retailer, []).append(en)
        ar_url = arabic_twin(retailer, url)
        if ar_url is not None and ar_url not in by_url:
            ar_ref = {**ref, "derived_from": en.id, "lang": "ar"}
            items[retailer].append(
                Item(item_id(retailer, ar_url, "ar"), ar_url, f"ar-{region}", "html", ar_ref)
            )
    return {
        retailer: Plan("ksa_radar", retailer, tuple(its)) for retailer, its in sorted(items.items())
    }


def read_rows(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def sitemap_locs(text: str) -> list[str]:
    """``<loc>`` values of a sitemap, or the http(s) lines of a plain URL list."""
    stripped = text.lstrip()
    if stripped.startswith("<"):
        root = ElementTree.fromstring(stripped)
        return [
            (el.text or "").strip()
            for el in root.iter()
            if el.tag.rsplit("}", 1)[-1] == "loc" and (el.text or "").strip()
        ]
    return [
        ln.strip() for ln in text.splitlines() if ln.strip().startswith(("http://", "https://"))
    ]


def read_text(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] == GZIP_MAGIC:
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def sitemap_plan(
    source: str, retailer: str, texts: Sequence[str], pattern: str, region: str = "AE"
) -> Plan:
    """Items for every ``<loc>`` matching ``pattern`` (named group ``lang`` -> locale), deduped."""
    rx = re.compile(pattern)
    items: dict[str, Item] = {}
    for text in texts:
        for loc in sitemap_locs(text):
            m = rx.search(loc)
            if m is None or loc in items:
                continue
            lang = (m.groupdict().get("lang") or "en").lower()
            items[loc] = Item(
                item_id(retailer, loc, lang),
                loc,
                f"{lang}-{region}",
                "html",
                {"retailer": retailer, "source": source},
            )
    if not items:
        raise ValueError("sitemap plan: no <loc> matched the pattern")
    return Plan(source, retailer, tuple(items.values()))


def write_plan(plan: Plan, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan.to_json(), fh, ensure_ascii=False, indent=1)


def main(argv: Sequence[str]) -> int:
    if len(argv) >= 3 and argv[0] == "ksa-radar":
        plans = ksa_radar(read_rows(argv[1]))
        for retailer, plan in plans.items():
            write_plan(plan, os.path.join(argv[2], f"{retailer}.json"))
            langs = {it.locale.split("-")[0] for it in plan.items}
            print(f"{retailer}\t{len(plan.items)}\t{','.join(sorted(langs))}")
        return 0
    if len(argv) >= 6 and argv[0] == "sitemap":
        _, source, retailer, list_file, pattern, out = argv[:6]
        region = argv[6] if len(argv) > 6 else "AE"
        with open(list_file, encoding="utf-8") as fh:
            paths = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
        plan = sitemap_plan(source, retailer, [read_text(p) for p in paths], pattern, region)
        write_plan(plan, out)
        print(f"{retailer}\t{len(plan.items)}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
