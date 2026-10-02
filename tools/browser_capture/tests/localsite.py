"""A local site with every request path a page can open, recording what reached the server.

Used by the real-browser test of the Playwright adapter. One ThreadingHTTPServer on 127.0.0.1
answers two names: ``localhost`` plays the storefront and ``127.0.0.1`` plays a third party; the
``Host`` header tells them apart. Nothing here is a retailer page.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STORE = "localhost"
OTHER = "127.0.0.1"


@dataclass
class Hit:
    host: str
    method: str
    path: str
    upgrade: str = ""


@dataclass
class Site:
    server: ThreadingHTTPServer
    hits: list[Hit] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def url(self, host: str, path: str) -> str:
        return f"http://{host}:{self.port}{path}"

    def record(self, hit: Hit) -> None:
        with self.lock:
            self.hits.append(hit)

    def paths(self) -> set[str]:
        with self.lock:
            return {f"{h.host}{h.path}" for h in self.hits}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def page_html(site: Site) -> str:
    """One page that tries every way out: a picture, a fetch GET and POST to the third party,
    a popup, a service worker, two WebSockets, a cross-host iframe and a redirect hop."""
    other = site.url(OTHER, "")
    store = site.url(STORE, "")
    return f"""<!doctype html><html><head><title>Local page</title></head><body>
<h1>Local page</h1>
<img src="{other}/img.png" alt="">
<img src="{store}/own.png" alt="">
<iframe src="{other}/frame"></iframe>
<script>
fetch("{other}/fetch-get").catch(() => {{}});
fetch("{other}/fetch-post", {{method: "POST", body: "x"}}).catch(() => {{}});
fetch("{store}/own-fetch").catch(() => {{}});
try {{ window.open("{other}/popup"); }} catch (e) {{}}
try {{ window.open("{store}/popup-own"); }} catch (e) {{}}
if (navigator.serviceWorker) {{ navigator.serviceWorker.register("/sw.js").catch(() => {{}}); }}
try {{ new WebSocket("ws://{OTHER}:{site.port}/ws-other"); }} catch (e) {{}}
try {{ new WebSocket("ws://{STORE}:{site.port}/ws-own"); }} catch (e) {{}}
const a = document.createElement("a"); a.href = "{store}/redirect-away"; a.id = "away";
document.body.appendChild(a);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    site: Site  # set by serve()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _hit(self) -> Hit:
        host = (self.headers.get("Host") or "").split(":")[0]
        hit = Hit(host, self.command, self.path, self.headers.get("Upgrade") or "")
        self.site.record(hit)
        return hit

    def _send(
        self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self._hit()
        self._send(200, b"{}", "application/json")

    def do_GET(self) -> None:
        hit = self._hit()
        if hit.upgrade.lower() == "websocket":
            self._send(400, b"no websockets here", "text/plain")
        elif self.path == "/robots.txt":
            self._send(200, b"User-agent: *\nDisallow: /private/\n", "text/plain")
        elif self.path == "/page":
            self._send(200, page_html(self.site).encode(), "text/html")
        elif self.path == "/redirect-away":
            self._send(302, b"", "text/plain", {"Location": self.site.url(OTHER, "/hop")})
        elif self.path == "/redirect-home":
            self._send(302, b"", "text/plain", {"Location": self.site.url(STORE, "/landed")})
        elif self.path == "/redirect-private":
            self._send(302, b"", "text/plain", {"Location": self.site.url(STORE, "/private/x")})
        elif self.path == "/sw.js":
            self._send(200, b"self.addEventListener('fetch', e => {});", "text/javascript")
        elif self.path.endswith(".png"):
            self._send(200, b"\x89PNG\r\n\x1a\n", "image/png")
        elif self.path == "/private/x":
            self._send(200, b"<html><title>private</title></html>", "text/html")
        else:
            self._send(
                200, f"<html><title>{self.path}</title><body>ok</body></html>".encode(), "text/html"
            )


def serve() -> Site:
    """Start the site on a free port in a daemon thread."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    site = Site(server)
    Handler.site = site
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return site
