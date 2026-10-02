"""Real-browser capture: one stock Chromium page view per plan item (ADR-0006 rung 2).

Ordinary access only. A stock Playwright Chromium opens each plan URL in a fresh browser
process (no cookies carried over, no login, no cart; see ``pw`` for the launch flags), paced at
about one navigation per second with jitter, after the host's robots.txt (read through the same
browser stack, fail closed) allows it. No stealth, no fingerprint changes, no challenge solving,
no proxy: a block or a challenge page is recorded with its evidence and that host is stopped for
the rest of the run. Every request the page makes passes the ``Gate`` first (policy module):
documents and redirect hops stay on the storefront's https hosts, pictures and beacons never
leave, and the hosts that scripts and data calls went to are counted so a later run can enforce
the list.

Per page we keep the server's document, the DOM after the network settled, the final URL and
redirect chain, headers, a screenshot and timings. Output under ``gs://$BUCKET/$PREFIX/`` (or
``file:<dir>``): ``manifest.json`` at start, ``pages/part-NNNN.jsonl.gz``, ``raw/`` and
``shots/`` blobs by digest, ``robots.json``, ``status.json`` at the end. Nothing is ever
rewritten.
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
from typing import Any
from urllib.parse import urljoin, urlsplit

from browser_capture.policy import ENFORCE_HOSTS, RECORD, Gate, host_refusal
from browser_capture.session import Answer, Session, TransportError, Visit
from page_capture import blocks, robots
from page_capture.plan import Item, Plan, parse_plan, shard
from page_capture.store import Parts, Store

MIN_PACE_S = 1.0
BATCH = 100
TRANSPORT_ERROR_LIMIT = 5
RATE_LIMIT_STREAK = 2
BACKOFF_S, BACKOFF_MAX_S = 60, 900
MAX_REDIRECTS = 5  # RFC 9309 asks for at least five on robots.txt
HEAD_CHARS = 2000

OK, HTTP_ERROR, BLOCKED, RATE_LIMITED, TRANSPORT_ERROR = (
    "ok",
    "http_error",
    "blocked",
    "rate_limited",
    "transport_error",
)
HOP_HOST_REFUSED = "hop_host_refused"
ROBOTS_DISALLOWED, ROBOTS_UNAVAILABLE = "robots_disallowed", "robots_unavailable"
SKIPPED_CUTOFF, SKIPPED_HOST_STOPPED = "skipped_cutoff", "skipped_host_stopped"


class Stop(Exception):  # noqa: N818 - a signal, not an error
    pass


@dataclass(frozen=True)
class Config:
    bucket: str
    prefix: str
    plan_uri: str
    cutoff: datetime
    pace_s: float = 1.0
    jitter_s: float = 0.5
    limit: int = 0
    egress: str = "unknown"
    hosts: tuple[str, ...] = ()  # storefront hosts; empty = the plan's own item hosts
    subresources: str = RECORD  # record | enforce
    subresource_hosts: tuple[str, ...] = ()
    screenshot: bool = True
    nav_timeout_s: float = 30.0
    idle_timeout_s: float = 20.0
    task_index: int = 0
    task_count: int = 1
    git_sha: str = ""


def _hosts(value: str) -> tuple[str, ...]:
    return tuple(h.strip().lower() for h in value.split(",") if h.strip())


def config_from_env(env: Mapping[str, str]) -> Config:
    pace = float(env.get("PACE", "1.0"))
    if pace < MIN_PACE_S:
        raise ValueError(f"PACE must be >= {MIN_PACE_S} s (politeness floor, ADR-0005)")
    jitter = float(env.get("JITTER", "0.5"))
    if jitter < 0:
        raise ValueError("JITTER must be >= 0")
    cutoff = datetime.fromisoformat(env["CUTOFF"])
    if cutoff.tzinfo is None:
        raise ValueError("CUTOFF must carry a timezone offset")
    index, count = (
        int(env.get("CLOUD_RUN_TASK_INDEX", "0")),
        int(env.get("CLOUD_RUN_TASK_COUNT", "1")),
    )
    if count < 1 or not 0 <= index < count:
        raise ValueError(f"task index {index} outside 0..{count - 1}")
    sub = env.get("SUBRESOURCES", RECORD).strip()
    sub_hosts: tuple[str, ...] = () if sub == RECORD else _hosts(sub)
    policy = RECORD if sub == RECORD else ENFORCE_HOSTS
    if policy == ENFORCE_HOSTS and not sub_hosts:
        raise ValueError("SUBRESOURCES must be 'record' or a comma-separated host list")
    return Config(
        bucket=env["BUCKET"],
        prefix=env["PREFIX"],
        plan_uri=env["PLAN"],
        cutoff=cutoff,
        pace_s=pace,
        jitter_s=jitter,
        limit=int(env.get("LIMIT", "0")),
        egress=env.get("EGRESS", "unknown"),
        hosts=_hosts(env.get("HOSTS", "")),
        subresources=policy,
        subresource_hosts=sub_hosts,
        screenshot=env.get("SCREENSHOT", "1") == "1",
        nav_timeout_s=float(env.get("NAV_TIMEOUT", "30")),
        idle_timeout_s=float(env.get("IDLE_TIMEOUT", "20")),
        task_index=index,
        task_count=count,
        git_sha=env.get("GIT_SHA", ""),
    )


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


class Job:
    def __init__(  # noqa: PLR0913 - keyword-only injection points for tests
        self,
        cfg: Config,
        session: Session,
        *,
        store: Store | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.session = session
        self.store = store or Store(cfg.bucket, cfg.prefix)
        self.clock = clock
        self.sleep = sleep
        self.rand = rand
        self.now = now
        self.started = clock()
        self.tag = f"t{cfg.task_index}" if cfg.task_count > 1 else ""
        self.parts = Parts(
            self.store, BATCH, on_flush=self.progress, label=f"{self.tag}-" if self.tag else ""
        )
        self.allowed: frozenset[str] = frozenset(cfg.hosts)
        self.hosts: dict[str, HostState] = {}
        self.counts: dict[str, int] = {}
        self.robots_log: dict[str, dict[str, Any]] = {}
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

    def named(self, base: str) -> str:
        if not self.tag:
            return base
        stem, dot, ext = base.rpartition(".")
        return f"{stem}.{self.tag}{dot}{ext}"

    def progress(self) -> None:
        state = {
            "started": self.started.isoformat(),
            "updated": self.clock().isoformat(),
            "cutoff": self.cfg.cutoff.isoformat(),
            "counts": self.counts,
            "hosts_stopped": {h.host: h.stopped for h in self.hosts.values() if h.stopped},
            "stopped": self.stopped,
        }
        self.store.put(self.named("progress.json"), json.dumps(state).encode(), gz=False)

    def manifest(self, plan_sha: str, total: int) -> None:
        engine = self.session.engine
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
            "pace_s": self.cfg.pace_s,
            "jitter_s": self.cfg.jitter_s,
            "cutoff": self.cfg.cutoff.isoformat(),
            "started": self.started.isoformat(),
            "python": platform.python_version(),
            "git_sha": self.cfg.git_sha,
            "hosts": sorted(self.allowed),
            "subresources": {
                "policy": self.cfg.subresources,
                "hosts": sorted(self.cfg.subresource_hosts),
            },
            "screenshot": self.cfg.screenshot,
            "nav_timeout_s": self.cfg.nav_timeout_s,
            "idle_timeout_s": self.cfg.idle_timeout_s,
            "browser": {
                "engine": engine.name,
                "version": engine.version,
                "playwright": engine.playwright,
                "user_agent": engine.user_agent,
                "viewport": list(engine.viewport),
                "headless": engine.headless,
                "stealth": False,
                "proxy": None,
                "launch_args": list(engine.launch_args),
                "fresh_browser_per_page": True,
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
        blocked = {h.host: h.stopped for h in self.hosts.values() if h.stopped}
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
            "hosts_blocked": blocked,
            "counts": self.counts,
        }
        self.store.put(self.named("status.json"), json.dumps(status).encode(), gz=False)
        self.progress()

    # ------------------------------------------------------------------ pacing
    def pace(self, host: HostState) -> None:
        delay = host.robots.crawl_delay if host.robots and host.robots.crawl_delay else 0.0
        base = max(self.cfg.pace_s, delay) + self.rand() * self.cfg.jitter_s
        wait = base - (self.now() - host.last)
        if host.last and wait > 0:
            self.sleep(wait)
        host.last = self.now()

    def stop_host(self, host: HostState, reason: str, url: str) -> None:
        if host.stopped is None:
            host.stopped = reason
            host.stopped_url = url
            self.count("hosts_stopped")
            print(json.dumps({"host_stopped": host.host, "reason": reason, "url": url}), flush=True)

    # ------------------------------------------------------------------ robots
    def answer(self, url: str) -> Answer | None:
        """One paced plain GET through the browser stack; None on a transport error."""
        host = self.host_for(url)
        self.pace(host)
        try:
            return self.session.answer(url, timeout_s=self.cfg.nav_timeout_s)
        except TransportError as exc:
            self.count("transport_error")
            print(json.dumps({"transport_error": url, "reason": str(exc)}), flush=True)
            return None

    def robots_verdict(self, url: str) -> str:
        """``allowed`` / ``disallowed`` / ``unavailable``; reads the host's robots.txt once.

        Hops stay on the same https host (fail closed otherwise). A challenge or block on
        robots.txt itself is the wall: the host is stopped and nothing else is asked of it.
        """
        host = self.host_for(url)
        if host.robots is not None:
            return host.robots.verdict(url)
        parts = urlsplit(url)
        robots_url = current = f"https://{parts.netloc}/robots.txt"
        hops = 0
        got: Answer | None = None
        verdict: robots.Robots | None = None
        while verdict is None:
            got = self.answer(current)
            if got is None:
                verdict = robots.Robots(robots.UNAVAILABLE, reason="transport error")
            elif 300 <= got.status < 400:
                target = urljoin(current, got.location)
                hops += 1
                why = host_refusal(target, frozenset({host.host}))
                if why is not None:
                    verdict = robots.Robots(
                        robots.UNAVAILABLE, reason=f"robots.txt redirect to {target}: {why}"
                    )
                elif hops > MAX_REDIRECTS or not got.location:
                    verdict = robots.Robots(robots.UNAVAILABLE, reason="too many redirects")
                else:
                    current = target
            else:
                text = got.body.decode("utf-8", "replace")
                verdict = robots.from_response(
                    got.status, got.content_type, text, self.session.engine.user_agent
                )
                wall = blocks.detect(got.status, text)
                if wall is not None:
                    verdict = robots.Robots(
                        robots.UNAVAILABLE, reason=f"{wall.kind} on robots.txt: {wall.reason}"
                    )
                    self.count(f"block_{wall.kind}")
                    self.stop_host(host, f"{wall.kind} on robots.txt: {wall.reason}", current)
        body = got.body if got is not None else b""
        digest = hashlib.sha256(body).hexdigest()
        raw = self.store.put(f"raw/{digest}.robots.txt.gz", body) if body else None
        host.robots = verdict
        self.count(f"robots_{verdict.state}")
        self.robots_log[host.host] = {
            "url": robots_url,
            "at": self.clock().isoformat(),
            "status": got.status if got is not None else None,
            "state": verdict.state,
            "reason": verdict.reason,
            "rules": len(verdict.rules),
            "crawl_delay": verdict.crawl_delay,
            "redirects": hops,
            "sha256": digest,
            "raw": raw,
        }
        return verdict.verdict(url)

    # ------------------------------------------------------------------- items
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
        why = host_refusal(item.url, self.allowed)
        if why is not None:  # a plan URL off the storefront is never opened
            self.record_page({**rec, "state": HOP_HOST_REFUSED, "reason": why}, host)
            return
        verdict = self.robots_verdict(item.url)  # a wall on robots.txt stops the host too
        if verdict != robots.ALLOWED:
            state = ROBOTS_DISALLOWED if verdict == robots.DISALLOWED else ROBOTS_UNAVAILABLE
            reason = host.robots.reason if host.robots else ""
            self.record_page({**rec, "state": state, "reason": reason}, host)
            return
        gate = Gate(self.allowed, self.cfg.subresources, frozenset(self.cfg.subresource_hosts))
        self.pace(host)
        rec["at"] = self.clock().isoformat()
        try:
            visit = self.session.visit(
                item.url,
                gate,
                nav_timeout_s=self.cfg.nav_timeout_s,
                idle_timeout_s=self.cfg.idle_timeout_s,
                screenshot=self.cfg.screenshot,
            )
        except TransportError as exc:
            rec["requests"] = dict(gate.counts)
            if gate.refused_document is not None:
                url, why = gate.refused_document
                self.count("hop_host_refused")
                self.stop_host(host, f"redirect off the storefront to {url}: {why}", item.url)
                rec |= {"state": HOP_HOST_REFUSED, "reason": f"{url}: {why}", "final_url": url}
            else:
                host.err_streak += 1
                self.count("transport_error")
                if host.err_streak >= TRANSPORT_ERROR_LIMIT:
                    self.stop_host(
                        host, f"{TRANSPORT_ERROR_LIMIT} consecutive transport errors", item.url
                    )
                rec |= {"state": TRANSPORT_ERROR, "reason": str(exc)}
            self.record_page(rec, host)
            return
        host.err_streak = 0
        self.record_visit(rec, host, visit)

    def record_visit(self, rec: dict[str, Any], host: HostState, visit: Visit) -> None:
        rec |= {
            "final_url": visit.final_url,
            "status": visit.status,
            "redirects": len(visit.hops),
            "hops": [{"url": h.url, "status": h.status} for h in visit.hops],
            "nav_ms": visit.nav_ms,
            "settle_ms": visit.settle_ms,
            "idle_timeout": visit.idle_timeout,
            "requests": dict(visit.gate_counts),
            "hosts_seen": dict(visit.hosts_seen),
        }
        chain = [h.url for h in visit.hops] + [visit.final_url]
        off = next(((u, w) for u in chain if (w := host_refusal(u, self.allowed))), None)
        if off is not None:  # the gate should have aborted this; the evidence is not kept
            url, why = off
            self.count("hop_host_refused")
            self.stop_host(host, f"document reached {url}: {why}", str(rec["url"]))
            rec |= {"state": HOP_HOST_REFUSED, "reason": f"{url}: {why}"}
            self.record_page(rec, host)
            return
        if visit.status is not None:
            self.count(f"http_{visit.status}")
        server_text = visit.server_body.decode("utf-8", "replace")
        status = visit.status if visit.status is not None else 0
        wall = blocks.detect(status, server_text) or blocks.detect(status, visit.rendered)
        rec |= self.store_evidence(visit)
        if wall is None:
            host.rl_streak = 0
            if visit.status is None:
                rec |= {"state": HTTP_ERROR, "reason": "no document response"}
            else:
                rec["state"] = OK if 200 <= visit.status < 300 else HTTP_ERROR
            self.record_page(rec, host)
            return
        self.count(f"block_{wall.kind}")
        self.parts.emit(
            "errors",
            {
                "url": rec["url"],
                "final_url": visit.final_url,
                "at": rec["at"],
                "status": visit.status,
                "block": wall.kind,
                "reason": wall.reason,
                "title": visit.title,
                "head": server_text[:HEAD_CHARS],
            },
        )
        if wall.kind == blocks.RATE_LIMITED:
            host.rl_streak += 1
            if host.rl_streak >= RATE_LIMIT_STREAK:
                self.stop_host(host, f"{RATE_LIMIT_STREAK} consecutive 429", str(rec["url"]))
            else:
                delay = min(BACKOFF_S * 2 ** (host.rl_streak - 1), BACKOFF_MAX_S)
                print(json.dumps({"backoff_s": delay, "host": host.host}), flush=True)
                self.sleep(delay)
            rec |= {"state": RATE_LIMITED, "reason": wall.reason}
        else:
            self.stop_host(host, f"{wall.kind}: {wall.reason}", str(rec["url"]))
            rec |= {"state": BLOCKED, "reason": wall.reason}
        self.record_page(rec, host)

    def store_evidence(self, visit: Visit) -> dict[str, Any]:
        """Server document, rendered DOM and screenshot by digest; empty bodies are not stored."""
        out: dict[str, Any] = {"title": visit.title}
        server_sha = hashlib.sha256(visit.server_body).hexdigest()
        rendered = visit.rendered.encode()
        rendered_sha = hashlib.sha256(rendered).hexdigest()
        out["bytes_server"] = len(visit.server_body)
        out["sha256_server"] = server_sha
        out["raw_server"] = (
            self.store.put(f"raw/{server_sha}.server.html.gz", visit.server_body)
            if visit.server_body
            else None
        )
        out["bytes_rendered"] = len(rendered)
        out["sha256_rendered"] = rendered_sha
        out["raw_rendered"] = (
            self.store.put(f"raw/{rendered_sha}.html.gz", rendered) if rendered else None
        )
        self.count("pages_bytes", len(visit.server_body) + len(rendered))
        if visit.screenshot:
            shot_sha = hashlib.sha256(visit.screenshot).hexdigest()
            out["shot"] = self.store.put(
                f"shots/{shot_sha}.png", visit.screenshot, gz=False, content_type="image/png"
            )
        else:
            out["shot"] = None
        return out

    def record_page(self, rec: dict[str, Any], host: HostState) -> None:
        state = str(rec["state"])
        self.count(f"pages_{state}")
        host.counts[state] = host.counts.get(state, 0) + 1
        self.parts.emit("pages", rec)

    # --------------------------------------------------------------------- run
    def load(self) -> None:
        raw = self.store.read_uri(self.cfg.plan_uri)
        self.plan = parse_plan(raw)
        mine = shard(self.plan.items, self.cfg.task_index, self.cfg.task_count)
        self.items = mine[: self.cfg.limit or None]
        if not self.allowed:
            hosts = {urlsplit(it.url).hostname or "" for it in self.plan.items}
            self.allowed = frozenset(h.lower() for h in hosts if h)
        self.manifest(hashlib.sha256(raw).hexdigest(), len(self.plan.items))
        print(
            json.dumps(
                {
                    "plan": self.cfg.plan_uri,
                    "source": self.plan.source,
                    "items_total": len(self.plan.items),
                    "items_shard": len(self.items),
                    "hosts": sorted(self.allowed),
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
            if item.kind == "html":
                self.one(item)
            if (i + 1) % 50 == 0:
                self.progress()


def _sigterm(signum: int, frame: object) -> None:
    raise Stop("sigterm")


def main() -> int:
    from browser_capture.pw import PlaywrightSession  # noqa: PLC0415 - only in the job image

    signal.signal(signal.SIGTERM, _sigterm)
    launch_args = tuple(a for a in os.environ.get("CHROMIUM_ARGS", "").split() if a)
    session = PlaywrightSession(launch_args)
    job = Job(config_from_env(os.environ), session)
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
        session.close()
        print(json.dumps({"stopped": job.stopped, "counts": job.counts}), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
