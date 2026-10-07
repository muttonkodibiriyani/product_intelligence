"""One scheduled run for one shop: sitemap -> selection -> capture -> read -> feed -> state.

    BUCKET=pi-capture-… SHOP=faces_ae python -m uae_collect.run

Everything a run writes sits under ``runs/<source>/<run id>/`` (page_capture's own layout, then
``readings/`` from capture_read and ``collect.json``), plus the feed under
``feeds/<source>/<run id>/`` for the host's load cron and the advanced ``state/<source>/``.

Stop rule (ADR-0006): the job runs one shop, so one host. The first block (challenge, 401/403,
a second 429 in a row, ten transport errors) stops that host in page_capture and so the whole
run; nothing is retried, stealthed or proxied. The pages read before the stop are still read and
fed (the run is partial); every page not read stays not_observed and is picked up again by the
next daily pass. A blocked or failed run exits 2, so the execution shows as failed.

Environment:

- ``BUCKET`` (required): the capture bucket, or ``file:<dir>`` locally
- ``SHOP`` (required): a key of :data:`uae_collect.shops.SHOPS`
- ``PASS``: ``daily`` / ``full`` / ``ar`` to override the date's pass (manual runs only)
- ``HOURS``: page-fetch window before the cutoff (default 6)
- ``MAX_ITEMS``: most pages one run plans (default 5000); a longer selection is cut and the run
  is partial
- ``EGRESS`` (default ``cloud-run-me-central1``), ``GIT_SHA``
"""

from __future__ import annotations

import gzip
import json
import os
import signal
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from capture_read import run as capture_read
from page_capture import robots
from page_capture import run as page_capture
from page_capture.plan import Item, Plan
from page_capture.store import Store
from pi_capture import feed as pi_feed
from pi_capture.model import ProductCapture, loads
from uae_collect.shops import AR, FULL, LOCALES, PASSES, SHOPS, Shop
from uae_collect.sitemap import MAX_CHILDREN, parse
from uae_collect.state import State

OK, CUTOFF, BLOCKED, ERROR, NOTHING = "ok", "cutoff", "blocked", "error", "nothing_to_read"
EXIT_FAILED = 2
#: A full pass is never a complete catalogue when its sitemap no longer lists more than this
#: share of the in-scope URLs a sitemap listed in the last BASELINE_DAYS: a short or truncated
#: sitemap would otherwise make every product it left out read as removed downstream. With no
#: such URLs yet (the first full pass on an empty state) there is no baseline, and it is not either.
MAX_SITEMAP_DROP = 0.05
BASELINE_DAYS = 14


@dataclass(frozen=True)
class Config:
    bucket: str
    shop: Shop
    run_pass: str
    started: datetime
    hours: float = 6.0
    max_items: int = 5000
    egress: str = "cloud-run-me-central1"
    git_sha: str = ""

    @property
    def day(self) -> str:
        return self.started.date().isoformat()

    @property
    def run_id(self) -> str:
        return f"{self.started:%Y-%m-%dT%H%M%SZ}-{self.run_pass}"

    @property
    def prefix(self) -> str:
        return f"runs/{self.shop.source}/{self.run_id}"


def config_from_env(env: Mapping[str, str], now: datetime) -> Config:
    shop_key = env["SHOP"]
    if shop_key not in SHOPS:
        raise ValueError(f"SHOP must be one of {sorted(SHOPS)}")
    shop = SHOPS[shop_key]
    run_pass = env.get("PASS", "").strip() or shop.pass_for(now.date())
    if run_pass not in PASSES:
        raise ValueError(f"PASS must be one of {PASSES}")
    hours, max_items = float(env.get("HOURS", "6")), int(env.get("MAX_ITEMS", "5000"))
    if not 0 < hours <= 20:
        raise ValueError("HOURS must be within (0, 20]")
    if max_items < 1:
        raise ValueError("MAX_ITEMS must be >= 1")
    return Config(
        bucket=env["BUCKET"],
        shop=shop,
        run_pass=run_pass,
        started=now,
        hours=hours,
        max_items=max_items,
        egress=env.get("EGRESS", "cloud-run-me-central1"),
        git_sha=env.get("GIT_SHA", ""),
    )


class SitemapError(Exception):
    """The sitemap could not be read; the run plans nothing."""


@dataclass
class Report:
    run_pass: str
    outcome: str = OK
    reason: str | None = None
    sitemaps: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    feed: str | None = None
    complete_catalogue: bool = False


def read_sitemaps(job: page_capture.Job, shop: Shop, report: Report) -> dict[str, str | None]:
    """Product URLs (-> lastmod) across the shop's sitemaps, through page_capture's own fetch:
    robots-checked, paced, block-detected, raw bodies stored under the run."""
    queue, seen, listed = list(shop.sitemaps), set[str](), dict[str, str | None]()
    hosts = {urlsplit(s).hostname for s in shop.sitemaps}
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if len(seen) > MAX_CHILDREN + len(shop.sitemaps):
            raise SitemapError(f"more than {MAX_CHILDREN} sitemaps")
        verdict = job.robots_verdict(url, job.cfg.pace_s)
        if verdict != robots.ALLOWED:
            raise SitemapError(f"sitemap {url}: robots {verdict}")
        hdrs = page_capture.headers(job.cfg.user_agent, "en-AE", "xml", {})
        got = job.fetch(url, hdrs, "xml", job.cfg.pace_s)
        digest, raw = job.store_raw("xml", got)
        report.sitemaps.append(
            {"url": url, "status": got.status, "state": got.state, "sha256": digest, "raw": raw}
        )
        if got.state != page_capture.OK:
            raise SitemapError(f"sitemap {url}: {got.state} {got.reason}".strip())
        body = gzip.decompress(got.body) if got.body[:2] == b"\x1f\x8b" else got.body
        try:
            doc = parse(body.decode("utf-8", "replace"))
        except ValueError as exc:
            raise SitemapError(f"sitemap {url}: {exc}") from None
        for child in doc.children:
            parts = urlsplit(child)
            if parts.scheme != "https" or parts.hostname not in hosts:
                raise SitemapError(f"sitemap {url}: child {child} is off the shop's https host")
            queue.append(child)
        for loc, lastmod in doc.urls.items():
            if shop.lang(loc) is not None:
                listed.setdefault(loc, lastmod)
    return listed


def _jsonl_gz(bucket: capture_read.Bucket, names: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in names:
        text = gzip.decompress(bucket.get(name)).decode("utf-8")
        rows.extend(json.loads(line) for line in text.splitlines() if line.strip())
    return rows


def _parts(bucket: capture_read.Bucket, prefix: str) -> list[str]:
    """``<prefix>part-*.jsonl.gz`` objects directly under ``prefix`` (not in sub-folders)."""
    return [
        n
        for n in bucket.names(prefix)
        if n.endswith(".jsonl.gz") and "/" not in n.removeprefix(prefix)
    ]


def _outcome(job: page_capture.Job) -> tuple[str, str | None]:
    stopped = [h for h in job.hosts.values() if h.stopped]
    if stopped:
        return BLOCKED, f"{stopped[0].host}: {stopped[0].stopped}"
    if job.stopped:
        return ERROR, job.stopped
    if job.cut:
        return CUTOFF, "cutoff reached before every planned page was fetched"
    return OK, None


def capture(job: page_capture.Job) -> None:
    """page_capture's main loop, with its own stop handling."""
    try:
        job.run()
    except page_capture.Stop as exc:
        job.stopped = str(exc)
    except Exception as exc:  # recorded in status.json and collect.json, never silent
        job.stopped = f"error: {exc!r}"
    finally:
        job.finish()


def collect(  # noqa: PLR0915 - one linear run, kept in one place on purpose
    cfg: Config,
    bucket: capture_read.Bucket,
    make_job: Callable[[page_capture.Config], page_capture.Job],
) -> Report:
    shop, report = cfg.shop, Report(run_pass=cfg.run_pass)
    store = Store(cfg.bucket, cfg.prefix)
    job = make_job(
        page_capture.Config(
            bucket=cfg.bucket,
            prefix=cfg.prefix,
            plan_uri=store.uri("plan.json"),
            cutoff=cfg.started + timedelta(hours=cfg.hours),
            pace_s=shop.pace_s,
            images=False,
            egress=cfg.egress,
            git_sha=cfg.git_sha,
        )
    )
    state_name = f"state/{shop.source}/urls.json.gz"
    try:
        listed = read_sitemaps(job, shop, report)
    except SitemapError as exc:
        job.finish()
        report.outcome, report.reason = _outcome(job)
        if report.outcome == OK:
            report.outcome = ERROR
        report.reason = str(exc)
        return report
    state = State.from_bytes(bucket.get(state_name)) if bucket.exists(state_name) else State()
    selected = state.select(shop, cfg.run_pass, listed)
    planned = selected[: cfg.max_items]
    lang = "ar" if cfg.run_pass == AR else "en"
    since = (cfg.started.date() - timedelta(days=BASELINE_DAYS)).isoformat()
    known = state.known(shop, lang, since)
    unlisted = len(known - listed.keys())
    report.counts |= {
        "listed": len(listed),
        "selected": len(selected),
        "planned": len(planned),
        "known_in_scope": len(known),
        "known_unlisted": unlisted,
    }
    if not planned:
        job.finish()
        report.outcome = NOTHING
        state.record(cfg.day, listed, [], [])  # the sitemap still dates the full-pass baseline
        bucket.put(state_name, state.to_bytes())
        return report
    plan = Plan(
        source=shop.source,
        retailer=shop.retailer,
        items=tuple(
            Item(
                id=f"p{i:05d}",
                url=url,
                locale=LOCALES[lang],
                kind="html",
                ref={"retailer": shop.retailer, "source": shop.source},
            )
            for i, url in enumerate(planned)
        ),
    )
    store.put("plan.json", json.dumps(plan.to_json()).encode())
    capture(job)
    report.outcome, report.reason = _outcome(job)
    if report.outcome == OK and len(planned) < len(selected):
        report.outcome = CUTOFF
        report.reason = f"MAX_ITEMS {cfg.max_items} < {len(selected)} selected"

    read = capture_read.Job(
        src_prefix=cfg.prefix,
        locale=LOCALES[lang],
        egress=cfg.egress,
        retailers=frozenset({shop.retailer}),
    )
    report.counts |= {f"read_{k}": v for k, v in capture_read.run(bucket, read).items()}
    pages = _jsonl_gz(bucket, _parts(bucket, f"{cfg.prefix}/pages/"))
    errors = _jsonl_gz(bucket, _parts(bucket, f"{cfg.prefix}/readings/errors/"))
    captures: list[ProductCapture] = [
        loads(line)
        for name in _parts(bucket, f"{cfg.prefix}/readings/")
        for line in gzip.decompress(bucket.get(name)).decode("utf-8").splitlines()
        if line.strip()
    ]
    failed = {str(e["url"]) for e in errors}
    read_ok = [str(p["url"]) for p in pages if p.get("state") == "ok" and p["url"] not in failed]
    out_of_scope = [str(e["url"]) for e in errors if e.get("state") == "out_of_scope"]
    report.counts |= {"pages_read": len(read_ok), "pages_out_of_scope": len(out_of_scope)}

    if lang == "en" and captures:
        feed_shop = pi_feed.SHOPS[shop.source]
        result = pi_feed.build_feed(captures, feed_shop)
        summary = result.report()
        if cfg.run_pass == FULL and report.outcome == OK:
            check = pi_feed.completeness(selected, pages, captures, result, feed_shop)
            report.complete_catalogue = check.complete
            summary["catalogue"] = check.report()
            refused = None
            if not known:  # nothing to measure this sitemap against: the next full pass can be
                refused = "no sitemap baseline yet: not a complete catalogue"
            elif unlisted > MAX_SITEMAP_DROP * len(known):
                refused = (
                    f"sitemap no longer lists {unlisted} of {len(known)} known in-scope URLs"
                    f" (> {MAX_SITEMAP_DROP:.0%}): not a complete catalogue"
                )
            if refused:
                report.complete_catalogue = False
                report.reason = summary["catalogue_refused"] = refused
        if result.rows:
            out = f"feeds/{shop.source}/{cfg.run_id}"
            mapping = pi_feed.mapping_for(feed_shop, complete=report.complete_catalogue)
            for name, data in (
                (f"{shop.source}.feed.json", pi_feed.dump_feed(result, feed_shop)),
                (f"{shop.source}.mapping.json", json.dumps(mapping, indent=1, sort_keys=True)),
                (
                    f"{shop.source}.feed-report.json",
                    json.dumps(
                        summary | {"excluded_rows": result.excluded}, indent=1, ensure_ascii=False
                    ),
                ),
            ):
                bucket.put(f"{out}/{name}", data.encode("utf-8"))
            report.feed = f"{out}/{shop.source}.feed.json"
        report.counts |= {"feed_rows": len(result.rows), "feed_excluded": len(result.excluded)}

    state.record(cfg.day, listed, read_ok, out_of_scope)
    bucket.put(state_name, state.to_bytes())
    return report


def write_report(bucket: capture_read.Bucket, cfg: Config, report: Report) -> None:
    doc = {"source": cfg.shop.source, "run_id": cfg.run_id, "prefix": cfg.prefix} | vars(report)
    bucket.put(f"{cfg.prefix}/collect.json", json.dumps(doc, indent=1).encode())
    print(json.dumps(doc), flush=True)


def _sigterm(signum: int, frame: object) -> None:
    raise page_capture.Stop("sigterm")


def main(
    env: Mapping[str, str] | None = None,
    bucket: capture_read.Bucket | None = None,
    make_job: Callable[[page_capture.Config], page_capture.Job] = page_capture.Job,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    signal.signal(signal.SIGTERM, _sigterm)
    cfg = config_from_env(os.environ if env is None else env, now())
    if bucket is None:
        if cfg.bucket.startswith("file:"):
            bucket = capture_read.LocalBucket(cfg.bucket.removeprefix("file:"))
        else:  # pragma: no cover - cloud only
            bucket = capture_read.GcsBucket(cfg.bucket)
    report = collect(cfg, bucket, make_job)
    write_report(bucket, cfg, report)
    return EXIT_FAILED if report.outcome in (BLOCKED, ERROR) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
