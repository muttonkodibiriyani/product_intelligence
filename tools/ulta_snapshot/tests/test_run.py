"""The rung-5 test runner's wiring, on fakes only (no network, no proxy, no secret)."""

from __future__ import annotations

import gzip
import html
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import HttpUrl
from ulta_snapshot.load import allowed_captures, page_product, robots_for
from ulta_snapshot.run import context, make_run, policy

from pi_fetch.pacing import HostPacer
from pi_fetch.policy import FetchPlan, FetchPolicy
from pi_fetch.proxy import ProxyCredentials, ProxyMeter
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

    def __init__(self, meter: ProxyMeter, allowed: Callable[[str], bool]) -> None:
        self.meter = meter
        self.allowed = allowed
        self.pages = 0

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        url = str(request.url)
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
        if self.pages == 3:  # a Cloudflare challenge: the run must stop here
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


def _factory(
    route: FetchPlan,
    pol: FetchPolicy,
    creds: ProxyCredentials,
    meter: ProxyMeter,
    allowed: Callable[[str], bool],
) -> Transport:
    return FakeBrowser(meter, allowed)


def test_runner_stops_at_first_challenge_and_writes_loader_input(tmp_path: Path) -> None:
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    out = tmp_path / "snap"
    run = make_run(  # capture_json stays off (rung 5 refuses captured_json on main)
        out,
        URLS,
        policy(0, "owner-approval-test", RESOURCE),
        Reader(),
        inner=_factory,
        pacer=HostPacer(clock=lambda: now[0], sleep=sleep),
        sleep=sleep,
    )
    with run.fetcher:
        run.run(context(datetime.now(UTC)))

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
