"""Fetch ulta.ae product pages through the owner-approved residential proxy (rung 5), fetch only.

ADR-0006 Amendment 2 and the coordinator's GO for the ~20-page test. Everything goes through
main's ``pi_fetch.Fetcher`` rung-5 route: the pinned stock WebKit, the proxy credentials read from
Secret Manager at runtime inside this process (never printed), robots.txt obeyed on every request
(pages and sub-requests), heavy assets and third-party hosts aborted, bytes metered against the
cap. Nothing here retries, solves or switches: the first challenge, 401/403/407, proxy error or
second 429 in a row stops the source (``SourceStoppedError``) and the run ends.

Writes to ``OUT_DIR`` (the loader's input layout, see ``load.py``):

* ``pdp/part-0000.jsonl.gz``: one record per page load (``html`` + robots-allowed ``captures``);
* ``robots.txt``: the robots.txt the fetcher obeyed for www.ulta.ae (read through the same route);
* ``progress.json``: the status file, rewritten after every page (counts, proxy bytes, GB, USD);
* ``audit.jsonl``: the fetcher's audit events (per-page proxy bytes and abort reasons);
* ``evidence/``: the fetcher's content-addressed raw payloads.

Env: ``OUT_DIR``, ``URLS_FILE`` (one product URL per line), ``PRIOR_BYTES`` (required; bytes
already used from the allowance), ``OWNER_APPROVAL_REF``, ``SECRET_RESOURCE``, ``CAPTURE_JSON``
(default off), ``MAX_PAGES`` (default 20), ``GOOGLE_APPLICATION_CREDENTIALS`` (the service
account that may read the secret).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import random
import signal
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl

from pi_core import CollectionContext, FetchMethod, LadderRung, Locale, Market, SourceContext
from pi_fetch.cache import LocalEvidenceStore
from pi_fetch.ladder import (
    Fetcher,
    ProxyTransportFactory,
    SourceStoppedError,
    default_proxy_transport,
)
from pi_fetch.pacing import HostPacer, RobotsRefusedError, RobotsTagger
from pi_fetch.policy import FetchPlan, FetchPolicy
from pi_fetch.proxy import (
    ProxyBudgetExceededError,
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
PAGE_INTERVAL_S = 5.0  # the pacer's floor; a random 0-5 s is added: one page per 5-10 s
_BYTES_PER_GB = Decimal(1000**3)
audit_log = logging.getLogger("pi_fetch.audit")


class RecordingTagger(RobotsTagger):
    """The fetcher's robots tagger, also keeping the robots.txt text it was given (per key)."""

    def __init__(self, user_agent: str = "*") -> None:
        super().__init__(user_agent)
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


def service_account_token() -> str:
    """An access token for the mounted service account (in memory only, never logged)."""
    # google-auth is installed in the job image only (tools/ulta_snapshot/Dockerfile).
    from google.auth.transport.requests import (  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415
        Request,
    )
    from google.oauth2 import (  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415
        service_account,
    )

    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(Request())
    return str(creds.token)


def context(now: datetime) -> CollectionContext:
    return CollectionContext(
        source_context=SourceContext(
            id=SOURCE_ID,
            source_id=SOURCE_ID,
            country=Market.UAE,
            locale=Locale.EN,
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
        #: Off by default: on main (1758af4) ``FetchResult`` refuses ``captured_json`` at rung 5
        #: (types.py), so capturing would fail the fetch. The DOM + JSON-LD path needs none.
        self.capture_json: bool = extra.get("capture_json", False)
        self.counts: Counter[str] = Counter()
        self.started = datetime.now(UTC).isoformat()
        self.stopped = "running"
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
        }
        tmp = self.out / "progress.json.tmp"
        tmp.write_text(json.dumps(body, indent=1))
        tmp.replace(self.out / "progress.json")

    def save_robots(self) -> None:
        for key, text in self.robots.texts.items():
            if key.startswith(SITE) and not (self.out / "robots.txt").exists():
                (self.out / "robots.txt").write_text(text)

    def emit(self, rec: dict[str, Any]) -> None:
        with gzip.open(self.out / "pdp/part-0000.jsonl.gz", "at", encoding="utf-8") as fh:
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
            return True
        except (SourceStoppedError, ProxyBudgetExceededError, TransportError) as exc:
            self.stopped = f"stopped: {type(exc).__name__}: {exc}"
            return False
        finally:
            self.save_robots()
        page_bytes = int(self.usage()["bytes_via_proxy"]) - int(before)
        self.emit(page_record(result, page_bytes))
        self.counts["pdp_fetched"] += 1
        if result.block is not None:
            self.counts[f"block_{result.block.kind.value}"] += 1
            if result.block.marks_source_blocked:
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

    def run(self, ctx: CollectionContext) -> None:
        self.counts["discovered"] = len(self.urls)
        self.progress()
        for i, url in enumerate(self.urls):
            if i:
                self.sleep(random.uniform(0.0, 5.0))  # noqa: S311 - pacing jitter, not crypto
            go_on = self.one(url, ctx)
            self.progress()
            if not go_on:
                return
        self.stopped = "complete"


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
    )


def main() -> int:
    out = Path(os.environ["OUT_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    urls = [u.strip() for u in Path(os.environ["URLS_FILE"]).read_text().splitlines() if u.strip()]
    urls = urls[: int(os.environ.get("MAX_PAGES", "20"))]
    pol = policy(
        int(os.environ["PRIOR_BYTES"]),
        os.environ["OWNER_APPROVAL_REF"],
        os.environ["SECRET_RESOURCE"],
    )
    run = make_run(
        out,
        urls,
        pol,
        SecretManagerReader(token=service_account_token),
        capture_json=os.environ.get("CAPTURE_JSON") == "1",
    )
    fetcher, graphql, audit = run.fetcher, run.graphql, run.audit

    def on_term(signum: int, _frame: object) -> None:
        run.stopped = f"stopped: signal {signum}"
        run.progress()
        sys.exit(1)

    signal.signal(signal.SIGTERM, on_term)
    try:
        with fetcher:
            run.run(context(datetime.now(UTC)))
    finally:
        run.progress()
        (out / "manifest.json").write_text(
            json.dumps(
                {
                    "proxy_usage": [u.manifest() for u in fetcher.proxy_usage()],
                    "stopped": run.stopped,
                    "graphql": dict(graphql.counts),
                    "pages": audit.pages,
                },
                indent=1,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
