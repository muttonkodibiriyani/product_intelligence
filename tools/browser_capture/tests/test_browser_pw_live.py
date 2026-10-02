"""The Playwright adapter against a local site: exactly the gate-allowed requests reach the server.

Marked ``browser`` like the repo's other real-browser tests: CI installs Chromium and refuses
any skip; on a machine where Chromium cannot launch the module skips itself. The site is
``tests/localsite.py``: ``localhost`` is the storefront, ``127.0.0.1`` the third party, both on
one port. No real retailer page is involved. ``CHROMIUM_ARGS`` (process-model flags) is honoured
so the same file runs inside the job image.
"""

from __future__ import annotations

import gzip
import os
import time
from collections.abc import Iterator

import pytest

from browser_capture import policy
from browser_capture.pw import PlaywrightSession
from browser_capture.session import TransportError, Visit
from tests import localsite
from tests.localsite import OTHER, STORE, Handler, Site

pytestmark = pytest.mark.browser

ARGS = tuple(a for a in os.environ.get("CHROMIUM_ARGS", "").split() if a)
HTTP = frozenset({"http"})


def robots_like(url: str) -> str | None:
    return "robots disallowed: /private/" if "/private/" in url else None


def gate() -> policy.Gate:
    return policy.Gate(
        frozenset({STORE}),
        policy.ENFORCE_HOSTS,
        frozenset(),
        document_check=robots_like,
        schemes=HTTP,
    )


@pytest.fixture(scope="module")
def session() -> Iterator[PlaywrightSession]:
    from playwright.sync_api import Error  # noqa: PLC0415

    try:
        s = PlaywrightSession(ARGS)
    except Error as exc:  # right on a laptop; CI asserts 0 skips so a broken install shows
        pytest.skip(f"Playwright chromium cannot launch: {exc.message.splitlines()[0]}")
    yield s
    s.close()


@pytest.fixture
def site() -> Iterator[Site]:
    s = localsite.serve()
    yield s
    s.close()


def visit(
    session: PlaywrightSession, site: Site, path: str, paced: list[str] | None = None
) -> tuple[policy.Gate, Visit]:
    g = gate()
    got = session.visit(
        site.url(STORE, path),
        g,
        nav_timeout_s=15,
        idle_timeout_s=3,
        screenshot=False,
        pace=(paced if paced is not None else []).append,
    )
    return g, got


def test_only_the_document_and_its_own_data_call_reach_the_server(
    session: PlaywrightSession, site: Site
) -> None:
    g, got = visit(session, site, "/page")
    assert got.status == 200
    assert got.title == "Local page"
    assert session.engine.policy_args == policy.SHUT_PATHS
    assert got.final_url == got.document_url == site.url(STORE, "/page")
    assert got.hops == ()
    assert not got.navigated_away
    assert b"<h1>Local page</h1>" in got.server_body
    # the picture, the frame, the pop-ups, the worker, the sockets and every third-party call
    # were refused before leaving; only the document and the storefront's own GET went out
    assert site.paths() == {f"{STORE}/page", f"{STORE}/own-fetch"}
    assert not [h for h in site.hits if h.upgrade]  # no WebSocket handshake at all
    assert g.counts["refused_popup"] >= 1
    assert g.counts["popups_closed"] >= 1
    assert g.counts["refused_websocket"] >= 2
    assert g.counts["refused_type_image"] == 2
    assert g.counts["refused_third_party"] >= 1  # fetch-get
    assert g.counts["refused_third_party_write"] == 1  # fetch-post
    assert g.counts["refused_frame_document"] == 1
    assert g.hosts_seen.get(OTHER, 0) >= 2
    assert "/sw.js" not in {h.path for h in site.hits}
    # the shared worker never started (its script was never asked for, so its fetch never ran)
    assert "/shared.js" not in {h.path for h in site.hits}
    assert "/from-shared" not in {h.path for h in site.hits}
    assert "SharedWorker:undefined" in got.rendered
    # WebRTC does not exist in the page or in its about:blank frame, so nothing reached the
    # page-chosen STUN server (UDP) or TURN server (TCP)
    for name in ("RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel"):
        assert f" {name}:undefined" in got.rendered
    assert "iframeRTCPeerConnection:undefined" in got.rendered
    assert site.udp_packets == []
    assert site.tcp_connections == []


def test_negative_control_without_the_init_script_webrtc_reaches_the_turn_server_over_tcp(
    session: PlaywrightSession, site: Site
) -> None:
    """The same page in a plain context of the same browser, launch flags included but no init
    script: ICE goes out over TCP to the page-chosen TURN server, which is exactly what the
    listener and the assertion above are there to catch."""
    browser = session._pw.chromium.launch(args=[*policy.SHUT_PATHS, *ARGS])
    try:
        page = browser.new_context().new_page()
        page.goto(site.url(STORE, "/page"), wait_until="domcontentloaded")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not site.tcp_connections:
            time.sleep(0.1)
        features = page.inner_text("#features")
    finally:
        browser.close()
    assert " RTCPeerConnection:function" in features
    assert len(site.tcp_connections) >= 1  # the TURN Allocate arrived
    assert site.udp_packets == []  # the launch flag alone does shut UDP; TCP is why the script


def test_a_redirect_off_the_storefront_stops_before_the_hop_is_requested(
    session: PlaywrightSession, site: Site
) -> None:
    g = gate()
    with pytest.raises(TransportError, match="document refused"):
        session.visit(
            site.url(STORE, "/redirect-away"),
            g,
            nav_timeout_s=15,
            idle_timeout_s=3,
            screenshot=False,
            pace=lambda u: None,
        )
    assert site.paths() == {f"{STORE}/redirect-away"}  # 127.0.0.1/hop was never asked for
    assert g.refused_document is not None
    assert g.refused_document[0] == site.url(OTHER, "/hop")
    assert "not in the allowed set" in g.refused_document[1]


def test_a_redirect_the_robots_check_refuses_is_not_followed(
    session: PlaywrightSession, site: Site
) -> None:
    g = gate()
    with pytest.raises(TransportError, match="robots disallowed"):
        session.visit(
            site.url(STORE, "/redirect-private"),
            g,
            nav_timeout_s=15,
            idle_timeout_s=3,
            screenshot=False,
            pace=lambda u: None,
        )
    assert site.paths() == {f"{STORE}/redirect-private"}
    assert g.refused_document == (site.url(STORE, "/private/x"), "robots disallowed: /private/")


def test_a_redirect_on_the_storefront_is_followed_as_a_paced_new_navigation(
    session: PlaywrightSession, site: Site
) -> None:
    paced: list[str] = []
    g, got = visit(session, site, "/redirect-home", paced)
    assert got.status == 200
    assert [(h.url, h.status) for h in got.hops] == [(site.url(STORE, "/redirect-home"), 302)]
    assert got.final_url == got.document_url == site.url(STORE, "/landed")
    assert [(d.url, d.status) for d in got.documents] == [(site.url(STORE, "/landed"), 200)]
    assert paced == [site.url(STORE, "/landed")]  # the hop waited its turn on the host
    assert g.counts["documents"] == 2
    assert site.paths() == {f"{STORE}/redirect-home", f"{STORE}/landed"}


def test_a_compressed_document_renders_and_is_kept_decoded(
    session: PlaywrightSession, site: Site
) -> None:
    body = gzip.compress(b"<html><title>gzipped</title><body><p>zip</p></body></html>")
    orig = Handler.do_GET

    def do_get(self: Handler) -> None:
        if self.path == "/page-gz":
            self._hit()
            self._send(200, body, "text/html", {"Content-Encoding": "gzip"})
        else:
            orig(self)

    Handler.do_GET = do_get  # type: ignore[method-assign]
    try:
        _, got = visit(session, site, "/page-gz")
    finally:
        Handler.do_GET = orig  # type: ignore[method-assign]
    assert got.title == "gzipped"
    assert b"<p>zip</p>" in got.server_body
    assert "<p>zip</p>" in got.rendered


def test_a_script_navigation_is_a_second_gated_document_and_is_flagged(
    session: PlaywrightSession, site: Site
) -> None:
    orig = Handler.do_GET
    second = site.url(STORE, "/second")
    away = (
        f'<html><title>first</title><body><script>location.href="{second}"</script></body></html>'
    )

    def do_get(self: Handler) -> None:
        if self.path == "/moves":
            self._hit()
            self._send(200, away.encode(), "text/html")
        else:
            orig(self)

    Handler.do_GET = do_get  # type: ignore[method-assign]
    try:
        g, got = visit(session, site, "/moves")
    finally:
        Handler.do_GET = orig  # type: ignore[method-assign]
    assert got.navigated_away
    assert got.final_url == got.document_url == site.url(STORE, "/second")
    assert [d.url for d in got.documents] == [site.url(STORE, "/moves"), site.url(STORE, "/second")]
    assert got.title == "/second"
    assert g.counts["documents"] == 2
