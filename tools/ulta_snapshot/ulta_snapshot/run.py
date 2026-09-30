"""Fetch ulta.ae product pages through the owner-approved residential proxy (rung 5), fetch only.

ADR-0006 Amendment 2 and the coordinator's GO for the ~20-page test. Everything goes through
main's ``pi_fetch.Fetcher`` rung-5 route: the pinned stock WebKit, the proxy credentials read from
Secret Manager at runtime inside this process (never printed), robots.txt obeyed on every request
(pages and sub-requests), heavy assets and third-party hosts aborted, bytes metered against the
cap. Nothing here retries, solves or switches: the first challenge, 401/403/407, proxy error or
second 429 in a row stops the source (``SourceStoppedError``) and the run ends.

Writes to ``OUT_DIR`` (the loader's input layout, see ``load.py``):

* ``pdp/part-<start>.jsonl.gz``: one record per page load (``html`` + robots-allowed
  ``captures``), one part per (resumed) run;
* ``urls_full_en.txt`` (``URL_SOURCE=sitemap``): the enumerated robots-allowed EN product URLs;
* ``robots.txt``: the robots.txt the fetcher obeyed for www.ulta.ae (read through the same route);
* ``progress.json``: the status file, rewritten after every page (counts, proxy bytes, GB, USD);
* ``audit.jsonl``: the fetcher's audit events (per-page proxy bytes and abort reasons);
* ``evidence/``: the fetcher's content-addressed raw payloads.

Env: ``OUT_DIR``, ``URLS_FILE`` (one product URL per line), ``PRIOR_GB`` or ``PRIOR_BYTES``
(required; already used from the allowance, rounded up), ``OWNER_APPROVAL_REF``,
``SECRET_RESOURCE`` (a pinned ``.../versions/<n>``), ``CAPTURE_JSON`` (default off),
``MAX_PAGES`` (default 20),
``GOOGLE_OAUTH_ACCESS_TOKEN`` (the operator's own short-lived token, e.g.
``gcloud auth print-access-token`` in Cloud Shell; used only to read the secret, removed from the
environment before the browser starts, never printed).

Console: one line per page, then one ``ULTA TEST RESULT:`` summary line (runbook:
docs/runbooks/ulta-proxy-test.md).
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import os
import random
import shutil
import signal
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from pydantic import HttpUrl

from pi_connector_ulta.discover import DiscoveryError, child_sitemaps, discover_sitemap
from pi_core import CollectionContext, FetchMethod, LadderRung, Locale, Market, SourceContext
from pi_fetch.cache import LocalEvidenceStore
from pi_fetch.ladder import (
    Fetcher,
    ProxyTransportFactory,
    SourceStoppedError,
    default_proxy_transport,
)
from pi_fetch.pacing import HostPacer, RobotsRefusedError, RobotsRules, RobotsTagger
from pi_fetch.policy import FetchPlan, FetchPolicy
from pi_fetch.proxy import (
    ProxyBudgetExceededError,
    ProxyConfigError,
    ProxyCredentials,
    ProxyMeter,
    ResidentialProxy,
    SecretManagerReader,
    SecretReader,
)
from pi_fetch.transports.base import Transport, TransportError
from pi_fetch.types import BrowserEngine, BrowserProfile, FetchRequest, FetchResult, PayloadKind

SOURCE_ID = 1  # placeholder id: fetch only, nothing is written to pi_db by this job
EGRESS = "iproyal_ae"
SITE = "www.ulta.ae"
BASE = f"https://{SITE}"
SITEMAP_INDEX = f"{BASE}/sitemap.xml"
URLS_FULL = "urls_full_en.txt"
#: Written with ``URLS_FULL``: the id the loader keys its ledger on across cumulative uploads.
SNAPSHOT = "snapshot.json"
#: Statuses that end a run normally (exit 0). Only ``complete`` means the whole URL list was
#: covered in one run from index 0; the loader marks a crawl_run succeeded only for that.
DONE = frozenset({"complete", "batch_complete", "enumerated"})
PAGE_INTERVAL_S = 5.0  # the pacer's floor; a random 0-5 s is added: one page per 5-10 s
_BYTES_PER_GB = Decimal(1000**3)
audit_log = logging.getLogger("pi_fetch.audit")


class RecordingTagger(RobotsTagger):
    """The fetcher's robots tagger, also keeping the robots.txt text it was given (per key)."""

    def __init__(self, user_agent: str = "*") -> None:
        super().__init__(user_agent)
        self.agent = user_agent
        self.texts: dict[str, str] = {}

    def add(self, host: str, robots_txt: str) -> None:
        self.texts[host.lower()] = robots_txt
        super().add(host, robots_txt)


class GraphqlCounter:
    """Counts the robots decisions on ``/graphql`` URLs made by the proxied browser."""

    def __init__(self, inner: ProxyTransportFactory = default_proxy_transport) -> None:
        self.counts: Counter[str] = Counter()
        self.inner = inner

    def wrap(self, allowed: Callable[[str], bool]) -> Callable[[str], bool]:
        def check(url: str) -> bool:
            ok = allowed(url)
            if urlsplit(url).path.rstrip("/").endswith("/graphql"):
                query = "query" if urlsplit(url).query else "bare"
                self.counts[f"graphql_{query}_{'allowed' if ok else 'refused'}"] += 1
            return ok

        return check

    def factory(
        self,
        route: FetchPlan,
        policy: FetchPolicy,
        credentials: ProxyCredentials,
        meter: ProxyMeter,
        allowed: Callable[[str], bool],
    ) -> Transport:
        """``default_proxy_transport`` with the same robots check, counted."""
        return self.inner(route, policy, credentials, meter, self.wrap(allowed))


class AuditSink(logging.Handler):
    """Appends the fetcher's structured audit events to ``audit.jsonl`` (no credentials: the
    transport scrubs them from every message)."""

    def __init__(self, path: Path) -> None:
        super().__init__(logging.INFO)
        self.path = path
        self.pages: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "event", None)
        if event is None:
            return
        row: dict[str, Any] = {"event": event, "message": record.getMessage()}
        for key in ("url", "bytes", "aborted", "reason", "source_id"):
            if hasattr(record, key):
                row[key] = getattr(record, key)
        if event == "proxy_page_bytes":
            self.pages.append(row)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")


def gb(n: int) -> str:
    return str((Decimal(n) / _BYTES_PER_GB).quantize(Decimal("0.000001")))


def operator_token() -> Callable[[], str]:
    """The operator's access token, taken out of the environment (so the browser process never
    inherits it) and kept in memory only; never logged."""
    token = os.environ.pop("GOOGLE_OAUTH_ACCESS_TOKEN", "").strip()
    if not token:
        msg = "GOOGLE_OAUTH_ACCESS_TOKEN is not set (see docs/runbooks/ulta-proxy-test.md)"
        raise SystemExit(msg)
    return lambda: token


def context(now: datetime) -> CollectionContext:
    return CollectionContext(
        source_context=SourceContext(
            id=SOURCE_ID,
            source_id=SOURCE_ID,
            country=Market.UAE,
            locale=Locale.EN,
            currency="AED",
            time_zone="Asia/Dubai",
            ladder_rung_current=LadderRung.PAID_PROXY,
            ladder_rung_max_allowed=LadderRung.PAID_PROXY,
            valid_from=now,
        ),
        crawl_run_id=SOURCE_ID,
        connector_version="ulta_snapshot/0.1",
        ladder_rung_used=LadderRung.PAID_PROXY,
        fetch_method=FetchMethod.RESIDENTIAL_PROXY,
    )


def policy(prior_bytes: int, approval: str, secret: str) -> FetchPolicy:
    proxy = ResidentialProxy(
        source_key="ulta_ae",
        owner_approval_ref=approval,
        secret_resource=secret,
        egress_name=EGRESS,
        prior_bytes=prior_bytes,
    )
    return FetchPolicy(
        browsers={SOURCE_ID: BrowserProfile(engine=BrowserEngine.WEBKIT)},
        residential_proxy={SOURCE_ID: proxy},
        page_interval_s={SOURCE_ID: PAGE_INTERVAL_S},
    )


def page_record(result: FetchResult, page_bytes: int) -> dict[str, Any]:
    """One loader input record; captures are already robots-filtered by the transport."""
    return {
        "at": result.retrieved_at.isoformat(),
        "url": str(result.request.url),
        "lang": "en",
        "status": result.http_status,
        "engine": "webkit",
        "egress": result.egress,
        "proxy_bytes": page_bytes,
        "block": result.block.model_dump(mode="json") if result.block else None,
        "html": "" if result.block else result.body.decode("utf-8", "replace"),
        "captures": [
            {"url": str(c.url), "status": c.status, "body": c.body.decode("utf-8", "replace")}
            for c in result.captured_json
        ],
    }


class Run:
    def __init__(self, out: Path, urls: list[str], fetcher: Fetcher, **extra: Any) -> None:
        self.out = out
        self.urls = urls
        self.fetcher = fetcher
        self.robots: RecordingTagger = extra["robots"]
        self.graphql: GraphqlCounter = extra["graphql"]
        self.audit: AuditSink = extra["audit"]
        self.sleep: Callable[[float], None] = extra.get("sleep", time.sleep)
        #: Off by default (``CAPTURE_JSON=0`` for the owner's test): the DOM + JSON-LD path needs
        #: no captures. Rung 5 accepts them since #31 when the coordinator asks for page JSON.
        self.capture_json: bool = extra.get("capture_json", False)
        self.counts: Counter[str] = Counter()
        now = datetime.now(UTC)
        self.started = now.isoformat()
        #: Part names are unique per run, so a run repeating a start index never appends to a
        #: part the loader has already marked done.
        self.stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        self.stopped = "running"
        self.challenged = False  # set only by a block that stopped the source (challenge/401/403)
        self.console = extra.get("console", sys.stdout)
        #: ``file`` (the given URLs) or ``sitemap`` (enumerate on this route, then crawl).
        self.url_source: str = extra.get("url_source", "file")
        #: Resume point in the URL list and the upper bound on pages this run (None: all).
        self.start: int = extra.get("start", 0)
        self.max_pages: int | None = extra.get("max_pages")
        self.est_bytes_per_page: int | None = extra.get("est_bytes_per_page")
        self.next_index = self.start
        self.batch: list[str] = []
        (out / "pdp").mkdir(parents=True, exist_ok=True)

    def usage(self) -> dict[str, Any]:
        usages = self.fetcher.proxy_usage()
        if not usages:
            return {"bytes_via_proxy": 0, "gb": "0", "usd": "0.00"}
        entry: dict[str, Any] = dict(usages[0].manifest())
        entry["gb"] = gb(usages[0].total)
        return entry

    def progress(self) -> None:
        body = {
            "started": self.started,
            "updated": datetime.now(UTC).isoformat(),
            "stopped": self.stopped,
            "counts": {"en": dict(self.counts)},
            "proxy": self.usage(),
            "graphql": dict(self.graphql.counts),
            "stopped_sources": {str(k): v for k, v in self.fetcher.stopped_sources().items()},
            "url_source": self.url_source,
            "snapshot_id": self.snapshot_id(),
            "urls_total": len(self.urls),
            "start_index": self.start,
            #: Resume here (START_INDEX=auto): every URL before it was fetched or robots-refused.
            "next_index": self.next_index,
        }
        tmp = self.out / "progress.json.tmp"
        tmp.write_text(json.dumps(body, indent=1))
        tmp.replace(self.out / "progress.json")

    def save_robots(self) -> None:
        for key, text in self.robots.texts.items():
            if key.startswith(SITE) and not (self.out / "robots.txt").exists():
                (self.out / "robots.txt").write_text(text)

    def emit(self, rec: dict[str, Any]) -> None:
        part = self.out / f"pdp/part-{self.start:06d}-{self.stamp}.jsonl.gz"  # one per run
        with gzip.open(part, "at", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    def one(self, url: str, ctx: CollectionContext) -> bool:
        """Fetch one page; False when the run must stop."""
        before = self.usage()["bytes_via_proxy"]
        request = FetchRequest(
            url=HttpUrl(url),
            kind=PayloadKind.HTML,
            locale=Locale.EN,
            render=True,
            capture_json=self.capture_json,
        )
        try:
            result = self.fetcher.fetch(request, ctx)
        except RobotsRefusedError:
            self.counts["robots_refused_page"] += 1
            self.say(f"refused by robots (not fetched, 0 bytes): {url}")
            return True
        except (
            SourceStoppedError,
            ProxyBudgetExceededError,
            ProxyConfigError,
            TransportError,
        ) as exc:
            self.stopped = f"stopped: {type(exc).__name__}: {exc}"
            return False
        finally:
            self.save_robots()
        page_bytes = int(self.usage()["bytes_via_proxy"]) - int(before)
        self.emit(page_record(result, page_bytes))
        self.counts["pdp_fetched"] += 1
        state = result.block.kind.value if result.block else f"http {result.http_status}"
        self.say(f"page {self.counts['pdp_fetched']}: {state}, {page_bytes} bytes: {url}")
        if result.block is not None:
            self.counts[f"block_{result.block.kind.value}"] += 1
            if result.block.marks_source_blocked:
                self.challenged = True
                self.stopped = f"stopped: {result.block.kind.value} {result.block.http_status}"
                return False
        elif result.http_status == 200:
            self.counts["pdp_ok"] += 1
        else:
            self.counts[f"http_{result.http_status}"] += 1
        if self.fetcher.stopped_sources():
            self.stopped = f"stopped: {self.fetcher.stopped_sources()}"
            return False
        return True

    def say(self, line: str) -> None:
        print(line, file=self.console, flush=True)

    def summary(self) -> str:
        """The one line the operator pastes back: status, pages, bytes, GB, USD, challenges."""
        use = self.usage()
        challenged = self.challenged
        if self.stopped in DONE:
            status = self.stopped
        elif challenged:
            status = "stopped_at_challenge"
        elif "proxy_byte_cap" in self.stopped or "ProxyBudgetExceeded" in self.stopped:
            status = "cap_reached"
        elif "signal" in self.stopped:
            status = "stopped_by_operator"
        else:
            status = "stopped_error"
        return (
            f"ULTA TEST RESULT: status={status} pages_ok={self.counts['pdp_ok']}/{len(self.batch)}"
            f" robots_refused={self.counts['robots_refused_page']}"
            f" proxy_bytes={use['bytes_via_proxy']} gb={use['gb']} usd={use.get('usd', '0.00')}"
            f" challenge={'yes' if challenged else 'no'} detail={self.stopped!r}"
        )

    def finish(self) -> None:
        """Final status file, manifest and summary line (also after a stop or a signal)."""
        self.progress()
        (self.out / "manifest.json").write_text(
            json.dumps(
                {
                    "proxy_usage": [u.manifest() for u in self.fetcher.proxy_usage()],
                    "stopped": self.stopped,
                    "counts": dict(self.counts),
                    "graphql": dict(self.graphql.counts),
                    "pages": self.audit.pages,
                },
                indent=1,
                default=str,
            )
        )
        self.say(self.summary())

    def document(self, url: str, ctx: CollectionContext) -> str | None:
        """One sitemap through the same route (robots-checked by the fetcher); None: stopped."""
        request = FetchRequest(
            url=HttpUrl(url), kind=PayloadKind.XML, locale=Locale.EN, render=True
        )
        try:
            result = self.fetcher.fetch(request, ctx)
        except RobotsRefusedError:
            self.stopped = f"stopped: sitemap refused by robots: {url}"
            return None
        except (
            SourceStoppedError,
            ProxyBudgetExceededError,
            ProxyConfigError,
            TransportError,
        ) as exc:
            self.stopped = f"stopped: {type(exc).__name__}: {exc}"
            return None
        finally:
            self.save_robots()
        self.counts["sitemap_fetched"] += 1
        if result.block is not None:
            self.counts[f"block_{result.block.kind.value}"] += 1
            self.challenged = self.challenged or result.block.marks_source_blocked
            self.stopped = f"stopped: sitemap {result.block.kind.value} {result.block.http_status}"
            return None
        if result.http_status != 200:
            self.stopped = f"stopped: sitemap http {result.http_status}: {url}"
            return None
        return result.body.decode("utf-8", "replace")

    def snapshot_id(self) -> str | None:
        path = self.out / SNAPSHOT
        return str(json.loads(path.read_text())["snapshot_id"]) if path.exists() else None

    def rules(self) -> RobotsRules | None:
        text = next((t for k, t in self.robots.texts.items() if k.startswith(SITE)), None)
        return None if text is None else RobotsRules(text, self.robots.agent)

    def sitemap_urls(self, ctx: CollectionContext) -> list[str] | None:  # noqa: PLR0911
        """Robots-allowed EN product URLs from the sitemap index and its product sitemaps,
        written to ``urls_full_en.txt``; reused (never re-fetched) when that file exists."""
        saved = self.out / URLS_FULL
        if saved.exists():
            urls = [u for u in saved.read_text().splitlines() if u.strip()]
            self.say(f"SITEMAP: reusing {URLS_FULL} ({len(urls)} urls), nothing re-fetched")
            return urls
        index = self.document(SITEMAP_INDEX, ctx)
        rules = self.rules()
        if index is None or rules is None:
            if index is not None:
                self.stopped = "stopped: robots.txt unavailable (fail closed)"
            return None
        try:
            children = [u for u in child_sitemaps(index, rules) if "product" in u]
        except DiscoveryError as exc:
            self.stopped = f"stopped: sitemap index unreadable: {exc}"
            return None
        if not children:
            self.stopped = "stopped: no robots-allowed product sitemap in the index"
            return None
        found: set[str] = set()
        for child in children:
            self.sleep(random.uniform(0.0, 5.0))  # noqa: S311 - pacing jitter, not crypto
            doc = self.document(child, ctx)
            if doc is None:
                return None
            try:
                keys = discover_sitemap(doc, rules)
            except DiscoveryError as exc:
                self.stopped = f"stopped: product sitemap unreadable: {child}: {exc}"
                return None
            found.update(k.product_url for k in keys if k.product_url.startswith(f"{BASE}/en/"))
        urls = sorted(found)
        tmp = saved.with_suffix(".tmp")
        tmp.write_text("".join(f"{u}\n" for u in urls))
        tmp.replace(saved)
        snapshot = {
            "snapshot_id": f"ulta-ae-{self.stamp}",
            "created": self.started,
            "urls": len(urls),
        }
        (self.out / SNAPSHOT).write_text(json.dumps(snapshot, indent=1))
        return urls

    def estimate(self, n: int) -> str:
        low, high = n * PAGE_INTERVAL_S / 3600, n * 2 * PAGE_INTERVAL_S / 3600
        per = self.est_bytes_per_page
        size = f"est {gb(n * per)} GB" if per else "est ? GB (set EST_BYTES_PER_PAGE)"
        return f"est {low:.1f}-{high:.1f} h, {size}"

    def run(self, ctx: CollectionContext) -> None:
        if self.url_source == "sitemap":
            urls = self.sitemap_urls(ctx)
            if urls is None:
                self.progress()
                return
            self.urls = urls
            self.say(f"SITEMAP: {len(urls)} urls, {self.estimate(len(urls))}")
            if not urls:
                self.stopped = "stopped: sitemap gave no robots-allowed EN product URLs"
                return
        end = len(self.urls) if self.max_pages is None else self.start + self.max_pages
        self.batch = self.urls[self.start : end]
        self.counts["discovered"] = len(self.urls)
        if self.max_pages == 0:
            self.stopped = "enumerated"
            return
        self.say(
            f"this run: {len(self.batch)} pages from index {self.start}, "
            f"{self.estimate(len(self.batch))}"
        )
        self.progress()
        for i, url in enumerate(self.batch):
            if i:
                self.sleep(random.uniform(0.0, 5.0))  # noqa: S311 - pacing jitter, not crypto
            go_on = self.one(url, ctx)
            if go_on:
                self.next_index = self.start + i + 1
            self.progress()
            if not go_on:
                return
        whole = self.start == 0 and self.next_index >= len(self.urls)
        self.stopped = "complete" if whole else "batch_complete"


def make_run(  # noqa: PLR0913 - keyword-only test seams
    out: Path,
    urls: list[str],
    pol: FetchPolicy,
    secret_reader: SecretReader,
    *,
    inner: ProxyTransportFactory = default_proxy_transport,
    pacer: HostPacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    capture_json: bool = False,
    console: TextIO = sys.stdout,
    **options: Any,
) -> Run:
    """The fetcher on main's rung-5 route, with robots text, graphql and audit recording."""
    out.mkdir(parents=True, exist_ok=True)
    audit = AuditSink(out / "audit.jsonl")
    audit_log.addHandler(audit)
    audit_log.setLevel(logging.INFO)
    robots = RecordingTagger(pol.robots_group_agent)
    graphql = GraphqlCounter(inner)
    fetcher = Fetcher(
        policy=pol,
        evidence=LocalEvidenceStore(out / "evidence"),
        pacer=pacer,
        robots=robots,
        proxy_transport_factory=graphql.factory,
        secret_reader=secret_reader,
    )
    return Run(
        out,
        urls,
        fetcher,
        robots=robots,
        graphql=graphql,
        audit=audit,
        sleep=sleep,
        capture_json=capture_json,
        console=console,
        **options,
    )


def run_options(env: Mapping[str, str], out: Path) -> dict[str, Any]:
    """URL source, resume point, page bound and estimate input from the environment.

    ``URL_SOURCE`` ``file`` (default: ``URLS_FILE``) or ``sitemap``; ``MAX_PAGES`` a number
    (``0``: enumerate only) or ``all``; ``START_INDEX`` a number or ``auto`` (the previous run's
    ``next_index`` in ``OUT_DIR/progress.json``); ``EST_BYTES_PER_PAGE`` from the test manifest.
    """
    source = env.get("URL_SOURCE", "file")
    if source not in {"file", "sitemap"}:
        msg = f"URL_SOURCE must be file or sitemap, not {source!r}"
        raise SystemExit(msg)
    raw_max = env.get("MAX_PAGES", "20").strip().lower()
    start_raw = env.get("START_INDEX", "0").strip().lower()
    previous = out / "progress.json"
    if start_raw == "auto":
        start = (
            int(json.loads(previous.read_text()).get("next_index", 0)) if previous.exists() else 0
        )
    else:
        start = int(start_raw)
    est = env.get("EST_BYTES_PER_PAGE", "").strip()
    if start < 0 or (raw_max != "all" and int(raw_max) < 0):
        msg = "START_INDEX and MAX_PAGES must not be negative"
        raise SystemExit(msg)
    return {
        "url_source": source,
        "start": start,
        "max_pages": None if raw_max == "all" else int(raw_max),
        "est_bytes_per_page": int(est) if est else None,
    }


def archive_previous(out: Path) -> None:
    """Copy an earlier run's status and manifest aside when a run resumes in the same folder.

    A copy, not a move: if this run then fails before it writes its own status, the earlier
    ``progress.json`` (and its ``next_index``) is still in place for ``START_INDEX=auto``.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for name in ("progress.json", "manifest.json"):
        if (out / name).exists():
            shutil.copy2(out / name, out / f"{Path(name).stem}-before-{stamp}.json")


def folder_allowance_used(out: Path) -> int:
    """The highest ``prior_bytes + bytes_via_proxy`` recorded by any earlier run in ``out``."""
    used = [0]
    for path in out.glob("progress*.json"):
        proxy = json.loads(path.read_text()).get("proxy") or {}
        used.append(int(proxy.get("allowance_used", 0)))
    return max(used)


def floored_prior(env: Mapping[str, str], out: Path) -> tuple[int, str]:
    """``prior_bytes(env)``, but never below what earlier runs in this folder already used."""
    given, floor = prior_bytes(env), folder_allowance_used(out)
    if floor > given:
        return floor, f"PRIOR: PRIOR_GB is below this folder's record; using {floor} bytes"
    return given, f"PRIOR: {given} bytes (folder record {floor})"


def prior_bytes(env: Mapping[str, str]) -> int:
    """Bytes already used from the allowance: ``PRIOR_BYTES``, else ``PRIOR_GB`` (the IPRoyal
    dashboard figure) rounded up to a whole byte. One of them is required: no default of 0."""
    if env.get("PRIOR_BYTES"):
        return int(env["PRIOR_BYTES"])
    if not env.get("PRIOR_GB"):
        msg = "set PRIOR_GB (IPRoyal dashboard, GB used, rounded up) or PRIOR_BYTES"
        raise SystemExit(msg)
    return math.ceil(Decimal(env["PRIOR_GB"]) * _BYTES_PER_GB)


def main() -> int:
    out = Path(os.environ["OUT_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    options = run_options(os.environ, out)
    prior, prior_note = floored_prior(os.environ, out)
    urls = []
    if options["url_source"] == "file":
        text = Path(os.environ["URLS_FILE"]).read_text()
        urls = [u.strip() for u in text.splitlines() if u.strip()]
    pol = policy(
        prior,
        os.environ["OWNER_APPROVAL_REF"],
        os.environ["SECRET_RESOURCE"],
    )
    run = make_run(
        out,
        urls,
        pol,
        SecretManagerReader(token=operator_token()),
        capture_json=os.environ.get("CAPTURE_JSON") == "1",
        **options,
    )

    def on_signal(signum: int, _frame: object) -> None:
        run.stopped = f"stopped: signal {signum} (operator stop)"
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    archive_previous(out)  # only once setup has succeeded
    run.say(prior_note)
    run.say(
        f"ulta.ae proxied run: source={options['url_source']} start={options['start']}"
        f" max_pages={options['max_pages']} prior_bytes={pol_prior(pol)} out={out}"
    )
    try:
        with run.fetcher:
            run.run(context(datetime.now(UTC)))
    finally:
        run.finish()
    return 0 if run.stopped in DONE else 2


def pol_prior(pol: FetchPolicy) -> int:
    return next(iter(pol.residential_proxy.values())).prior_bytes


if __name__ == "__main__":
    sys.exit(main())
