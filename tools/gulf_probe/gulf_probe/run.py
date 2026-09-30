"""Probe entry point (Cloud Run job or local Docker). Network I/O lives here; logic is in
``analysis`` and ``plan``.

Ordinary access only (ADR-0005/0006): plain httpx with normal headers, and stock Playwright
Chromium/Firefox/WebKit (headless, or headed on Xvfb; desktop or a built-in mobile device).
Every browser attempt gets a fresh context; cookies are never carried between attempts or between
httpx and a browser; nothing is retried; challenge pages are recorded, never interacted with.

Env: PROBE_BUCKET (required), PROBE_EGRESS (label), PROBE_STAGE ("1" = built-in discovery plan,
anything else = PROBE_SPEC JSON, see :func:`plan.parse_spec`), PROBE_PREFIX (optional),
PROBE_PACE (seconds between requests, default 1.0).
"""

import contextlib
import gzip
import html
import json
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from google.cloud import storage  # type: ignore[attr-defined]
from playwright.sync_api import Browser, Playwright, Response, sync_playwright

from gulf_probe import analysis, plan

BLOCK_LIMIT = 3  # consecutive blocks per (site, client) before that client stops for the site
Rec = dict[str, Any]


class Probe:
    """Sequential, paced fetcher that records one JSON line per attempt."""

    def __init__(self, bucket: str, prefix: str, egress: str) -> None:
        # "file:/dir" writes locally (our-server egress run); otherwise a GCS bucket name.
        self.local = bucket.removeprefix("file:") if bucket.startswith("file:") else None
        self.bucket = None if self.local else storage.Client().bucket(bucket)
        self.prefix = prefix
        self.egress = egress
        self.records: list[Rec] = []
        self.blocks: dict[tuple[str, str], int] = {}
        self.last = 0.0
        self.http_client = httpx.Client(follow_redirects=True, timeout=30.0)
        self.pw: Playwright | None = None
        self.browsers: dict[tuple[str, bool], Browser | None] = {}
        # Hosts whose robots.txt we obey, keyed by netloc. Sephora is exempt (its disallowed
        # paths are owner-approved: ADR-0005); every other site's robots.txt is obeyed.
        self.robots: dict[str, list[tuple[bool, str]]] = {}
        self.robots_status: dict[str, int | None] = {}

    # ------------------------------------------------------------------ plumbing
    def pace(self) -> None:
        base = float(os.environ.get("PROBE_PACE", "1.0"))
        wait = base + random.uniform(0.0, 0.6 * base) - (time.monotonic() - self.last)  # noqa: S311
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()

    def put(self, name: str, data: bytes) -> str:
        if self.local is not None:
            path = os.path.join(self.local, self.prefix, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(gzip.compress(data))
            return path
        assert self.bucket is not None  # noqa: S101
        blob = self.bucket.blob(f"{self.prefix}/{name}")
        blob.upload_from_string(gzip.compress(data), content_type="application/gzip")
        return f"gs://{self.bucket.name}/{self.prefix}/{name}"

    def base(self, t: plan.Target, c: plan.Client) -> Rec:
        return {**asdict(t), "egress": self.egress, "client": c.label}

    def record(self, rec: Rec, body: bytes, ext: str) -> Rec:
        rec["seq"] = len(self.records) + 1
        rec["at"] = datetime.now(UTC).isoformat()
        if body:
            rec["raw"] = self.put(f"raw/{rec['seq']:04d}.{ext}.gz", body)
        key = (rec["site"], rec["client"])
        self.blocks[key] = self.blocks.get(key, 0) + 1 if rec.get("block") else 0
        self.records.append(rec)
        keys = ("seq", "client", "url", "status", "block", "usable")
        print(json.dumps({k: rec.get(k) for k in keys}, default=str), flush=True)
        return rec

    def fetch(self, t: plan.Target, c: plan.Client) -> Rec | None:
        split = urlsplit(t.url)
        path = split.path + (f"?{split.query}" if split.query else "")
        skip = analysis.robots_gate(
            t.site, path, self.robots.get(split.netloc), self.robots_status.get(split.netloc)
        )
        if skip is not None:
            self.records.append({**self.base(t, c), "skipped": skip})
            return None
        if self.blocks.get((t.site, c.label), 0) >= BLOCK_LIMIT:
            self.records.append({**self.base(t, c), "skipped": "after_blocks"})
            return None
        self.pace()
        rec = self.http(t) if c.engine == "http" else self.browser(t, c)
        # Keep the best robots outcome seen for the host (a 200 from any client wins).
        if (
            t.site != "sephora"
            and split.path == "/robots.txt"
            and self.robots_status.get(split.netloc) != 200
        ):
            self.robots_status[split.netloc] = rec.get("status")
        if (
            t.site != "sephora"
            and split.path == "/robots.txt"
            and rec.get("status") == 200
            and not rec.get("block")  # a 200 challenge page is not a robots.txt
        ):
            text = rec.get("_text", "")
            pre = re.search(r"<pre[^>]*>(.*)</pre>", text, re.DOTALL)  # browsers wrap text in <pre>
            robots = html.unescape(pre.group(1)) if pre else text
            self.robots[split.netloc] = analysis.robots_rules(robots)
            rec["robots_rules"] = len(self.robots[split.netloc])
        return rec

    # ------------------------------------------------------------------ rung 1: plain HTTP
    def http(self, t: plan.Target) -> Rec:
        rec = self.base(t, plan.HTTP)
        self.http_client.cookies.clear()
        started = time.monotonic()
        try:
            r = self.http_client.get(t.url, headers=plan.browser_headers(t.locale, t.kind))
        except httpx.HTTPError as exc:
            return self.record({**rec, "error": repr(exc)}, b"", "bin")
        text = r.text if t.kind != "image" else ""
        size = len(r.content) if t.kind == "image" else None
        verdict = analysis.detect_block(r.status_code, r.headers, text, size=size)
        rec |= {
            "status": r.status_code,
            "final_url": str(r.url),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "bytes": len(r.content),
            "content_type": r.headers.get("content-type", ""),
            "headers": analysis.redact_headers(r.headers),
            "block": asdict(verdict) if verdict else None,
            "vendor": analysis.detect_vendor(r.headers, text),
        }
        if not verdict and t.kind == "html":
            rec["fields"] = analysis.product_fields(text)
        elif not verdict and t.kind == "xml":
            rec["sitemap"] = analysis.sitemap_stats(text)
        elif not verdict and t.kind == "json":
            try:
                rec["fields"] = analysis.json_fields(r.json())
            except ValueError:
                rec["fields"] = None
        rec["usable"] = plan.usable(rec.get("fields"), [])
        rec["_text"] = text
        return self.record(rec, r.content, t.kind)

    # ------------------------------------------------------------------ rung 2: real browser
    def launch(self, c: plan.Client) -> Browser | None:
        key = (c.engine, c.headless)
        if key not in self.browsers:
            if self.pw is None:
                self.pw = sync_playwright().start()
            try:
                engine = getattr(self.pw, c.engine)
                self.browsers[key] = engine.launch(headless=c.headless, timeout=60_000)
            except Exception as exc:
                print(json.dumps({"launch_failed": c.label, "error": repr(exc)}), flush=True)
                self.browsers[key] = None
        return self.browsers[key]

    def preflight(self, clients: list[plan.Client]) -> None:
        """Offline engine check (inline HTML) so infra failures are never read as blocks."""
        for c in {x for x in clients if x.engine != "http"}:
            b = self.launch(c)
            ok = False
            if b is not None:
                with contextlib.suppress(Exception):
                    ctx = b.new_context()
                    page = ctx.new_page()
                    page.set_content("<title>ok</title>", timeout=20_000)
                    ok = page.title() == "ok"
                    ctx.close()
            self.records.append({"preflight": c.label, "egress": self.egress, "ok": ok})
            print(json.dumps({"preflight": c.label, "ok": ok}), flush=True)

    def browser(self, t: plan.Target, c: plan.Client) -> Rec:
        rec = self.base(t, c)
        b = self.launch(c)
        if b is None or self.pw is None:
            return self.record({**rec, "error": "browser launch failed (infra)"}, b"", "bin")
        opts: dict[str, Any] = {"locale": t.locale}
        if c.device == "mobile":
            opts |= self.pw.devices[plan.MOBILE_DEVICE[c.engine]]
        ctx = b.new_context(**opts)  # fresh context per attempt: no cookies carried over
        captured: list[Rec] = []

        def on_response(resp: Response) -> None:
            ctype = resp.headers.get("content-type", "")
            if resp.request.resource_type in ("xhr", "fetch") and plan.is_json_api(resp.url, ctype):
                body = ""
                with contextlib.suppress(Exception):
                    body = resp.text()
                captured.append({"url": resp.url, "status": resp.status, "body": body})

        page = ctx.new_page()
        page.on("response", on_response)
        started = time.monotonic()
        try:
            resp = page.goto(t.url, wait_until="load", timeout=45_000)
            with contextlib.suppress(Exception):  # networkidle is best-effort
                page.wait_for_load_state("networkidle", timeout=10_000)
            page_html = page.content()
        except Exception as exc:
            ctx.close()
            return self.record({**rec, "error": repr(exc)}, b"", "bin")
        status = resp.status if resp else 0
        headers = resp.headers if resp else {}
        final_url = page.url
        ctx.close()
        verdict = analysis.detect_block(status, headers, page_html)
        seq = len(self.records) + 1
        xhr: list[Rec] = []
        for i, cap in enumerate(captured):
            fields = None
            with contextlib.suppress(ValueError):
                fields = analysis.json_fields(json.loads(cap["body"]))
            body = analysis.redact_text(cap["body"]).encode()
            uri = self.put(f"xhr/{seq:04d}-{i:02d}.json", body) if body else None
            url = analysis.redact_text(cap["url"])
            xhr.append({"url": url, "status": cap["status"], "fields": fields, "raw": uri})
        fields = analysis.product_fields(page_html) if not verdict else None
        rec |= {
            "status": status,
            "final_url": final_url,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "bytes": len(page_html),
            "headers": analysis.redact_headers(headers),
            "block": asdict(verdict) if verdict else None,
            "vendor": analysis.detect_vendor(headers, page_html),
            "fields": fields,
            "xhr": xhr,
            "usable": plan.usable(fields, [x["fields"] for x in xhr]),
            "_text": page_html,
        }
        return self.record(rec, page_html.encode(), "html")

    def close(self) -> None:
        self.http_client.close()
        for b in self.browsers.values():
            if b is not None:
                with contextlib.suppress(Exception):
                    b.close()
        if self.pw is not None:
            self.pw.stop()


def start_display() -> subprocess.Popen[bytes] | None:
    """Virtual display for headed (still ordinary) browsers; ``None`` if Xvfb is absent."""
    cmd = ["Xvfb", ":99", "-screen", "0", "1366x900x24", "-nolisten", "tcp"]
    try:
        xvfb = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)  # noqa: S603
    except FileNotFoundError:
        return None
    os.environ["DISPLAY"] = ":99"
    time.sleep(2)
    return xvfb


def first_image(rec: Rec | None) -> str | None:
    """First JSON-LD image URL on a fetched page."""
    if not rec or rec.get("block"):
        return None
    for block in analysis.json_ld_blocks(rec.get("_text", "")):
        img = block.get("image") if isinstance(block, dict) else None
        if isinstance(img, list) and img and isinstance(img[0], str):
            return img[0]
        if isinstance(img, str):
            return img
    return None


def stage1(probe: Probe) -> None:
    """Discovery: plain HTTP across all entry points + Chromium headless on the page types."""
    http, chrome = plan.HTTP, plan.CHROMIUM_HEADLESS
    probe.preflight([chrome])
    probe.fetch(
        plan.Target("meta", "egress_ip", "https://api.ipify.org?format=json", "json", "en-AE"), http
    )
    seph = {f"{t.step}:{t.locale}": probe.fetch(t, http) for t in plan.sephora_fixed()}
    probe.fetch(
        plan.Target("sephora", "alt_domain", "https://www.sephora.ae/", "html", "en-AE"), http
    )
    locs: dict[str, list[str]] = {"en-AE": [], "ar-AE": []}
    for t in plan.sephora_product_sitemaps():
        rec = probe.fetch(t, http)
        if rec and not rec.get("block") and rec.get("status") == 200:
            locs[t.locale] += analysis.sitemap_locs(rec.get("_text", ""))
    cat = seph.get("sitemap_category:en-AE")
    cat_locs = analysis.sitemap_locs(cat.get("_text", "")) if cat and not cat.get("block") else []
    pdps = [plan.Target("sephora", "pdp", u, "html", "en-AE") for u in plan.pick(locs["en-AE"], 3)]
    pdps += [plan.Target("sephora", "pdp", u, "html", "ar-AE") for u in plan.pick(locs["ar-AE"], 1)]
    cats = [plan.Target("sephora", "category", u, "html", "en-AE") for u in plan.pick(cat_locs, 1)]
    search = plan.search_targets()
    pdp_recs = [probe.fetch(t, http) for t in [*pdps, *cats, search[0]]]
    image = next((u for u in map(first_image, pdp_recs) if u), None)
    if image:
        probe.fetch(plan.Target("sephora", "image", image, "image", "en-AE"), http)

    ulta = {f"{t.step}:{t.locale}": probe.fetch(t, http) for t in plan.ulta_fixed()}
    idx = ulta.get("sitemap_index:en-AE")
    children = analysis.sitemap_locs(idx.get("_text", "")) if idx and not idx.get("block") else []
    ulta_locs: list[str] = []
    for child in plan.pick(children, 2):
        rec = probe.fetch(plan.Target("ulta", "sitemap_child", child, "xml", "en-AE"), http)
        if rec and not rec.get("block"):
            ulta_locs += analysis.sitemap_locs(rec.get("_text", ""))
    ulta_pages = [
        plan.Target("ulta", "page", u, "html", "en-AE")
        for u in plan.pick(ulta_locs, 3, contains="/en/")
    ]
    ulta_pages = ulta_pages or [
        plan.Target("ulta", "listing", f"{plan.ULTA}/en/makeup", "html", "en-AE")
    ]
    for t in [*ulta_pages, search[1]]:
        probe.fetch(t, http)

    seph_home = plan.sephora_fixed()[3]
    for t in [seph_home, *pdps[:1], *cats, search[0]]:
        probe.fetch(t, chrome)
    ulta_home = plan.ulta_fixed()[2]
    for t in [ulta_home, *ulta_pages[:1], search[1]]:
        probe.fetch(t, chrome)
    api = [x["url"] for r in probe.records for x in r.get("xhr", []) if "/api/v1" in x["url"]]
    for u in list(dict.fromkeys(api))[:1]:
        probe.fetch(plan.Target("sephora", "bff_plain", u, "json", "en-AE"), http)


def main() -> int:
    egress = os.environ.get("PROBE_EGRESS", "unknown")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stage = os.environ.get("PROBE_STAGE", "1")
    prefix = os.environ.get("PROBE_PREFIX", f"stage{stage}-{egress}-{stamp}")
    probe = Probe(os.environ["PROBE_BUCKET"], prefix, egress)
    xvfb = start_display()
    try:
        if stage == "1":
            stage1(probe)
        else:
            rows = plan.parse_spec(os.environ["PROBE_SPEC"])
            probe.preflight([c for _, c in rows])
            for t, c in rows:
                probe.fetch(t, c)
    finally:
        probe.close()
        if xvfb:
            xvfb.terminate()
        clean = [{k: v for k, v in r.items() if k != "_text"} for r in probe.records]
        probe.put("records.jsonl", "\n".join(json.dumps(r, default=str) for r in clean).encode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
