"""The rung-5 test runner's wiring, on fakes only (no network, no proxy, no secret)."""

from __future__ import annotations

import gzip
import html
import io
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import HttpUrl
from ulta_snapshot.load import allowed_captures, page_product, robots_for
from ulta_snapshot.run import (
    Run,
    archive_previous,
    audit_log,
    context,
    floored_prior,
    main,
    make_run,
    owner_item,
    policy,
    prior_bytes,
    run_options,
)

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
RESOURCE = "projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/1"
BASE = "https://www.ulta.ae"
URLS = [f"{BASE}/en/buy-a", f"{BASE}/en/buy-b", f"{BASE}/en/buy-c", f"{BASE}/en/buy-d"]
#: The sitemap index as pinned WebKit renders it (children: category, content, product).
INDEX = (FIXTURES / "ulta_ae_sitemap_index_webkit_view.html").read_text()
PRODUCT_SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE}/en/buy-c</loc></url>
  <url><loc>{BASE}/en/buy-a</loc></url>
  <url><loc>{BASE}/en/buy-a/</loc></url>
  <url><loc>{BASE}/ar/buy-a</loc></url>
  <url><loc>{BASE}/en/buy-b</loc></url>
  <url><loc>{BASE}/en/buy-b?colour=red</loc></url>
  <url><loc>{BASE}/en/makeup</loc></url>
  <url><loc>https://outside.example/en/buy-x</loc></url>
</urlset>"""
SITEMAPS = [f"{BASE}/robots.txt", f"{BASE}/sitemap.xml", f"{BASE}/product-sitemap-ae.xml"]


class Reader:
    def read(self, resource: str) -> bytes:
        assert resource == RESOURCE
        return SECRET


class FakeBrowser:
    """Scripted proxied browser: asks robots about two graphql sub-requests per page."""

    def __init__(
        self,
        meter: ProxyMeter,
        allowed: Callable[[str], bool],
        challenge_at: int | None,
        robots_extra: str = "",
    ) -> None:
        self.robots_extra = robots_extra
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
            robots = (FIXTURES / "ulta_ae_robots.txt").read_text()
            robots = robots.replace("Disallow: /*?\n", f"Disallow: /*?\n{self.robots_extra}")
            text = html.escape(robots)
            body = f"<html><head></head><body><pre>{text}</pre></body></html>"
            return RawResponse(
                final_url=url,
                status=200,
                headers=(("content-type", "text/plain"),),
                body=body.encode(),
                content_type="text/plain",
                elapsed_ms=1,
            )
        if url.endswith(".xml"):
            doc = INDEX if url.endswith("/sitemap.xml") else PRODUCT_SITEMAP
            self.meter.add(500, len(doc))
            return RawResponse(
                final_url=url,
                status=200,
                headers=(("content-type", "text/html"),),
                body=doc.encode(),
                content_type="text/html",
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

    def __init__(self, challenge_at: int | None = None, robots_extra: str = "") -> None:
        self.challenge_at = challenge_at
        self.robots_extra = robots_extra
        self.browsers: list[FakeBrowser] = []

    def __call__(
        self,
        route: FetchPlan,
        pol: FetchPolicy,
        creds: ProxyCredentials,
        meter: ProxyMeter,
        allowed: Callable[[str], bool],
    ) -> Transport:
        self.browsers.append(FakeBrowser(meter, allowed, self.challenge_at, self.robots_extra))
        return self.browsers[-1]

    @property
    def requested(self) -> list[str]:
        return [u for b in self.browsers for u in b.requested]


def _run(
    out: Path,
    urls: list[str],
    prior: int,
    factory: Factory,
    console: io.StringIO,
    **options: Any,
) -> Run:
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
        **options,
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
    (part,) = (out / "pdp").glob("part-000000-*.jsonl.gz")
    with gzip.open(part, "rt") as fh:
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
    assert "challenge=no" in console.getvalue()
    run.counts["block_rate_limited"] += 1  # an earlier non-stopping 429 is not a challenge
    assert "status=cap_reached" in run.summary()


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


def test_sitemap_mode_enumerates_estimates_then_crawls_up_to_max_pages(tmp_path: Path) -> None:
    out = tmp_path / "snap"
    console = io.StringIO()
    factory = Factory()
    run = _run(
        out, [], 0, factory, console, url_source="sitemap", max_pages=2, est_bytes_per_page=300_000
    )
    with run.fetcher:
        run.run(context(datetime.now(UTC)))
    run.finish()

    # Robots-allowed, EN, product pages only; de-duplicated and sorted.
    assert (out / "urls_full_en.txt").read_text().splitlines() == URLS[:3]
    assert factory.requested == [*SITEMAPS, URLS[0], URLS[1]]  # MAX_PAGES bounds the crawl
    text = console.getvalue()
    assert "SITEMAP: 3 urls, est 0.0-0.0 h, est 0.000900 GB" in text
    assert text.index("SITEMAP:") < text.index("page 1:")  # the estimate comes before crawling
    progress = json.loads((out / "progress.json").read_text())
    # A bounded batch is never "complete": the loader must not take it as a full baseline.
    assert progress["stopped"] == "batch_complete"
    assert progress["next_index"] == 2
    assert progress["urls_total"] == 3
    assert progress["snapshot_id"].startswith("ulta-ae-")
    assert "status=batch_complete pages_ok=2/2" in text


def test_max_pages_zero_enumerates_only(tmp_path: Path) -> None:
    out = tmp_path / "snap"
    console = io.StringIO()
    factory = Factory()
    run = _run(out, [], 0, factory, console, url_source="sitemap", max_pages=0)
    with run.fetcher:
        run.run(context(datetime.now(UTC)))
    run.finish()

    assert factory.requested == SITEMAPS  # no product page
    assert len((out / "urls_full_en.txt").read_text().splitlines()) == 3
    assert "SITEMAP: 3 urls, est 0.0-0.0 h, est ? GB (set EST_BYTES_PER_PAGE)" in console.getvalue()
    assert "status=enumerated pages_ok=0/0" in console.getvalue()
    assert not list((out / "pdp").glob("part-*"))


def test_sitemap_disallowed_by_robots_is_never_fetched(tmp_path: Path) -> None:
    out = tmp_path / "snap"
    console = io.StringIO()
    factory = Factory(robots_extra="Disallow: /product-sitemap-ae.xml\n")
    run = _run(out, [], 0, factory, console, url_source="sitemap", max_pages=0)
    with run.fetcher:
        run.run(context(datetime.now(UTC)))
    run.finish()

    assert factory.requested == SITEMAPS[:2]  # the disallowed product sitemap is not requested
    stopped = json.loads((out / "manifest.json").read_text())["stopped"]
    assert "no robots-allowed product sitemap" in stopped
    assert not (out / "urls_full_en.txt").exists()
    assert "status=stopped_error" in console.getvalue()


def test_resume_from_next_index_reuses_the_list_without_refetching(tmp_path: Path) -> None:
    out = tmp_path / "snap"
    first = _run(out, [], 0, Factory(), io.StringIO(), url_source="sitemap", max_pages=2)
    with first.fetcher:
        first.run(context(datetime.now(UTC)))
    first.finish()
    audit_log.removeHandler(first.audit)

    # main(): options first (START_INDEX=auto reads next_index); old files are copied aside.
    options = run_options({"URL_SOURCE": "sitemap", "MAX_PAGES": "all", "START_INDEX": "auto"}, out)
    assert options["start"] == 2
    archive_previous(out)
    console = io.StringIO()
    factory = Factory()
    second = _run(out, [], 0, factory, console, **options)
    with second.fetcher:
        second.run(context(datetime.now(UTC)))
    second.finish()

    assert factory.requested == [f"{BASE}/robots.txt", URLS[2]]  # no sitemap, no earlier page
    assert "reusing urls_full_en.txt (3 urls)" in console.getvalue()
    assert len(list((out / "pdp").glob("part-000000-*.jsonl.gz"))) == 1
    assert len(list((out / "pdp").glob("part-000002-*.jsonl.gz"))) == 1
    progress = json.loads((out / "progress.json").read_text())
    assert progress["next_index"] == 3
    assert progress["stopped"] == "batch_complete"  # resumed: not one run over the whole list
    (before,) = out.glob("progress-before-*.json")
    assert json.loads(before.read_text())["snapshot_id"] == progress["snapshot_id"]
    assert list(out.glob("manifest-before-*.json"))


def test_run_options_parse_and_auto_resume(tmp_path: Path) -> None:
    assert run_options({}, tmp_path) == {
        "url_source": "file",
        "start": 0,
        "max_pages": 20,
        "est_bytes_per_page": None,
    }
    (tmp_path / "progress.json").write_text(json.dumps({"next_index": 7}))
    env = {"URL_SOURCE": "sitemap", "MAX_PAGES": "all", "START_INDEX": "auto"}
    got = run_options({**env, "EST_BYTES_PER_PAGE": "5"}, tmp_path)
    assert got == {"url_source": "sitemap", "start": 7, "max_pages": None, "est_bytes_per_page": 5}
    with pytest.raises(SystemExit):
        run_options({"URL_SOURCE": "api"}, tmp_path)
    with pytest.raises(SystemExit):
        run_options({"START_INDEX": "-1"}, tmp_path)


def test_only_one_run_over_the_whole_list_from_zero_is_complete(tmp_path: Path) -> None:
    whole = _run(tmp_path / "a", [], 0, Factory(), io.StringIO(), url_source="sitemap")
    with whole.fetcher:
        whole.run(context(datetime.now(UTC)))
    assert whole.stopped == "complete"
    audit_log.removeHandler(whole.audit)

    tail = _run(tmp_path / "b", [], 0, Factory(), io.StringIO(), url_source="sitemap", start=1)
    with tail.fetcher:
        tail.run(context(datetime.now(UTC)))
    assert tail.stopped == "batch_complete"
    assert tail.next_index == 3


def test_a_repeated_start_index_writes_a_new_part(tmp_path: Path) -> None:
    out = tmp_path / "snap"
    for _ in range(2):
        run = _run(out, [], 0, Factory(), io.StringIO(), url_source="sitemap", max_pages=1)
        with run.fetcher:
            run.run(context(datetime.now(UTC)))
        run.finish()
        audit_log.removeHandler(run.audit)
    assert len(list((out / "pdp").glob("part-000000-*.jsonl.gz"))) == 2


def test_failed_setup_keeps_the_resume_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "progress.json").write_text(json.dumps({"next_index": 7}))
    for key in ("PRIOR_GB", "PRIOR_BYTES"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OUT_DIR", str(tmp_path))
    monkeypatch.setenv("URL_SOURCE", "sitemap")
    monkeypatch.setenv("START_INDEX", "auto")
    with pytest.raises(SystemExit, match="PRIOR_GB"):
        main()
    # Nothing was moved: the next START_INDEX=auto still resumes at 7.
    assert json.loads((tmp_path / "progress.json").read_text())["next_index"] == 7
    assert run_options({"START_INDEX": "auto"}, tmp_path)["start"] == 7
    archive_previous(tmp_path)
    assert (tmp_path / "progress.json").exists()  # archiving copies, never moves


def test_prior_is_floored_at_what_this_folder_already_used(tmp_path: Path) -> None:
    assert floored_prior({"PRIOR_GB": "0.001"}, tmp_path)[0] == 1_000_000
    (tmp_path / "progress.json").write_text(json.dumps({"proxy": {"allowance_used": 3_000_000}}))
    (tmp_path / "progress-before-x.json").write_text(
        json.dumps({"proxy": {"allowance_used": 5_000_000}})
    )
    prior, note = floored_prior({"PRIOR_GB": "0.001"}, tmp_path)
    assert prior == 5_000_000
    assert "below this folder's record" in note
    assert floored_prior({"PRIOR_GB": "0.01"}, tmp_path)[0] == 10_000_000


@pytest.mark.parametrize(
    "ref", ["", "  ", "PASTE_OWNER_ITEM_HERE", "ADR-0006 Am.2", "ADR-0006 Amendment 2", "adr-0006"]
)
def test_a_rerun_needs_a_new_owner_item_not_an_adr(ref: str) -> None:
    with pytest.raises(SystemExit, match="new owner item"):
        owner_item({"OWNER_APPROVAL_REF": ref})
    with pytest.raises(SystemExit, match="new owner item"):
        owner_item({})


@pytest.mark.parametrize("ref", ["ADR-0006 Am.2", "PASTE_OWNER_ITEM_HERE", ""])
def test_main_refuses_without_a_new_owner_item_before_any_fetch_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fetch setup reached without a new owner item")

    for name in ("SecretManagerReader", "operator_token", "make_run"):
        monkeypatch.setattr(f"ulta_snapshot.run.{name}", never)
    urls = tmp_path / "urls.txt"
    urls.write_text("https://www.ulta.ae/en/p/x\n")
    for key in ("URL_SOURCE", "START_INDEX", "PRIOR_GB"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("URLS_FILE", str(urls))
    monkeypatch.setenv("PRIOR_BYTES", "0")
    monkeypatch.setenv("SECRET_RESOURCE", "projects/x/secrets/y/versions/1")
    monkeypatch.setenv("OWNER_APPROVAL_REF", ref)
    with pytest.raises(SystemExit, match="new owner item"):
        main()


def test_owner_item_id_is_passed_through() -> None:
    assert owner_item({"OWNER_APPROVAL_REF": " owner-item-2026-10-09 "}) == "owner-item-2026-10-09"


def test_runbook_does_not_prefill_an_approval() -> None:
    text = (Path(__file__).parents[3] / "docs/runbooks/ulta-proxy-test.md").read_text()
    assert 'OWNER_APPROVAL_REF="$OWNER_ITEM"' in text
    assert "OWNER_ITEM=PASTE_OWNER_ITEM_HERE" in text
    assert not re.search(r'OWNER_APPROVAL_REF="(?!\$OWNER_ITEM")', text)
