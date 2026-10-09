"""Listing positions: capture plans for retailer listing pages, and a reader for what came back.

A listing is a retailer page that lists products in the retailer's own order (new in, best
sellers, exclusives). We record where each product stood on the page on the day we read it, and
how much of the listing we read, so a missing product is never mistaken for a dropped one.

Nothing here fetches anything. The capture itself is ``page_capture.run`` (paced, robots
fail-closed, stop on the first challenge or 401/403); this module only writes its plans and reads
its output afterwards, so an extractor bug never costs a second read.

- ``plan``: page 1 of every listing in a spec. Every URL is checked offline against a saved
  robots.txt for its host first; a host without one is refused (fail-closed), and a disallowed
  listing is refused by name before anything is written.
- ``next``: page N+1 of every paged listing whose page N came back full. Paging is only by the
  ``start`` query parameter (Faces, SFCC), and the step is page 1's tile count, so no page size
  is ever asked for (robots disallows ``sz``). Run ``next`` after each capture until it plans
  nothing.
- ``read``: position rows (one per product, 1-based, global across pages, first sighting wins)
  and one summary per listing: ``pages_read``, ``positions_captured``, ``end_reached`` and
  ``stop_reason``.

``stop_reason`` is one of:

- ``end``: a page came back short, empty or with no product not already seen (``end_reached``);
- ``cap``: ``max_pages`` read and the last one was still full;
- ``robots_page1`` / ``page1_ssr``: a page-1-only listing (robots forbids paging, or only the
  server-rendered first page is read); never ``end_reached``;
- ``block``: a page was blocked or rate limited, or skipped because its host had stopped;
- ``error``: any other page failure (HTTP error, transport error, robots refusal, cutoff);
- ``pending``: the next page is planned but not captured yet.

A listing whose page 1 was not read is ``not_observed``. "Not in the list" may only be said of a
listing with ``end_reached`` true; otherwise only "not in the first N positions captured".

Spec (JSON)::

    {"retailer": "faces_ae", "source": "faces_ae_listings", "max_pages": 10,
     "listings": [{"id": "faces-new", "url": "https://www.faces.ae/en/new-beauty-products",
                   "category": "new", "label": "New beauty", "paging": "start"},
                  {"id": "...", "url": "...", "category": "best_seller", "paging": "none",
                   "page1_reason": "robots_page1"}]}

CLI::

    python -m page_capture.listings plan <spec.json> <out-plan.json> <host>=<robots.txt>...
    python -m page_capture.listings next <spec.json> <out-plan.json> <capture-dir>... \
        -- <host>=<robots.txt>...
    python -m page_capture.listings read <spec.json> <out-dir> <capture-dir>...
    python -m page_capture.listings links <retailer> <base-url> <raw-page> [regex]

``plan`` and ``next`` exit 3 when there is nothing to plan, so a shell loop can stop on it.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from page_capture import robots
from page_capture.plan import GZIP_MAGIC, Item, Plan
from page_capture.plans import write_plan
from page_capture.run import USER_AGENT

CATEGORIES = ("new", "best_seller", "exclusive", "discovery")
PAGING = ("start", "none")
PAGE1_REASONS = ("robots_page1", "page1_ssr")
DEFAULT_MAX_PAGES = 10
BLOCK_STATES = ("blocked", "rate_limited", "skipped_host_stopped")
NOTHING_TO_PLAN = 3

# Product page links per retailer: group ``id`` is the retailer's product id. Matched against the
# absolute URL (query and fragment dropped), so a tile's link and a plain anchor count the same.
PRODUCT_LINKS: dict[str, re.Pattern[str]] = {
    "faces_ae": re.compile(r"^https://www\.faces\.ae/(?:en|ar)/p/[^/]+-(?P<id>\d{6,})\.html$"),
    "bloomingdales_ae": re.compile(
        r"^https://(?:www\.)?bloomingdales\.ae/(?:ar/)?[^?]+-(?P<id>\d{4,})\.html$"
    ),
    "ounass_ae": re.compile(
        r"^https://(?:www\.)?ounass\.ae/(?:ar/)?shop-[^/]+-(?P<id>\d+(?:_\d+)?)\.html$"
    ),
    "sephora_me": re.compile(r"^https://www\.sephora\.me/ae-(?:en|ar)/p/[^/]+/(?P<id>P\d+)/?$"),
}
HREF = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


@dataclass(frozen=True)
class Listing:
    id: str
    url: str
    category: str
    label: str = ""
    paging: str = "none"
    page1_reason: str = "robots_page1"
    max_pages: int = DEFAULT_MAX_PAGES


@dataclass(frozen=True)
class Spec:
    retailer: str
    source: str
    listings: tuple[Listing, ...]
    locale: str = "en-AE"


@dataclass
class PageRead:
    listing: str
    page: int
    state: str
    url: str
    at: str = ""
    final_url: str = ""
    raw: str = ""
    reason: str = ""
    products: list[tuple[str, str]] = field(default_factory=list)  # (id, url), page order


def spec_from_json(doc: Mapping[str, Any]) -> Spec:
    retailer, source = doc.get("retailer"), doc.get("source")
    if not isinstance(retailer, str) or retailer not in PRODUCT_LINKS:
        raise ValueError(f"spec: retailer must be one of {sorted(PRODUCT_LINKS)}")
    if not isinstance(source, str) or not source:
        raise ValueError("spec: source must be a non-empty string")
    default_max = doc.get("max_pages", DEFAULT_MAX_PAGES)
    raw_listings = doc.get("listings")
    if not isinstance(raw_listings, list) or not raw_listings:
        raise ValueError("spec: listings must be a non-empty list")
    out = [
        listing_from_json(raw, f"listings[{i}]", default_max) for i, raw in enumerate(raw_listings)
    ]
    ids = [x.id for x in out]
    if len(set(ids)) != len(ids):
        raise ValueError("spec: duplicate listing id")
    locale = doc.get("locale", "en-AE")
    if not isinstance(locale, str) or len(locale.split("-")) != 2:
        raise ValueError("spec: locale must look like en-AE")
    return Spec(retailer, source, tuple(out), locale)


def listing_from_json(raw: Mapping[str, Any], where: str, default_max: Any) -> Listing:
    lid, url = raw.get("id"), raw.get("url")
    if not isinstance(lid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", lid):
        raise ValueError(f"{where}: id must be lowercase [a-z0-9_-]")
    if not isinstance(url, str) or urlsplit(url).scheme != "https":
        raise ValueError(f"{where}: url must be https")
    category = raw.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"{where}: category must be one of {CATEGORIES}")
    paging = raw.get("paging", "none")
    if paging not in PAGING:
        raise ValueError(f"{where}: paging must be one of {PAGING}")
    if paging == "start" and urlsplit(url).query:
        raise ValueError(f"{where}: a paged listing URL must carry no query")
    reason = raw.get("page1_reason", "robots_page1")
    if reason not in PAGE1_REASONS:
        raise ValueError(f"{where}: page1_reason must be one of {PAGE1_REASONS}")
    max_pages = raw.get("max_pages", default_max)
    if not isinstance(max_pages, int) or not 1 <= max_pages <= DEFAULT_MAX_PAGES:
        raise ValueError(f"{where}: max_pages must be within 1..{DEFAULT_MAX_PAGES}")
    return Listing(lid, url, category, str(raw.get("label", "")), paging, reason, max_pages)


def read_spec(path: str) -> Spec:
    return spec_from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def page_url(listing: Listing, page: int, step: int) -> str:
    if page == 1:
        return listing.url
    if listing.paging != "start" or step < 1:
        raise ValueError(f"{listing.id}: page {page} needs start paging and a step")
    parts = urlsplit(listing.url)
    query = urlencode([*parse_qsl(parts.query), ("start", str((page - 1) * step))])
    return urlunsplit(parts._replace(query=query))


def page_item(spec: Spec, listing: Listing, page: int, step: int) -> Item:
    ref = {"listing": listing.id, "page": page, "step": step, "category": listing.category}
    return Item(
        id=f"{listing.id}-p{page:02d}",
        url=page_url(listing, page, step),
        locale=spec.locale,
        kind="html",
        ref=ref,
    )


# ------------------------------------------------------------------ robots, offline
def load_robots(pairs: Iterable[str]) -> dict[str, robots.Robots]:
    """``host=path`` pairs: each saved robots.txt read as a 200 text/plain answer."""
    out: dict[str, robots.Robots] = {}
    for pair in pairs:
        host, sep, path = pair.partition("=")
        if not sep or not host or not path:
            raise ValueError(f"robots: expected host=path, got {pair!r}")
        raw = Path(path).read_bytes()
        text = (gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw).decode("utf-8", "replace")
        out[host.lower()] = robots.from_response(200, "text/plain", text, USER_AGENT)
    return out


def robots_refusals(items: Sequence[Item], rules: Mapping[str, robots.Robots]) -> list[str]:
    """One line per item whose host has no saved robots.txt, or whose URL it disallows."""
    out: list[str] = []
    for it in items:
        host = (urlsplit(it.url).hostname or "").lower()
        verdict = rules[host].verdict(it.url) if host in rules else robots.UNAVAILABLE
        if verdict != robots.ALLOWED:
            out.append(f"robots {verdict}: {it.id} {it.url}")
    return out


def checked_plan(spec: Spec, items: Sequence[Item], rules: Mapping[str, robots.Robots]) -> Plan:
    refused = robots_refusals(items, rules)
    if refused:
        raise ValueError("refused before writing a plan:\n" + "\n".join(refused))
    return Plan(source=spec.source, retailer=spec.retailer, items=tuple(items))


def first_pages(spec: Spec) -> list[Item]:
    return [page_item(spec, x, 1, 0) for x in spec.listings]


# ------------------------------------------------------------------ reading captures
def product_links(retailer: str, base_url: str, html: str) -> list[tuple[str, str]]:
    """Product (id, url) pairs in document order, each product once (first link wins)."""
    pattern = PRODUCT_LINKS[retailer]
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for m in HREF.finditer(html):
        href = unescape(m.group(1) if m.group(1) is not None else m.group(2)).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        parts = urlsplit(urljoin(base_url, href))
        url = urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))
        hit = pattern.match(url)
        if hit and hit.group("id") not in seen:
            seen.add(hit.group("id"))
            out.append((hit.group("id"), url))
    return out


def page_records(capture_dir: Path) -> Iterable[dict[str, Any]]:
    for part in sorted((capture_dir / "pages").glob("part-*.jsonl*")):
        raw = part.read_bytes()
        data = gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw
        for line in data.decode("utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def read_raw(capture_dir: Path, name: str) -> str:
    raw = (capture_dir / name).read_bytes()
    data = gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw
    return data.decode("utf-8", "replace")


def page_reads(spec: Spec, capture_dirs: Sequence[Path]) -> dict[str, dict[int, PageRead]]:
    """Every captured page of the spec's listings, by listing and page; a later capture of the
    same page replaces an earlier one only when the earlier one was not read."""
    known = {x.id for x in spec.listings}
    out: dict[str, dict[int, PageRead]] = {x.id: {} for x in spec.listings}
    for d in capture_dirs:
        for rec in page_records(d):
            ref = rec.get("ref") or {}
            lid, page = ref.get("listing"), ref.get("page")
            if lid not in known or not isinstance(page, int):
                continue
            pr = PageRead(
                listing=lid,
                page=page,
                state=str(rec.get("state")),
                url=str(rec.get("url")),
                at=str(rec.get("at") or ""),
                final_url=str(rec.get("final_url") or rec.get("url")),
                raw=str(rec.get("raw") or ""),
                reason=str(rec.get("reason") or ""),
            )
            if pr.state == "ok" and pr.raw:
                pr.products = product_links(spec.retailer, pr.final_url, read_raw(d, pr.raw))
            old = out[lid].get(page)
            if old is None or old.state != "ok":
                out[lid][page] = pr
    return out


@dataclass(frozen=True)
class Walk:
    """One listing's pages read in order, up to the first that stops it."""

    pages: tuple[PageRead, ...]
    positions: tuple[tuple[int, str, str, PageRead], ...]  # (position, id, url, page)
    stop_reason: str
    end_reached: bool
    step: int
    next_page: int | None  # the page ``next`` should plan, if any


def walk(listing: Listing, pages: Mapping[int, PageRead]) -> Walk:
    read: list[PageRead] = []
    positions: list[tuple[int, str, str, PageRead]] = []
    seen: set[str] = set()
    step = 0
    page = 1
    while True:
        pr = pages.get(page)
        if pr is None:
            nxt = page if page > 1 else None
            return Walk(tuple(read), tuple(positions), "pending", False, step, nxt)
        read.append(pr)
        if pr.state != "ok":
            reason = "block" if pr.state in BLOCK_STATES else "error"
            return Walk(tuple(read), tuple(positions), reason, False, step, None)
        new = [(pid, url) for pid, url in pr.products if pid not in seen]
        for pid, url in new:
            seen.add(pid)
            positions.append((len(positions) + 1, pid, url, pr))
        if listing.paging == "none":
            return Walk(tuple(read), tuple(positions), listing.page1_reason, False, step, None)
        if page == 1:
            step = len(pr.products)
        if not new or len(pr.products) < step or step == 0:
            return Walk(tuple(read), tuple(positions), "end", True, step, None)
        if page >= listing.max_pages:
            return Walk(tuple(read), tuple(positions), "cap", False, step, None)
        page += 1


def next_pages(spec: Spec, reads: Mapping[str, Mapping[int, PageRead]]) -> list[Item]:
    out: list[Item] = []
    for x in spec.listings:
        w = walk(x, reads[x.id])
        if w.next_page is not None:
            out.append(page_item(spec, x, w.next_page, w.step))
    return out


def summarise(
    spec: Spec, reads: Mapping[str, Mapping[int, PageRead]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Position rows and one summary per listing."""
    rows: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for x in spec.listings:
        w = walk(x, reads[x.id])
        for pos, pid, url, pr in w.positions:
            rows.append(
                {
                    "retailer": spec.retailer,
                    "listing": x.id,
                    "listing_url": x.url,
                    "category": x.category,
                    "label": x.label,
                    "page": pr.page,
                    "position": pos,
                    "product_id": pid,
                    "product_url": url,
                    "page_url": pr.url,
                    "captured_at": pr.at,
                }
            )
        observed = bool(w.pages) and w.pages[0].state == "ok"
        warnings = []
        if observed and not w.positions:
            warnings.append("page 1 read but no product link matched")
        summary.append(
            {
                "retailer": spec.retailer,
                "listing": x.id,
                "listing_url": x.url,
                "category": x.category,
                "label": x.label,
                "status": "observed" if observed else "not_observed",
                "pages_read": sum(1 for p in w.pages if p.state == "ok"),
                "positions_captured": len(w.positions),
                "end_reached": w.end_reached,
                "stop_reason": w.stop_reason,
                "page_size": w.step or None,
                "page_states": [
                    {"page": p.page, "state": p.state, "reason": p.reason} for p in w.pages
                ],
                "first_at": w.pages[0].at if w.pages else "",
                "warnings": warnings,
            }
        )
    return rows, summary


def write_read(out_dir: Path, rows: Sequence[Mapping[str, Any]], summary: Sequence[Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "positions.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def anchor_links(base_url: str, html: str, pattern: str) -> list[str]:
    """Same-host anchors whose path matches ``pattern``, in document order, each once."""
    host = urlsplit(base_url).hostname
    rx = re.compile(pattern, re.IGNORECASE)
    seen: set[str] = set()
    out: list[str] = []
    for m in HREF.finditer(html):
        href = unescape(m.group(1) if m.group(1) is not None else m.group(2)).strip()
        parts = urlsplit(urljoin(base_url, href))
        if parts.hostname != host or not rx.search(parts.path):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _emit_plan(spec: Spec, items: list[Item], out: str, robots_pairs: Sequence[str]) -> int:
    if not items:
        print("nothing to plan")
        return NOTHING_TO_PLAN
    plan = checked_plan(spec, items, load_robots(robots_pairs))
    write_plan(plan, out)
    print(f"{len(items)} items -> {out}")
    return 0


def main(argv: Sequence[str]) -> int:
    if len(argv) >= 4 and argv[0] == "plan":
        spec = read_spec(argv[1])
        return _emit_plan(spec, first_pages(spec), argv[2], argv[3:])
    if len(argv) >= 6 and argv[0] == "next" and "--" in argv:
        cut = list(argv).index("--")
        spec = read_spec(argv[1])
        reads = page_reads(spec, [Path(d) for d in argv[3:cut]])
        return _emit_plan(spec, next_pages(spec, reads), argv[2], argv[cut + 1 :])
    if len(argv) >= 4 and argv[0] == "read":
        spec = read_spec(argv[1])
        rows, summary = summarise(spec, page_reads(spec, [Path(d) for d in argv[3:]]))
        write_read(Path(argv[2]), rows, summary)
        print(f"{len(rows)} positions, {len(summary)} listings -> {argv[2]}")
        return 0
    if len(argv) >= 4 and argv[0] == "links":
        retailer, base, path = argv[1:4]
        raw = Path(path).read_bytes()
        html = (gzip.decompress(raw) if raw[:2] == GZIP_MAGIC else raw).decode("utf-8", "replace")
        pattern = argv[4] if len(argv) > 4 else r"new|best|exclusive"
        for url in anchor_links(base, html, pattern):
            print(url)
        print(f"products linked: {len(product_links(retailer, base, html))}", file=sys.stderr)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
