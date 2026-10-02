"""Capture job: raw pages, their embedded JSON and their pictures, exactly as served.

Ordinary access only (ADR-0005/0006): plain httpx with stock browser headers, one paced GET per
URL, a fresh cookie jar per request, no retries, no impersonation and **no proxy of any kind**
(pictures are never fetched through a proxy; this job cannot be configured with one). robots.txt
is read once per host through the same client before the host's first request and obeyed
fail-closed (see ``robots.py``); image hosts are treated exactly like page hosts.

Stop rules apply per host, so one blocked host does not end the run for the others:
- a challenge marker or 401/403 stops the host (``blocked``);
- a 429 backs off 60 s, doubling to 900 s; two in a row stop the host (``rate_limited``);
- ten consecutive transport errors stop the host.
Every remaining item of a stopped host is recorded ``skipped_host_stopped``; nothing is retried
from this or any other egress. Past ``CUTOFF`` the rest is recorded ``skipped_cutoff``.

Output under ``gs://$BUCKET/$PREFIX/`` (or ``file:<dir>``): ``manifest.json`` at start,
``pages/``, ``images/`` and ``errors/`` JSONL parts, raw bodies in ``raw/<sha256>.<ext>.gz`` (every
2xx/4xx/5xx body, so a block keeps its evidence), pictures in ``images/<sha256>.<ext>``,
``robots.json`` (what each host's robots.txt said), ``progress.json`` and, once at the end,
``status.json`` (``outcome``: complete | cutoff | error).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import signal
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from page_capture import blocks, proxy, robots
from page_capture.plan import Item, Plan, parse_plan, shard
from page_capture.store import Parts, Store

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
MIN_PACE_S = 1.0
MIN_IMAGE_PACE_S = 0.5
BATCH = 100
TRANSPORT_ERROR_LIMIT = 10
RATE_LIMIT_STREAK = 2
BACKOFF_S, BACKOFF_MAX_S = 60, 900
HEAD_CHARS = 2000
ACCEPT = {
    "html": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "xml": "application/xml,text/xml;q=0.9,*/*;q=0.8",
    "json": "application/json,text/plain,*/*",
    "image": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "robots": "text/plain,*/*;q=0.8",
}
RAW_EXT = {"html": "html", "json": "json", "xml": "xml"}
IMAGE_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
    "image/svg+xml": "svg",
}
# item states
OK, HTTP_ERROR, BLOCKED, RATE_LIMITED, TRANSPORT_ERROR = (
    "ok",
    "http_error",
    "blocked",
    "rate_limited",
    "transport_error",
)
ROBOTS_DISALLOWED, ROBOTS_UNAVAILABLE = "robots_disallowed", "robots_unavailable"
SKIPPED_CUTOFF, SKIPPED_HOST_STOPPED, DUPLICATE = (
    "skipped_cutoff",
    "skipped_host_stopped",
    "duplicate",
)
PROXY_CAP = "proxy_cap"


class Stop(Exception):  # noqa: N818
    pass


class ResponseLike(Protocol):
    status_code: int

    @property
    def content(self) -> bytes: ...
    @property
    def text(self) -> str: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def url(self) -> Any: ...


class CookiesLike(Protocol):
    def clear(self) -> None: ...


class HttpClient(Protocol):
    @property
    def cookies(self) -> CookiesLike: ...
    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> ResponseLike: ...


@dataclass(frozen=True)
class Config:
    bucket: str
    prefix: str
    plan_uri: str
    cutoff: datetime
    pace_s: float = 1.5
    image_pace_s: float = 1.0
    images: bool = True
    limit: int = 0
    egress: str = "unknown"
    user_agent: str = USER_AGENT
    task_index: int = 0
    task_count: int = 1
    git_sha: str = ""
    proxy_hosts: tuple[str, ...] = ()
    proxy_secret: str = ""
    proxy_byte_cap: int = proxy.DEFAULT_BYTE_CAP


def config_from_env(env: Mapping[str, str]) -> Config:
    pace = float(env.get("PACE", "1.5"))
    if pace < MIN_PACE_S:
        raise ValueError(f"PACE must be >= {MIN_PACE_S} s (politeness floor, ADR-0005)")
    image_pace = float(env.get("IMAGE_PACE", "1.0"))
    if image_pace < MIN_IMAGE_PACE_S:
        raise ValueError(f"IMAGE_PACE must be >= {MIN_IMAGE_PACE_S} s")
    cutoff = datetime.fromisoformat(env["CUTOFF"])
    if cutoff.tzinfo is None:
        raise ValueError("CUTOFF must carry a timezone offset")
    index, count = (
        int(env.get("CLOUD_RUN_TASK_INDEX", "0")),
        int(env.get("CLOUD_RUN_TASK_COUNT", "1")),
    )
    if count < 1 or not 0 <= index < count:
        raise ValueError(f"task index {index} outside 0..{count - 1}")
    proxy_hosts = tuple(
        h.strip().lower() for h in env.get("PROXY_HOSTS", "").split(",") if h.strip()
    )
    proxy_secret = env.get("PROXY_SECRET", "").strip()
    if proxy_hosts and not proxy_secret:
        raise ValueError("PROXY_HOSTS needs PROXY_SECRET (a Secret Manager version name)")
    if proxy_secret and not proxy_hosts:
        raise ValueError("PROXY_SECRET without PROXY_HOSTS: name the hosts the proxy is for")
    proxy_cap = int(env.get("PROXY_BYTE_CAP", str(proxy.DEFAULT_BYTE_CAP)))
    if proxy_cap <= 0 or proxy_cap > proxy.DEFAULT_BYTE_CAP:
        raise ValueError(f"PROXY_BYTE_CAP must be within 1..{proxy.DEFAULT_BYTE_CAP} (owner cap)")
    return Config(
        bucket=env["BUCKET"],
        prefix=env["PREFIX"],
        plan_uri=env["PLAN"],
        cutoff=cutoff,
        pace_s=pace,
        image_pace_s=image_pace,
        images=env.get("IMAGES", "1") == "1",
        limit=int(env.get("LIMIT", "0")),
        egress=env.get("EGRESS", "unknown"),
        user_agent=env.get("UA", USER_AGENT),
        task_index=index,
        task_count=count,
        git_sha=env.get("GIT_SHA", ""),
        proxy_hosts=proxy_hosts,
        proxy_secret=proxy_secret,
        proxy_byte_cap=proxy_cap,
    )


def headers(user_agent: str, locale: str, kind: str, extra: Mapping[str, str]) -> dict[str, str]:
    lang, _, region = locale.partition("-")
    other = "en" if lang == "ar" else "ar"
    accept_language = f"{lang}-{region or 'AE'},{lang};q=0.9,{other};q=0.8"
    return {
        "User-Agent": user_agent,
        "Accept": ACCEPT[kind],
        "Accept-Language": accept_language,
        **extra,
    }


def raw_ext(kind: str, content_type: str) -> str:
    ct = content_type.lower()
    if "json" in ct:
        return "json"
    if "xml" in ct and "html" not in ct:
        return "xml"
    if "html" in ct:
        return "html"
    return RAW_EXT.get(kind, "txt")


def image_ext(content_type: str) -> str:
    return IMAGE_EXT.get(content_type.split(";", maxsplit=1)[0].strip().lower(), "bin")


@dataclass
class HostState:
    host: str
    last: float = 0.0
    robots: robots.Robots | None = None
    stopped: str | None = None
    stopped_url: str | None = None
    rl_streak: int = 0
    err_streak: int = 0
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Fetched:
    state: str  # ok | http_error | blocked | rate_limited | transport_error
    status: int | None
    final_url: str
    content_type: str
    body: bytes
    ms: int
    at: str
    reason: str = ""


class Job:
    def __init__(  # noqa: PLR0913 - keyword-only injection points for tests
        self,
        cfg: Config,
        *,
        client: HttpClient | None = None,
        store: Store | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        proxy_client: HttpClient | None = None,
    ) -> None:
        self.cfg = cfg
        self.client: HttpClient = client or httpx.Client(follow_redirects=True, timeout=30.0)
        self.proxy_client: HttpClient | None = proxy_client
        if cfg.proxy_hosts and self.proxy_client is None:
            self.proxy_client = proxy.proxy_client(proxy.endpoint_from_secret(cfg.proxy_secret))
        self.meter = proxy.Meter(cfg.proxy_byte_cap)
        self.store = store or Store(cfg.bucket, cfg.prefix)
        self.clock = clock
        self.sleep = sleep
        self.started = clock()
        # A sharded run has one writer per task; names carry the task index so the
        # tasks never overwrite each other's parts or summaries.
        self.tag = f"t{cfg.task_index}" if cfg.task_count > 1 else ""
        self.parts = Parts(
            self.store, BATCH, on_flush=self.progress, label=f"{self.tag}-" if self.tag else ""
        )
        self.hosts: dict[str, HostState] = {}
        self.counts: dict[str, int] = {}
        self.robots_log: dict[str, dict[str, Any]] = {}
        self.seen_images: dict[str, str] = {}
        self.cut = False
        self.stopped: str | None = None
        self.plan: Plan | None = None
        self.items: list[Item] = []

    # ------------------------------------------------------------- bookkeeping
    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def host_for(self, url: str) -> HostState:
        host = urlsplit(url).netloc.lower()
        if host not in self.hosts:
            self.hosts[host] = HostState(host)
        return self.hosts[host]

    def progress(self) -> None:
        state = {
            "started": self.started.isoformat(),
            "updated": self.clock().isoformat(),
            "cutoff": self.cfg.cutoff.isoformat(),
            "counts": self.counts,
            "hosts_stopped": {h.host: h.stopped for h in self.hosts.values() if h.stopped},
            "stopped": self.stopped,
            "proxy_bytes": self.meter.used,
        }
        self.store.put(self.named("progress.json"), json.dumps(state).encode(), gz=False)

    def named(self, base: str) -> str:
        """``progress.json`` for a single task, ``progress.t1.json`` for task 1 of a shard."""
        if not self.tag:
            return base
        stem, dot, ext = base.rpartition(".")
        return f"{stem}.{self.tag}{dot}{ext}"

    def manifest(self, plan_sha: str, total: int) -> None:
        doc = {
            "source": self.plan.source if self.plan else None,
            "retailer": self.plan.retailer if self.plan else None,
            "plan": self.cfg.plan_uri,
            "plan_sha256": plan_sha,
            "items_total": total,
            "items_shard": len(self.items),
            "shard": {"index": self.cfg.task_index, "count": self.cfg.task_count},
            "limit": self.cfg.limit,
            "egress": self.cfg.egress,
            "user_agent": self.cfg.user_agent,
            "pace_s": self.cfg.pace_s,
            "image_pace_s": self.cfg.image_pace_s,
            "images": self.cfg.images,
            "cutoff": self.cfg.cutoff.isoformat(),
            "started": self.started.isoformat(),
            "python": platform.python_version(),
            "httpx": httpx.__version__,
            "git_sha": self.cfg.git_sha,
            "proxy": {
                "hosts": list(self.cfg.proxy_hosts),
                "secret": self.cfg.proxy_secret,  # the resource name only, never the payload
                "byte_cap": self.cfg.proxy_byte_cap,
            },
        }
        self.store.put(self.named("manifest.json"), json.dumps(doc).encode(), gz=False)

    def finish(self) -> None:
        self.parts.flush_all()
        self.store.put(
            self.named("robots.json"),
            json.dumps(self.robots_log, ensure_ascii=False).encode(),
            gz=False,
        )
        outcome = "complete"
        if self.stopped and self.stopped.startswith("error"):
            outcome = "error"
        elif self.cut or self.stopped:
            outcome = "cutoff"
        status = {
            "state": "finished",
            "outcome": outcome,
            "stopped": self.stopped,
            "prefix": self.cfg.prefix,
            "started": self.started.isoformat(),
            "finished": self.clock().isoformat(),
            "cutoff": self.cfg.cutoff.isoformat(),
            "hosts": {
                h.host: {"stopped": h.stopped, "stopped_url": h.stopped_url, "counts": h.counts}
                for h in self.hosts.values()
            },
            "counts": self.counts,
            "proxy_bytes": self.meter.used,
            "proxy_byte_cap": self.cfg.proxy_byte_cap,
        }
        self.store.put(self.named("status.json"), json.dumps(status).encode(), gz=False)
        self.progress()

    # ------------------------------------------------------------------ fetch
    def pace(self, host: HostState, pace_s: float) -> None:
        delay = host.robots.crawl_delay if host.robots and host.robots.crawl_delay else 0.0
        base = max(pace_s, delay)
        wait = base + random.uniform(0.0, 0.6 * base) - (time.monotonic() - host.last)  # noqa: S311
        if wait > 0:
            self.sleep(wait)
        host.last = time.monotonic()

    def fetch(self, url: str, hdrs: Mapping[str, str], kind: str, pace_s: float) -> Fetched:
        """One paced GET on an unstopped host. Applies the stop rules; never retries."""
        host = self.host_for(url)
        at = self.clock().isoformat()
        client = self.client_for(host, kind)
        if client is None:
            self.stop_host(host, f"proxy byte cap {self.cfg.proxy_byte_cap} reached", url)
            return Fetched(PROXY_CAP, None, url, "", b"", 0, at, "proxy byte cap")
        self.pace(host, pace_s)
        client.cookies.clear()
        t0 = time.monotonic()
        try:
            r = client.get(url, headers=hdrs)
        except httpx.HTTPError as exc:
            host.err_streak += 1
            self.count("transport_error")
            reason = repr(exc)
            if host.err_streak >= TRANSPORT_ERROR_LIMIT:
                self.stop_host(host, f"{TRANSPORT_ERROR_LIMIT} consecutive transport errors", url)
            return Fetched(TRANSPORT_ERROR, None, url, "", b"", 0, at, reason)
        host.err_streak = 0
        if client is self.proxy_client:
            n = proxy.wire_bytes(r)
            self.meter.charge(n)
            self.count("proxy_bytes", n + proxy.REQUEST_ALLOWANCE)
            self.count("proxy_requests")
        ms = int((time.monotonic() - t0) * 1000)
        content_type = r.headers.get("content-type", "")
        self.count(f"http_{r.status_code}")
        scan = r.status_code != 200 or kind in ("html", "json")
        verdict = blocks.detect(r.status_code, r.text if scan else "")
        if verdict is None:
            host.rl_streak = 0
            state = OK if 200 <= r.status_code < 300 else HTTP_ERROR
            return Fetched(state, r.status_code, str(r.url), content_type, r.content, ms, at)
        self.count(f"block_{verdict.kind}")
        self.parts.emit(
            "errors",
            {
                "url": url,
                "at": at,
                "status": r.status_code,
                "block": verdict.kind,
                "reason": verdict.reason,
                "head": r.text[:HEAD_CHARS],
            },
        )
        if verdict.kind == blocks.RATE_LIMITED:
            host.rl_streak += 1
            if host.rl_streak >= RATE_LIMIT_STREAK:
                self.stop_host(host, f"{RATE_LIMIT_STREAK} consecutive 429", url)
            else:
                delay = min(BACKOFF_S * 2 ** (host.rl_streak - 1), BACKOFF_MAX_S)
                print(json.dumps({"backoff_s": delay, "host": host.host}), flush=True)
                self.sleep(delay)
            return Fetched(
                RATE_LIMITED, r.status_code, str(r.url), content_type, r.content, ms, at, "http 429"
            )
        self.stop_host(host, f"{verdict.kind}: {verdict.reason}", url)
        return Fetched(
            BLOCKED, r.status_code, str(r.url), content_type, r.content, ms, at, verdict.reason
        )

    def client_for(self, host: HostState, kind: str) -> HttpClient | None:
        """The direct client, or the proxy client for a named page host; None once the cap is hit.

        Pictures never go through the proxy, whatever host serves them.
        """
        if kind == "image" or host.host not in self.cfg.proxy_hosts or self.proxy_client is None:
            return self.client
        if self.meter.exhausted:
            return None
        return self.proxy_client

    def stop_host(self, host: HostState, reason: str, url: str) -> None:
        host.stopped, host.stopped_url = reason, url
        self.count("hosts_stopped")
        print(json.dumps({"host_stopped": host.host, "reason": reason, "url": url}), flush=True)

    def store_raw(self, kind: str, got: Fetched) -> tuple[str, str | None]:
        digest = hashlib.sha256(got.body).hexdigest()
        if not got.body:
            return digest, None
        return digest, self.store.put(
            f"raw/{digest}.{raw_ext(kind, got.content_type)}.gz", got.body
        )

    # ----------------------------------------------------------------- robots
    def robots_verdict(self, url: str, pace_s: float) -> str:
        """``allowed`` / ``disallowed`` / ``unavailable``; reads the host's robots.txt once."""
        host = self.host_for(url)
        if host.robots is None:
            parts = urlsplit(url)
            robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
            hdrs = headers(self.cfg.user_agent, "en-AE", "robots", {})
            got = self.fetch(robots_url, hdrs, "robots", pace_s)
            text = got.body.decode("utf-8", "replace")
            verdict = robots.from_response(got.status, got.content_type, text, self.cfg.user_agent)
            if got.state in (BLOCKED, RATE_LIMITED):
                verdict = robots.Robots(robots.UNAVAILABLE, reason=f"{got.state}: {got.reason}")
            digest, raw = self.store_raw("robots", got)
            host.robots = verdict
            self.count(f"robots_{verdict.state}")
            self.robots_log[host.host] = {
                "url": robots_url,
                "at": got.at,
                "status": got.status,
                "state": verdict.state,
                "reason": verdict.reason,
                "rules": len(verdict.rules),
                "crawl_delay": verdict.crawl_delay,
                "sha256": digest,
                "raw": raw,
            }
        return host.robots.verdict(url)

    # ------------------------------------------------------------------ items
    def one(self, item: Item) -> None:
        rec: dict[str, Any] = {
            "id": item.id,
            "url": item.url,
            "locale": item.locale,
            "kind": item.kind,
            "ref": dict(item.ref),
        }
        host = self.host_for(item.url)
        if self.cut:
            self.record_page({**rec, "state": SKIPPED_CUTOFF}, host)
            return
        if host.stopped:
            self.record_page({**rec, "state": SKIPPED_HOST_STOPPED, "reason": host.stopped}, host)
            return
        verdict = self.robots_verdict(item.url, self.cfg.pace_s)
        if verdict != robots.ALLOWED:
            state = ROBOTS_DISALLOWED if verdict == robots.DISALLOWED else ROBOTS_UNAVAILABLE
            reason = host.robots.reason if host.robots else ""
            self.record_page({**rec, "state": state, "reason": reason}, host)
            return
        assert self.plan is not None  # noqa: S101 - set by run() before any item
        hdrs = headers(
            self.cfg.user_agent,
            item.locale,
            item.kind,
            {**self.plan.default_headers, **item.headers},
        )
        got = self.fetch(item.url, hdrs, item.kind, self.cfg.pace_s)
        digest, raw = self.store_raw(item.kind, got)
        rec |= {
            "final_url": got.final_url,
            "at": got.at,
            "status": got.status,
            "ms": got.ms,
            "bytes": len(got.body),
            "sha256": digest,
            "content_type": got.content_type,
            "raw": raw,
            "state": got.state,
        }
        if got.reason:
            rec["reason"] = got.reason
        self.count("pages_bytes", len(got.body))
        self.record_page(rec, host)

    def record_page(self, rec: dict[str, Any], host: HostState) -> None:
        state = str(rec["state"])
        self.count(f"pages_{state}")
        host.counts[f"pages_{state}"] = host.counts.get(f"pages_{state}", 0) + 1
        self.parts.emit("pages", rec)
        n = self.counts.get("pages_ok", 0)
        if state == OK and (n in (1, 10, 100) or n % 500 == 0):
            print(json.dumps({"milestone": "pages_ok", "n": n, "at": rec.get("at")}), flush=True)

    def image(self, item: Item, url: str) -> None:
        rec: dict[str, Any] = {"item_id": item.id, "url": url}
        host = self.host_for(url)
        if url in self.seen_images:
            self.record_image({**rec, "state": DUPLICATE, "object": self.seen_images[url]}, host)
            return
        if self.cut:
            self.record_image({**rec, "state": SKIPPED_CUTOFF}, host)
            return
        if host.stopped:
            self.record_image({**rec, "state": SKIPPED_HOST_STOPPED, "reason": host.stopped}, host)
            return
        verdict = self.robots_verdict(url, self.cfg.image_pace_s)
        if verdict != robots.ALLOWED:
            state = ROBOTS_DISALLOWED if verdict == robots.DISALLOWED else ROBOTS_UNAVAILABLE
            reason = host.robots.reason if host.robots else ""
            self.record_image({**rec, "state": state, "reason": reason}, host)
            return
        hdrs = headers(self.cfg.user_agent, item.locale, "image", {})
        got = self.fetch(url, hdrs, "image", self.cfg.image_pace_s)
        digest = hashlib.sha256(got.body).hexdigest()
        obj: str | None = None
        if got.state == OK and got.body:
            obj = self.store.put(
                f"images/{digest}.{image_ext(got.content_type)}",
                got.body,
                gz=False,
                content_type=got.content_type.split(";")[0],
            )
            self.seen_images[url] = obj
        elif got.body:
            _, obj = self.store_raw("image", got)
        rec |= {
            "final_url": got.final_url,
            "at": got.at,
            "status": got.status,
            "bytes": len(got.body),
            "sha256": digest,
            "content_type": got.content_type,
            "object": obj,
            "state": got.state,
        }
        if got.reason:
            rec["reason"] = got.reason
        self.count("images_bytes", len(got.body))
        self.record_image(rec, host)

    def record_image(self, rec: dict[str, Any], host: HostState) -> None:
        state = str(rec["state"])
        self.count(f"images_{state}")
        host.counts[f"images_{state}"] = host.counts.get(f"images_{state}", 0) + 1
        self.parts.emit("images", rec)

    # -------------------------------------------------------------------- run
    def load(self) -> None:
        raw = self.store.read_uri(self.cfg.plan_uri)
        self.plan = parse_plan(raw)
        mine = shard(self.plan.items, self.cfg.task_index, self.cfg.task_count)
        self.items = mine[: self.cfg.limit or None]
        self.manifest(hashlib.sha256(raw).hexdigest(), len(self.plan.items))
        print(
            json.dumps(
                {
                    "plan": self.cfg.plan_uri,
                    "source": self.plan.source,
                    "items_total": len(self.plan.items),
                    "items_shard": len(self.items),
                }
            ),
            flush=True,
        )

    def run(self) -> None:
        self.load()
        for i, item in enumerate(self.items):
            if not self.cut and self.clock() >= self.cfg.cutoff:
                self.cut = True
                print(json.dumps({"cutoff": self.cfg.cutoff.isoformat()}), flush=True)
            if item.kind != "images":  # an images item is a second, pictures-only pass
                self.one(item)
            if self.cfg.images:
                for url in item.images:
                    self.image(item, url)
            if (i + 1) % 50 == 0:
                self.progress()


def _sigterm(signum: int, frame: object) -> None:
    raise Stop("sigterm")


def main() -> int:
    signal.signal(signal.SIGTERM, _sigterm)
    job = Job(config_from_env(os.environ))
    print(json.dumps({"start": job.started.isoformat(), "cutoff": job.cfg.cutoff.isoformat()}))
    code = 0
    try:
        job.run()
    except Stop as exc:
        job.stopped = str(exc)
    except Exception as exc:
        job.stopped, code = f"error: {exc!r}", 1
    finally:
        job.finish()
        print(json.dumps({"stopped": job.stopped, "counts": job.counts}), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
