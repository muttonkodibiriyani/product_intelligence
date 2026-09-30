"""The rung-5 test runner's wiring, on fakes only (no network, no proxy, no secret)."""

from __future__ import annotations

import gzip
import html
import io
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import HttpUrl
from ulta_snapshot.load import allowed_captures, page_product, robots_for
from ulta_snapshot.run import Run, context, make_run, policy, prior_bytes

from pi_fetch.pacing import HostPacer
from pi_fetch.policy import FetchPlan, FetchPolicy
from pi_fetch.proxy import DEFAULT_BYTE_CAP, ProxyCredentials, ProxyMeter
from pi_fetch.transports.base import RawResponse, Transport
from pi_fetch.types import CapturedJson, FetchRequest

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "packages/pi_connector_ulta/tests/fixtures"
SECRET = json.dumps(
    {
        "host": "gw.proxy.test",
        "port": 1,
        "username": "u-fake",
        "password": "p-fake",
        "provider": "t",
    }
).encode()
RESOURCE = "projects/p/secrets/s/versions/latest"
BASE = "https://www.ulta.ae"
URLS = [f"{BASE}/en/buy-a", f"{BASE}/en/buy-b", f"{BASE}/en/buy-c", f"{BASE}/en/buy-d"]


class Reader:
    def read(self, resource: str) -> bytes:
        assert resource == RESOURCE
        return SECRET


class FakeBrowser:
    """Scripted proxied browser: asks robots about two graphql sub-requests per page."""

    def __init__(
        self, meter: ProxyMeter, allowed: Callable[[str], bool], challenge_at: int | None
    ) -> None:
        self.meter = meter
        self.allowed = allowed
        self.challenge_at = challenge_at
        self.pages = 0
        self.requested: list[str] = []

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        url = str(request.url)
        self.requested.append(url)
        self.meter.add(500, 1500)
        if url.endswith("/robots.txt"):
            text = html.escape((FIXTURES / "ulta_ae_robots.txt").read_text())
            body = f"<html><head></head><body><pre>{text}</pre></body></html>"
            return RawResponse(
                final_url=url,
                status=200,
                headers=(("content-type", "text/plain"),),
                body=body.encode(),
                content_type="text/plain",
                elapsed_ms=1,
            )
        self.pages += 1
        if self.pages == self.challenge_at:  # a Cloudflare challenge: the run must stop here
            page = ROOT / "docs/recon/samples/probe/ulta_ae_cf_challenge_webkit_head.html"
            return RawResponse(
                final_url=url,
                status=403,
                headers=(("content-type", "text/html"), ("server", "cloudflare")),
                body=page.read_bytes(),
                content_type="text/html",
                elapsed_ms=1,
            )
        captured = []
        for sub in (f"{BASE}/graphql?query=q", f"{BASE}/graphql"):
            if self.allowed(sub) and request.capture_json:
                data = (FIXTURES / "ulta_ae_page_json_kylie_tint.json").read_bytes()
                captured.append(CapturedJson(url=HttpUrl(sub), status=200, body=data))
        self.meter.add(1000, 300_000)
        return RawResponse(
            final_url=url,
            status=200,
            headers=(("content-type", "text/html"),),
            body=(FIXTURES / "ulta_ae_pdp_en_kylie_tint.html").read_bytes(),
            content_type="text/html",
            captured_json=tuple(captured),
            elapsed_ms=1,
        )

    def close(self) -> None:
        pass


class Factory:
    """The proxied-browser factory, keeping the browsers it built for assertions."""

    def __init__(self, challenge_at: int | None = None) -> None:
        self.challenge_at = challenge_at
        self.browsers: list[FakeBrowser] = []

    def __call__(
        self,
        route: FetchPlan,
        pol: FetchPolicy,
        creds: ProxyCredentials,
        meter: ProxyMeter,
        allowed: Callable[[str], bool],
    ) -> Transport:
        self.browsers.append(FakeBrowser(meter, allowed, self.challenge_at))
        return self.browsers[-1]

    @property
    def requested(self) -> list[str]:
        return [u for b in self.browsers for u in b.requested]


def _run(out: Path, urls: list[str], prior: int, factory: Factory, console: io.StringIO) -> Run:
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    return make_run(  # capture_json stays off (the owner's test runs with CAPTURE_JSON=0)
        out,
        urls,
        policy(prior, "owner-approval-test", RESOURCE),
        Reader(),
        inner=factory,
        pacer=HostPacer(clock=lambda: now[0], sleep=sleep),
        sleep=sleep,
        console=console,
    )


def test_runner_stops_at_first_challenge_and_writes_loader_input(tmp_path: Path) -> None:
    out = tmp_path / "snap"
    console = io.StringIO()
    run = _run(out, URLS, 0, Factory(challenge_at=3), console)
    with run.fetcher:
        run.run(context(datetime.now(UTC)))
    run.finish()

    assert "ULTA TEST RESULT: status=stopped_at_challenge pages_ok=2/4" in console.getvalue()
    assert "challenge=yes" in console.getvalue()
    progress = json.loads((out / "progress.json").read_text())
    assert progress["stopped"].startswith("stopped:")
    assert progress["counts"]["en"]["pdp_ok"] == 2
    assert progress["counts"]["en"]["pdp_fetched"] == 3  # the 4th URL was never requested
    assert progress["graphql"] == {"graphql_query_refused": 2, "graphql_bare_allowed": 2}
    assert progress["proxy"]["bytes_via_proxy"] > 0
    assert progress["proxy"]["prior_bytes"] == 0
    assert "p-fake" not in (out / "progress.json").read_text()
    # The robots.txt obeyed in this run is saved for the loader.
    assert "Disallow: /*?" in (out / "robots.txt").read_text()
    with gzip.open(out / "pdp/part-0000.jsonl.gz", "rt") as fh:
        recs: list[dict[str, Any]] = [json.loads(line) for line in fh]
    assert [r["status"] for r in recs] == [200, 200, 403]
    assert recs[2]["html"] == ""  # a block is recorded, never parsed
    # The loader reads the runner's output: DOM parses; only the allowed capture is usable.
    robots = robots_for(out, enabled=True)
    assert allowed_captures(recs[0], robots) == ([], 0)  # CAPTURE_JSON off: DOM only
    product = page_product(recs[0], robots)
    assert product is not None
    assert product.variants


PAGE = 303_000  # one fake page load through the proxy (2 kB request + 301 kB page)
RESERVE = 8_000_000  # ResidentialProxy.page_reserve_bytes default


def test_byte_cap_stops_the_run_before_a_page_could_cross_it(tmp_path: Path) -> None:
    # Room for robots.txt and two pages; after the second, another page could cross the cap.
    prior = DEFAULT_BYTE_CAP - RESERVE - 2_000 - 2 * PAGE + 1
    out = tmp_path / "snap"
    console = io.StringIO()
    factory = Factory()
    run = _run(out, URLS, prior, factory, console)
    with run.fetcher:
        run.run(context(datetime.now(UTC)))
    run.finish()

    assert factory.requested == [f"{BASE}/robots.txt", URLS[0], URLS[1]]  # no 3rd page request
    progress = json.loads((out / "progress.json").read_text())
    assert progress["stopped"].startswith("stopped:")
    assert "proxy_byte_cap" in progress["stopped"]
    assert progress["counts"]["en"]["pdp_ok"] == 2
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["stopped"] == progress["stopped"]
    assert manifest["proxy_usage"][0]["prior_bytes"] == prior
    assert "status=cap_reached pages_ok=2/4" in console.getvalue()


def test_exhausted_allowance_raises_before_any_request(tmp_path: Path) -> None:
    prior = DEFAULT_BYTE_CAP - RESERVE + 1  # not even one page fits
    out = tmp_path / "snap"
    console = io.StringIO()
    factory = Factory()
    run = _run(out, URLS, prior, factory, console)
    with run.fetcher:
        run.run(context(datetime.now(UTC)))
    run.finish()

    assert factory.requested == [f"{BASE}/robots.txt"]  # no page request at all
    progress = json.loads((out / "progress.json").read_text())
    assert progress["stopped"] != "complete"
    assert progress["proxy"]["bytes_via_proxy"] == 2_000  # robots.txt only
    assert (out / "manifest.json").exists()
    assert "status=cap_reached pages_ok=0/4" in console.getvalue()


def test_robots_refused_page_is_skipped_and_the_run_continues(tmp_path: Path) -> None:
    refused = f"{BASE}/en/buy-b?colour=red"  # robots: Disallow: /*?
    urls = [URLS[0], refused, URLS[2]]
    out = tmp_path / "snap"
    console = io.StringIO()
    factory = Factory()
    run = _run(out, urls, 0, factory, console)
    with run.fetcher:
        run.run(context(datetime.now(UTC)))
    run.finish()

    assert refused not in factory.requested  # never sent through the proxy
    assert factory.requested == [f"{BASE}/robots.txt", URLS[0], URLS[2]]
    progress = json.loads((out / "progress.json").read_text())
    assert progress["stopped"] == "complete"
    assert progress["counts"]["en"]["robots_refused_page"] == 1
    assert progress["counts"]["en"]["pdp_ok"] == 2
    assert progress["proxy"]["bytes_via_proxy"] == 2_000 + 2 * PAGE  # zero bytes for the refusal
    assert f"refused by robots (not fetched, 0 bytes): {refused}" in console.getvalue()
    assert "status=complete pages_ok=2/3 robots_refused=1" in console.getvalue()


def test_prior_bytes_rounds_the_dashboard_figure_up() -> None:
    assert prior_bytes({"PRIOR_GB": "0.00002"}) == 20_000
    assert prior_bytes({"PRIOR_GB": "0.0000132101"}) == 13_211
    assert prior_bytes({"PRIOR_BYTES": "5", "PRIOR_GB": "9"}) == 5
