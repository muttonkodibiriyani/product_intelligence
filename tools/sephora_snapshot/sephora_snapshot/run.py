"""Sephora Middle East snapshot job (UAE: task 01a0f424-006c; KSA: task 01a0fc6d, COUNTRY=SA).
Ordinary access only (ADR-0005/0006).

Plain httpx with normal browser headers from a single egress (Cloud Run me-central1), sequential,
~1 req/s with jitter, fresh cookie jar per request, no retries. Robots: tag_only (owner-approved
for Sephora). Order: sitemaps -> EN PDPs -> tRPC availability -> AR PDPs, until CUTOFF.

Stop rules: a challenge or 401/403 -> stop the whole job (source blocked; nothing is retried from
this or any other egress). 429 -> back off 60 s doubling; 3 consecutive -> stop. Items not fetched
by the cutoff are simply absent (not_observed as of the cutoff).
With PLAN=<object> the job skips seeding. A ``price`` plan first re-reads the EN PDPs in the plan's
order (a new dated price read). Then tRPC runs (unless TRPC=0) for the plan's ``trpc`` list, or the
whole order if it has none. Last come AR PDPs for the plan entries that carry an AR URL.
With AUTO=1 (unattended, ADR-0009) the job derives PREFIX and CUTOFF itself, refuses to fetch
outside the 18:00Z-02:00Z window, seeds from the sitemaps and orders the night gap-first from what
earlier runs covered (see cadence.py); each product gets its EN page, then its stock read.
Output: batched jsonl.gz parts + progress.json under gs://$BUCKET/$PREFIX/. Every run ends with
covered.json.gz (what it read, for the next plan) and status.json (the terminal marker).
Capture options (task 01a0fc6d, off by default so the UAE loader sees what it always saw):
COUNTRY=SA selects the KSA storefront (/sa-en, /sa-ar, locales en-SA/ar-SA); FULL=1 keeps every
productDetails field (long text included); RAW=1 stores each page as served at raw/<lang>-<pid>
.html.gz and records its sha256; IMAGES=1 downloads every picture an EN page exposes to
images/<sha256>.<ext> (image-host robots.txt obeyed fail-closed, own pace IMAGE_PACE >= 0.5 s,
never through a proxy; a block on the image host ends the picture pass, pages continue).
"""

from __future__ import annotations

import gzip
import json
import os
import random
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from sephora_snapshot import cadence, extract, images

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
BATCH = 200
MIN_PACE_S = 1.0
MIN_IMAGE_PACE_S = 0.5
IMAGE_AGENT_NAME = "pi-snapshot"  # our robots.txt group name on image hosts


class Stop(Exception):  # noqa: N818
    pass


def headers(locale: str, kind: str) -> dict[str, str]:
    accept = {
        "html": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "xml": "application/xml,text/xml;q=0.9,*/*;q=0.8",
        "json": "application/json,text/plain,*/*",
        "image": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }[kind]
    cc = locale.rsplit("-", 1)[-1] if "-" in locale else "AE"
    lang = f"ar-{cc},ar;q=0.9,en;q=0.8" if locale.startswith("ar") else f"en-{cc},en;q=0.9,ar;q=0.8"
    return {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": lang}


class Job:
    def __init__(self) -> None:
        self.started = datetime.now(UTC)
        self.bucket_name = os.environ["BUCKET"]
        self.auto = os.environ.get("AUTO") == "1"
        self.outside: str | None = None
        self.refused: str | None = None
        if self.auto:
            # A stale one-shot env must not ride along with a scheduled run: the run is refused
            # (no request), but still leaves its status.json under its own new prefix.
            given = [k for k in ("PREFIX", "CUTOFF", "PLAN") if os.environ.get(k)]
            if given:
                self.refused = f"AUTO=1 derives PREFIX/CUTOFF and its plan: unset {given}"
            self.prefix = cadence.auto_prefix(
                self.started,
                os.environ.get("CLOUD_RUN_EXECUTION", ""),
                os.environ.get("CLOUD_RUN_TASK_ATTEMPT", ""),
            )
            try:
                self.cutoff = cadence.auto_cutoff(self.started)
            except cadence.OutsideWindow as exc:
                self.outside, self.cutoff = str(exc), self.started
        else:
            self.prefix = os.environ["PREFIX"]
            self.cutoff = datetime.fromisoformat(os.environ["CUTOFF"])
        self.pace_s = float(os.environ.get("PACE", "1.0"))
        if self.pace_s < MIN_PACE_S:
            raise ValueError(f"PACE must be >= {MIN_PACE_S} s (politeness floor, ADR-0005)")
        self.capture_options()
        # Recorded in progress.json: the loader only marks a run 'succeeded' for an unlimited
        # full run with the stock pass on (see load.Loader.finish).
        self.mode = "auto" if self.auto else "plan" if os.environ.get("PLAN") else "full"
        self.limit = int(os.environ.get("LIMIT", "0"))
        self.trpc_on = os.environ.get("TRPC", "1") == "1"
        self.local = (
            self.bucket_name.removeprefix("file:") if self.bucket_name.startswith("file:") else None
        )
        if self.local is None:
            from google.cloud import storage  # noqa: PLC0415

            self.bucket = storage.Client().bucket(self.bucket_name)
        if self.auto and self.prefix_in_use():
            # Never write over another run's parts or status (a retry or re-execute).
            raise ValueError(f"prefix {self.prefix!r} already holds objects")
        self.client = httpx.Client(follow_redirects=True, timeout=30.0)
        self.last = 0.0
        self.buf: dict[str, list[dict[str, Any]]] = {}
        self.parts: dict[str, int] = {}
        self.counts: dict[str, int] = {}
        self.rl_streak = 0
        self.err_streak = 0
        self.stopped: str | None = None
        # What this run read, by product: the next AUTO run plans from it.
        self.covered: dict[str, dict[str, dict[str, Any]]] = {
            "pdp_en": {},
            "trpc": {},
            "attempted_en": {},
        }

    def capture_options(self) -> None:
        """Storefront (ADR-0005 UAE default; KSA = "SA") and the capture options of task 01a0fc6d:
        FULL=1 keeps every productDetails field, RAW=1 stores each page's HTML, IMAGES=1
        downloads the pictures each EN page exposes (own pace, image-host robots, no proxy)."""
        self.country = extract.check_country(os.environ.get("COUNTRY", "AE"))
        self.locales = extract.locales(self.country)
        self.full = os.environ.get("FULL", "0") == "1"
        self.raw = os.environ.get("RAW", "0") == "1"
        self.images_on = os.environ.get("IMAGES", "0") == "1"
        self.image_pace_s = float(os.environ.get("IMAGE_PACE", "1.0"))
        if self.image_pace_s < MIN_IMAGE_PACE_S:
            raise ValueError(f"IMAGE_PACE must be >= {MIN_IMAGE_PACE_S} s")
        self.image_robots: dict[str, images.Robots] = {}
        self.image_seen: set[str] = set()
        self.image_last = 0.0
        self.image_rl_streak = 0
        self.image_err_streak = 0

    # ---------------------------------------------------------------- output
    def put(self, name: str, data: bytes, gz: bool = True) -> None:
        body = gzip.compress(data) if gz else data
        if self.local is not None:
            path = os.path.join(self.local, self.prefix, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(body)
            return
        self.bucket.blob(f"{self.prefix}/{name}").upload_from_string(body)

    def prefix_in_use(self) -> bool:
        if self.local is not None:
            return os.path.exists(os.path.join(self.local, self.prefix))
        blobs = self.bucket.client.list_blobs(self.bucket, prefix=f"{self.prefix}/", max_results=1)
        return any(True for _ in blobs)

    def emit(self, stream: str, rec: dict[str, Any]) -> None:
        self.buf.setdefault(stream, []).append(rec)
        if len(self.buf[stream]) >= BATCH:
            self.flush(stream)

    def flush(self, stream: str) -> None:
        recs = self.buf.get(stream) or []
        if not recs:
            return
        n = self.parts.get(stream, 0)
        data = "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in recs).encode()
        self.put(f"{stream}/part-{n:04d}.jsonl.gz", data)
        self.parts[stream] = n + 1
        self.buf[stream] = []
        self.progress()

    def progress(self) -> None:
        state = {
            "started": self.started.isoformat(),
            "updated": datetime.now(UTC).isoformat(),
            "cutoff": self.cutoff.isoformat(),
            "mode": self.mode,
            "limit": self.limit,
            "trpc": self.trpc_on,
            "country": self.country,
            "full": self.full,
            "raw": self.raw,
            "images": self.images_on,
            "counts": self.counts,
            "stopped": self.stopped,
        }
        self.put("progress.json", json.dumps(state).encode(), gz=False)

    def count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    # ---------------------------------------------------------------- fetch
    def pace(self) -> None:
        wait = self.pace_s + random.uniform(0.0, 0.6 * self.pace_s) - (time.monotonic() - self.last)  # noqa: S311
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()

    def get(self, url: str, locale: str, kind: str) -> tuple[int, bytes, dict[str, Any]] | None:
        """One paced GET. Returns None on transport error (recorded); raises Stop on a block."""
        if datetime.now(UTC) >= self.cutoff:
            raise Stop("cutoff")
        self.pace()
        self.client.cookies.clear()
        t0 = time.monotonic()
        meta: dict[str, Any] = {"url": url, "locale": locale, "at": datetime.now(UTC).isoformat()}
        try:
            r = self.client.get(url, headers=headers(locale, kind))
        except httpx.HTTPError as exc:
            self.err_streak += 1
            self.count("transport_error")
            self.emit("errors", {**meta, "error": repr(exc)})
            if self.err_streak >= 10:
                raise Stop("10 consecutive transport errors") from exc
            return None
        self.err_streak = 0
        meta |= {
            "status": r.status_code,
            "ms": int((time.monotonic() - t0) * 1000),
            "bytes": len(r.content),
        }
        verdict = extract.detect_block(
            r.status_code, r.text if kind != "xml" or r.status_code != 200 else ""
        )
        if verdict is not None:
            self.emit(
                "errors",
                {**meta, "block": verdict.kind, "reason": verdict.reason, "head": r.text[:2000]},
            )
            self.count(f"block_{verdict.kind}")
            if verdict.kind == "rate_limited":
                self.rl_streak += 1
                if self.rl_streak >= 3:
                    raise Stop("3 consecutive 429")
                delay = min(60 * 2 ** (self.rl_streak - 1), 900)
                print(json.dumps({"backoff_s": delay, "url": url}), flush=True)
                time.sleep(delay)
                return None
            raise Stop(f"{verdict.kind}: {verdict.reason} at {url}")
        self.rl_streak = 0
        return r.status_code, r.content, meta

    # ---------------------------------------------------------------- phases
    def seed(self) -> dict[str, dict[str, str]]:
        ids: dict[str, dict[str, str]] = {}
        for locale in self.locales:
            for url in extract.sitemap_urls(locale):
                got = self.get(url, locale, "xml")
                if got is None or got[0] != 200:
                    self.count("sitemap_fail")
                    continue
                self.count("sitemap_ok")
                for lang, pid, pdp in extract.parse_sitemap(got[1], self.country):
                    if pid.startswith("P"):
                        ids.setdefault(pid, {})[lang] = pdp
        self.put("seed.json", json.dumps(ids, ensure_ascii=False).encode())
        self.counts["seed_pids"] = len(ids)
        self.counts["seed_en"] = sum(1 for v in ids.values() if "en" in v)
        self.counts["seed_ar"] = sum(1 for v in ids.values() if "ar" in v)
        self.progress()
        print(json.dumps({"seed": self.counts}), flush=True)
        return ids

    def pdp(self, pid: str, lang: str, url: str) -> None:
        self.count(f"pdp_{lang}_attempted")
        if lang == "en":  # a failed page is planned by its last attempt, not as unread forever
            self.covered["attempted_en"][pid] = {"at": datetime.now(UTC).isoformat()}
        locale = f"{lang}-{self.country}"
        got = self.get(url, locale, "html")
        if got is None:
            return
        status, body, meta = got
        rec: dict[str, Any] = {**meta, "pid": pid, "lang": lang}
        if self.raw:  # the page as served, kept beside the extract (parse later, re-parse ever)
            rec["raw"] = f"raw/{lang}-{pid}.html.gz"
            rec["sha256"] = images.sha256_hex(body)
            self.put(rec["raw"], body)
        if status != 200:
            self.count(f"pdp_{lang}_http_{status}")
            self.emit("errors", rec)
            return
        try:
            rec["extract"] = extract.extract_pdp(body.decode("utf-8", "replace"), full=self.full)
        except ValueError as exc:
            self.count(f"pdp_{lang}_parse_error")
            self.emit("errors", {**rec, "error": str(exc)})
            if not self.raw:
                self.put(f"raw/{lang}-{pid}.html.gz", body)
            return
        self.count(f"pdp_{lang}_ok")
        if self.images_on and lang == "en":
            self.pictures(pid, rec["extract"]["productDetails"])
        if lang == "en":
            self.covered["pdp_en"][pid] = {
                "at": meta["at"],
                "multi_price": cadence.multi_price(rec["extract"]["productDetails"]),
            }
        n = self.counts[f"pdp_{lang}_ok"]
        if n in (1, 10, 100) or n % 500 == 0:
            print(json.dumps({"milestone": f"pdp_{lang}_ok", "n": n, "at": meta["at"]}), flush=True)
        self.emit(f"pdp_{lang}", rec)

    # ---------------------------------------------------------------- pictures
    def image_pace(self) -> None:
        base = self.image_pace_s
        wait = base + random.uniform(0.0, 0.5 * base) - (time.monotonic() - self.image_last)  # noqa: S311
        if wait > 0:
            time.sleep(wait)
        self.image_last = time.monotonic()

    def image_allowed(self, url: str) -> bool:
        """Fail-closed robots check for an image host, read once per host (paced, same client)."""
        host = images.hosts([url]).pop()
        robots = self.image_robots.get(host)
        if robots is None:
            self.image_pace()
            status: int | None
            try:
                r = self.client.get(f"https://{host}/robots.txt", headers=headers("en", "html"))
                text, status = r.text, r.status_code
                if status == 200 and "<html" in text[:2000].lower():
                    status = None  # a viewer or challenge page is not a robots.txt
            except httpx.HTTPError:
                text, status = "", None
            robots = images.Robots(text, status, IMAGE_AGENT_NAME)
            self.image_robots[host] = robots
            self.emit("images_robots", {"host": host, "status": status, "rules": len(robots.rules)})
        return robots.allows(url)

    def pictures(self, pid: str, details: dict[str, Any]) -> None:
        """Download every picture an EN page exposes, once per URL per run, at the image pace.
        A block on the image host ends the picture pass (pages continue); 429 backs off."""
        for url in images.image_urls(details):
            if not self.images_on:
                return
            if url in self.image_seen:
                continue
            self.image_seen.add(url)
            if datetime.now(UTC) >= self.cutoff:
                raise Stop("cutoff")
            if not self.image_allowed(url):
                self.count("image_robots_refused")
                self.emit("images", {"pid": pid, "url": url, "state": "robots_refused"})
                continue
            self.picture(pid, url)

    def picture(self, pid: str, url: str) -> None:
        """One paced picture download; records one ``images`` row whatever happens."""
        self.image_pace()
        self.client.cookies.clear()
        t0 = time.monotonic()
        rec: dict[str, Any] = {"pid": pid, "url": url, "at": datetime.now(UTC).isoformat()}
        try:
            r = self.client.get(url, headers=headers(self.locales[0], "image"))
        except httpx.HTTPError as exc:
            self.image_err_streak += 1
            self.count("image_transport_error")
            self.emit("images", {**rec, "state": "transport_error", "error": repr(exc)})
            if self.image_err_streak >= 10:
                self.images_on = False
                self.count("images_stopped_transport")
            return
        self.image_err_streak = 0
        ct = r.headers.get("content-type", "")
        is_image = ct.lower().startswith("image/")
        rec |= {"status": r.status_code, "ms": int((time.monotonic() - t0) * 1000)}
        rec |= {"bytes": len(r.content), "content_type": ct}
        if r.status_code == 429:
            self.image_rl_streak += 1
            self.count("image_http_429")
            self.emit("images", {**rec, "state": "rate_limited"})
            if self.image_rl_streak >= 3:
                self.images_on = False
                self.count("images_stopped_rate_limited")
                return
            time.sleep(min(60 * 2 ** (self.image_rl_streak - 1), 900))
            return
        self.image_rl_streak = 0
        if r.status_code in (401, 403) or (r.status_code == 200 and not is_image):
            self.count("images_stopped_blocked")
            self.images_on = False
            head = "" if is_image else r.text[:2000]
            self.emit("images", {**rec, "state": "blocked", "head": head})
            return
        if r.status_code != 200:
            self.count(f"image_http_{r.status_code}")
            self.emit("images", {**rec, "state": "http_error"})
            return
        digest = images.sha256_hex(r.content)
        name = images.object_name(digest, ct)
        self.put(name, r.content, gz=False)
        self.count("image_ok")
        self.emit("images", {**rec, "state": "ok", "sha256": digest, "object": name})

    def trpc(self, pid: str) -> None:
        self.count("trpc_attempted")
        locale = self.locales[0]
        url = extract.trpc_availability_url(locale, pid)
        got = self.get(url, locale, "json")
        if got is None:
            return
        status, body, meta = got
        rec: dict[str, Any] = {**meta, "pid": pid}
        try:
            rec["json"] = json.loads(body)
        except json.JSONDecodeError:
            rec["text"] = body[:2000].decode("utf-8", "replace")
        self.count(f"trpc_http_{status}")
        if status == 200:
            self.covered["trpc"][pid] = {"at": meta["at"]}
        self.emit("trpc", rec)

    def load_plan(self, name: str) -> dict[str, Any]:
        """Read a gzipped plan: ``{"order": [pid], "seed": {pid: {lang: url}}, "trpc"?: [pid],
        "meta": {"phase": ...}}`` (see plan.py)."""
        if self.local is not None:
            with open(os.path.join(self.local, name), "rb") as fh:
                raw = fh.read()
        else:
            raw = self.bucket.blob(name).download_as_bytes()
        plan: dict[str, Any] = json.loads(gzip.decompress(raw))
        return plan

    def run_stock(self, plan_name: str) -> None:
        """PLAN continuation run: EN PDPs (price plan only), tRPC stock reads (unless TRPC=0),
        then the plan's AR PDPs."""
        plan = self.load_plan(plan_name)
        order: list[str] = list(plan["order"])
        ids: dict[str, dict[str, str]] = dict(plan["seed"])
        self.counts["plan_pids"] = len(order)
        self.progress()
        if (plan.get("meta") or {}).get("phase") == "price":
            for pid in order:
                if "en" in ids.get(pid, {}):
                    self.pdp(pid, "en", ids[pid]["en"])
            self.flush("pdp_en")
        if self.trpc_on:  # TRPC=0: AR-only plan run
            for pid in plan.get("trpc", order):
                self.trpc(pid)
            self.flush("trpc")
        for pid in order:
            if "ar" in ids.get(pid, {}):
                self.pdp(pid, "ar", ids[pid]["ar"])

    def read_covered(self) -> list[dict[str, Any]]:
        """Every earlier run's covered.json.gz still in the bucket (retention is 14 days).
        An unreadable file is skipped and counted (``plan_covered_unreadable``), never fatal."""
        name = "covered.json.gz"
        blobs: list[bytes] = []
        if self.local is not None:
            for entry in sorted(os.listdir(self.local)):
                path = os.path.join(self.local, entry, name)
                if entry != self.prefix and os.path.isfile(path):
                    with open(path, "rb") as fh:
                        blobs.append(fh.read())
        else:
            for blob in self.bucket.client.list_blobs(self.bucket, match_glob=f"*/{name}"):
                if blob.name != f"{self.prefix}/{name}":
                    blobs.append(blob.download_as_bytes())
        out: list[dict[str, Any]] = []
        for raw in blobs:
            try:
                payload = json.loads(gzip.decompress(raw))
            except (OSError, EOFError, ValueError):
                self.count("plan_covered_unreadable")
                continue
            if isinstance(payload, dict):
                out.append(payload)
            else:
                self.count("plan_covered_unreadable")
        return out

    def run_auto(self) -> None:
        """Unattended run: seed, plan gap-first from earlier runs, then EN page + stock per
        product until the cutoff. No AR pages (ADR-0009: AR is the weekly discovery pass)."""
        if self.refused is not None:
            print(json.dumps({"refused": self.refused}), flush=True)
            raise Stop(f"refused: {self.refused}")
        if self.outside is not None:
            print(json.dumps({"outside_window": self.outside}), flush=True)
            raise Stop("outside_window")
        ids = self.seed()
        history = self.read_covered()
        order, tiers = cadence.gap_first(
            (pid for pid, urls in ids.items() if "en" in urls), cadence.merge_covered(history)
        )
        order = order[: self.limit or None]
        self.counts |= {"plan_pids": len(order), "plan_history_runs": len(history)}
        self.counts |= {f"plan_{tier}": n for tier, n in tiers.items()}
        self.put("plan.json.gz", json.dumps({"order": order, "tiers": tiers}).encode())
        self.progress()
        for pid in order:
            self.pdp(pid, "en", ids[pid]["en"])
            if self.trpc_on:
                self.trpc(pid)

    def finish(self) -> None:
        """The terminal marker: covered.json.gz, then status.json, written once per run."""
        self.put("covered.json.gz", json.dumps(self.covered).encode())
        status = {
            "state": "finished",
            "outcome": cadence.outcome(self.stopped),
            "stopped": self.stopped,
            "prefix": self.prefix,
            "mode": self.mode,
            "started": self.started.isoformat(),
            "finished": datetime.now(UTC).isoformat(),
            "cutoff": self.cutoff.isoformat(),
            "loadable": cadence.loadable(self.counts),
            "counts": self.counts,
        }
        self.put("status.json", json.dumps(status).encode(), gz=False)

    def run(self) -> None:
        if self.auto:
            self.run_auto()
            return
        plan = os.environ.get("PLAN")
        if plan:
            self.run_stock(plan)
            return
        ids = self.seed()
        limit = self.limit or None
        order = sorted(ids)
        # spread categories so a cutoff is a fair sample; plan.py reuses this order
        random.Random(20260930).shuffle(order)  # noqa: S311 - ordering, not crypto
        order = order[:limit]
        for pid in order:
            if "en" in ids[pid]:
                self.pdp(pid, "en", ids[pid]["en"])
        self.flush("pdp_en")
        if self.trpc_on:
            for pid in order:
                self.trpc(pid)
            self.flush("trpc")
        for pid in order:
            if "ar" in ids[pid]:
                self.pdp(pid, "ar", ids[pid]["ar"])
        self.flush("pdp_ar")
        self.flush("images")


def _sigterm(signum: int, frame: object) -> None:
    raise Stop("sigterm")


def main() -> int:
    signal.signal(signal.SIGTERM, _sigterm)
    job = Job()
    print(
        json.dumps({"start": job.started.isoformat(), "cutoff": job.cutoff.isoformat()}), flush=True
    )
    code = 0
    try:
        job.run()
        job.stopped = "complete"
    except Stop as exc:
        job.stopped = str(exc)
    except Exception as exc:
        job.stopped, code = f"error: {exc!r}", 1
    finally:
        for stream in list(job.buf):
            job.flush(stream)
        job.progress()
        job.finish()
        print(json.dumps({"stopped": job.stopped, "counts": job.counts}), flush=True)
    return 1 if cadence.outcome(job.stopped) in ("refused", "error") else code


if __name__ == "__main__":
    sys.exit(main())
