"""Transports against a local server only (no live sites)."""

import json
from pathlib import Path

import pytest
from pydantic import HttpUrl

from fetch_helpers import local_server
from pi_core import FetchMethod, LadderRung, Locale
from pi_fetch.ladder import _robots_text
from pi_fetch.policy import EgressProfile, Engine, FetchPlan
from pi_fetch.transports.base import TransportError
from pi_fetch.transports.browser import BrowserTransport, is_json_response
from pi_fetch.transports.http import HttpTransport
from pi_fetch.types import BrowserEngine, BrowserProfile, FetchRequest, PayloadKind

PAGE = b"""<html><body><div id="out">loading</div><script>
fetch('/api/product').then(r => r.json()).then(d => {
  document.getElementById('out').textContent = d.name;
});
fetch('/api/text');
</script></body></html>"""


def req(
    url: str,
    kind: PayloadKind = PayloadKind.HTML,
    *,
    render: bool = False,
    capture_json: bool = False,
) -> FetchRequest:
    return FetchRequest(
        url=HttpUrl(url), kind=kind, locale=Locale.EN, render=render, capture_json=capture_json
    )


def test_http_transport_follows_redirects_and_keeps_raw_headers() -> None:
    with local_server() as srv:
        srv.routes["/old"] = lambda _h: (301, [("Location", "/new")], b"")
        srv.static("/new", b"{}", "application/json", ("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"))
        transport = HttpTransport(timeout_s=5)
        try:
            response = transport.send(req(f"{srv.base}/old", PayloadKind.JSON), {"X-T": "1"})
        finally:
            transport.close()
    assert response.status == 200
    assert response.final_url.endswith("/new")
    assert [v for k, v in response.headers if k == "set-cookie"] == ["a=1", "b=2"]
    assert response.content_type == "application/json"
    assert srv.requests[0][1]["X-T"] == "1"


def test_http_transport_carries_no_cookie_between_requests() -> None:
    # A WAF cookie (cf_clearance, _abck) set by one response must never ride on the next request.
    with local_server() as srv:
        srv.static("/set", b"ok", "text/plain", ("Set-Cookie", "cf_clearance=abc; Path=/"))
        srv.static("/next", b"ok", "text/plain")
        transport = HttpTransport(timeout_s=5)
        try:
            transport.send(req(f"{srv.base}/set"), {})
            transport.send(req(f"{srv.base}/next"), {})
        finally:
            transport.close()
    assert "Cookie" not in srv.requests[1][1]


def test_http_transport_error_is_not_a_block() -> None:
    transport = HttpTransport(timeout_s=2)
    with pytest.raises(TransportError, match="failed"):
        transport.send(req("http://127.0.0.1:9/"), {})
    transport.close()


@pytest.mark.parametrize(
    ("content_type", "resource_type", "expected"),
    [
        ("application/json; charset=utf-8", "xhr", True),
        ("application/ld+json", "fetch", True),
        ("application/json", "document", False),
        ("text/plain", "fetch", False),
        (None, "xhr", False),
    ],
)
def test_is_json_response(content_type: str | None, resource_type: str, expected: bool) -> None:
    assert is_json_response(content_type, resource_type) is expected


@pytest.fixture(scope="module", params=list(BrowserEngine), ids=lambda e: e.value)
def profile(request: pytest.FixtureRequest) -> BrowserProfile:
    """Each stock engine a source can be pinned to; skipped where it can't launch."""
    from playwright.sync_api import Error, sync_playwright  # noqa: PLC0415

    engine: BrowserEngine = request.param
    try:
        with sync_playwright() as p:
            getattr(p, engine.value).launch().close()
    except Error as exc:
        pytest.skip(f"Playwright {engine.value} cannot launch: {exc.message.splitlines()[0]}")
    return BrowserProfile(engine=engine)


@pytest.mark.browser
def test_browser_renders_and_captures_page_json(profile: BrowserProfile) -> None:
    with local_server() as srv:
        srv.static("/p", PAGE, "text/html")
        srv.static("/api/product", json.dumps({"name": "Rouge"}).encode(), "application/json")
        srv.static("/api/text", b"plain", "text/plain")
        transport = BrowserTransport(profile=profile, timeout_s=15)
        try:
            response = transport.send(
                req(f"{srv.base}/p", render=True, capture_json=True),
                {"Accept-Language": "en-AE,en;q=0.9", "User-Agent": "ignored"},
            )
            second = transport.send(req(f"{srv.base}/api/product", PayloadKind.JSON), {})
        finally:
            transport.close()
    assert response.status == 200
    assert b'<div id="out">Rouge</div>' in response.body
    assert [c.url.path for c in response.captured_json] == ["/api/product"]
    assert json.loads(response.captured_json[0].body) == {"name": "Rouge"}
    assert json.loads(second.body) == {"name": "Rouge"}
    page_request = next(h for p, h, _ in srv.requests if p == "/p")
    assert page_request["Accept-Language"].startswith("en-AE")
    # Stock browser identity: the fetch layer's User-Agent is not injected (no spoofing).
    assert page_request["User-Agent"] != "ignored"


@pytest.mark.browser
def test_browser_failure_raises_transport_error(profile: BrowserProfile) -> None:
    transport = BrowserTransport(profile=profile, timeout_s=5)
    try:
        with pytest.raises(TransportError):
            transport.send(req("http://127.0.0.1:9/"), {})
    finally:
        transport.close()


ULTA_ROBOTS = (Path(__file__).parent / "fixtures" / "robots" / "ulta_ae.txt").read_text()


@pytest.mark.browser
def test_real_browser_robots_viewer_extracts_the_file_exactly(profile: BrowserProfile) -> None:
    # The recon ulta.ae robots.txt plus the characters a viewer must escape, behind a BOM.
    text = ULTA_ROBOTS.rstrip("\n") + "\n# a <b> & c > d\nDisallow: /x?a=1&b=<2>\n"
    with local_server() as srv:
        srv.static("/robots.txt", "﻿".encode() + text.encode(), "text/plain; charset=utf-8")
        transport = BrowserTransport(profile=profile, timeout_s=15)
        try:
            raw = transport.send(req(f"{srv.base}/robots.txt"), {})
        finally:
            transport.close()
    route = FetchPlan(
        rung=LadderRung.BROWSER,
        method=FetchMethod.PLAYWRIGHT,
        engine=Engine.BROWSER,
        egress=EgressProfile(name="direct"),
        browser=profile,
    )
    assert _robots_text(route, raw) == text
