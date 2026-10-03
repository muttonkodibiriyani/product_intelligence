# browser_capture — one stock Chromium page view per plan item

Cloud Run job (also runs locally in Docker) that opens each URL of a **plan** in a real browser
and keeps what the server sent, what the page rendered, a screenshot, the redirect chain, headers
and timings. It exists for shops that answer a plain HTTP client with a JavaScript challenge
or an empty shell but serve an ordinary browser (ADR-0006, rung 2). It shares the plan, store,
robots and block-marker code with `page_capture`; nothing is fetched outside Playwright.

What "ordinary browser" means here, enforced by the job and recorded in `manifest.json`:

- Stock Playwright Chromium, headless, default context (default User-Agent, viewport, locale,
  no `extra_http_headers`). No stealth plugin, no fingerprint change, no CAPTCHA or challenge
  solving, no cookie reuse from an earlier run, no login, no cart, no proxy. `browser.stealth` is
  always `false` and `browser.proxy` is always `null` in the manifest.
- Every page gets its **own browser process**: launch, open, close. Cookies and storage never
  carry over. The only launch arguments are process-model flags passed in `CHROMIUM_ARGS`
  (for example `--no-sandbox --disable-dev-shm-usage --single-process --no-zygote`, needed under
  Docker on a host without user namespaces and under gVisor). They change how Chromium forks,
  not what a site sees; the manifest records them verbatim as `browser.launch_args`.
- `robots.txt` of every host is read first, through the browser's own request stack and
  User-Agent, before that host's first page. Redirects of `robots.txt` are followed one hop at a
  time, only to the same https host; anything else fails closed. A challenge marker or wall on
  `robots.txt` stops the host at once. 404/410 means nothing restricted. Any other non-200,
  transport error or HTML body makes robots **unavailable** and every URL on that host is refused.
- About one navigation per second per host (`PACE`, minimum 1.0 s) plus uniform jitter
  (`JITTER`), or the host's `Crawl-delay` if that is larger.
- Stop rules per host (other hosts continue): challenge marker in the server document or the
  rendered DOM, or 401/403, stops the host (`blocked`); two 429 in a row stop it (`rate_limited`,
  with a 60 s backoff doubling to 900 s in between); five consecutive transport errors stop it;
  one refused redirect hop stops it (`hop_host_refused`). Remaining items on a stopped host are
  recorded `skipped_host_stopped`.

## The request gate

Every request path a page has goes through `policy.Gate.decide` or is shut, at the browser
context so pop-up windows are covered too:

- **Documents.** The navigation, every redirect hop, every child-frame document and anything a
  script navigates to must be https, have no userinfo or port, sit on a host in `HOSTS`
  (default: the hosts of the plan's own URLs) and pass the job's own check: the host is not
  stopped and its `robots.txt` (read for every allowed host before the first page) allows the
  path. Documents are fetched by the handler with redirects **not** followed; a 3xx is never
  passed to Chromium. The hop is recorded, the navigation cancelled, and the hop is opened as a
  fresh navigation only after the gate and the per-host pacing have had their say (at most 5).
  A refused target ends the item with nothing stored: `hop_host_refused` (host rules),
  `robots_disallowed` or `robots_unavailable`, with the refused URL as `final_url`. A frame
  that redirects is simply refused (`refused_frame_redirect`).
- **Pop-up windows** are refused at the gate (`refused_popup`) and closed (`popups_closed`).
- **Service workers** are blocked by the context (`service_workers="block"`), so no worker script
  is ever requested and nothing runs behind the page.
- **WebSockets** are refused before the handshake (`refused_websocket`); none is ever connected.
- **Shared workers and WebRTC** have no route handler to pass through, so they are shut at
  launch by `policy.SHUT_PATHS` (`--disable-features=SharedWorker`,
  `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`): no shared worker script is
  requested and no STUN datagram leaves. These are recorded in the manifest as `policy_args`,
  apart from the process-model `launch_args`. The UDP flag alone only moves ICE onto TCP, and a
  TURN allocation over TCP would still reach a host the page chooses, so `policy.NO_WEBRTC` is
  added as an init script to every frame before any page script runs: it deletes
  `RTCPeerConnection`, `webkitRTCPeerConnection` and `RTCDataChannel`. No constructor, no
  connection on any transport. The manifest records it as `init_script`.
- **Pictures, media, fonts, beacons, pings, manifests, text tracks, event sources** and anything
  of unknown type never leave (`refused_type_<type>`).
- **Scripts, stylesheets and data calls** (`xhr`, `fetch`) must be https. A data call that is not
  a `GET`/`HEAD` and does not go to the storefront's own hosts is refused in every mode
  (`refused_third_party_write`): the capture never writes to anyone else. The rest follows
  `SUBRESOURCES`:
  - `record` (default): allowed to any https host; the hosts and counts are written per page as
    `hosts_seen` and `requests`. This is for the first run on a shop: the report yields the list
    of hosts the page really needs.
  - a host list (`SUBRESOURCES=cdn.example,api.example`): only those hosts; the rest are aborted
    and counted as `refused_third_party`. This is the production setting once the list is known.

Each row records `document_url` (the document the DOM belongs to) and `documents` (every
document the main frame committed). When a script moved the page after the asked-for document
loaded, the row is `navigated_away` with the reason `script moved to <url>`, so the evidence is
never read as the page that was asked for.

The job also audits the chain it gets back after the fact: any hop or document off the allowed
set is `hop_host_refused` even if it was fetched, and its bodies are not stored.

## Output

Under `gs://$BUCKET/$PREFIX/` (or `file:<dir>` for local runs), never rewritten:

| Object | Content |
| --- | --- |
| `manifest.json` | run start, plan, hosts, subresource policy, egress label, git sha, and the `browser` block (engine, version, playwright, user agent, viewport, headless, stealth, proxy, launch args) |
| `pages/part-NNNN.jsonl.gz` | one row per plan item: `state`, `status`, `final_url`, `redirects`, `hops`, `nav_ms`, `settle_ms`, `idle_timeout`, `requests`, `hosts_seen`, `title`, digests and names of the stored bodies |
| `raw/<sha256>.server.html.gz` | the document as the server sent it |
| `raw/<sha256>.html.gz` | the DOM after the network went idle (or after `IDLE_TIMEOUT`) |
| `raw/<sha256>.robots.txt.gz` | each host's robots.txt as served |
| `shots/<sha256>.png` | the viewport screenshot (`SCREENSHOT=1`) |
| `errors/part-NNNN.jsonl.gz` | one row per block with the first 2000 characters of the body |
| `robots.json` | per host: status, state, rule count, crawl delay, redirects, digest |
| `progress.json` | counts so far, written at every flush |
| `status.json` | outcome (`complete`, `cutoff`, or stopped), per-host counts, `hosts_blocked` |

Sharded runs (`CLOUD_RUN_TASK_COUNT` > 1) suffix `manifest.tN.json`, `status.tN.json` and
`part-tN-NNNN` so tasks never overwrite each other.

States: `ok`, `navigated_away`, `http_error`, `blocked`, `rate_limited`, `transport_error`,
`hop_host_refused`, `robots_disallowed`, `robots_unavailable`, `skipped_cutoff`,
`skipped_host_stopped`. There is no
silent default: an item without a document response is `http_error` with reason
`no document response`.

## Running

Environment: `BUCKET`, `PREFIX`, `PLAN` (a `gs://` or local path to a `page_capture` plan;
only `kind: html` items are opened), `CUTOFF` (ISO 8601 with a timezone), optional `PACE`,
`JITTER`, `LIMIT`, `EGRESS` (a label for the manifest), `HOSTS`, `SUBRESOURCES`, `SCREENSHOT`,
`NAV_TIMEOUT`, `IDLE_TIMEOUT`, `CHROMIUM_ARGS`, `GIT_SHA`, and Cloud Run's task index/count.

Build from `tools/` so the image sees both packages:

```sh
docker build -t pi-browser-capture:dev -f browser_capture/Dockerfile tools/
docker run --rm --network host --ipc=host --init \
  -v "$KEY":/secrets/sa.json:ro -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa.json \
  -e BUCKET=... -e PREFIX=shop/2026-10-02/browser-r1 -e PLAN=gs://.../plan.json \
  -e CUTOFF=2026-10-02T20:30:00+00:00 -e SUBRESOURCES=record -e SCREENSHOT=1 \
  -e CHROMIUM_ARGS='--no-sandbox --disable-dev-shm-usage --single-process --no-zygote' \
  pi-browser-capture:dev
```

The unit tests drive `run.Job` through a scripted fake session and a `file:` store; no real
retailer page is ever used in a fixture. The Playwright adapter (`pw.py`) is proven by
`tests/test_browser_pw_live.py` against a local site (`tests/localsite.py`: `localhost` is the
storefront, `127.0.0.1` the third party) that serves a page with pictures, a cross-host frame,
third-party GET and POST calls, two pop-ups, a service worker, a shared worker, two WebSockets
and a WebRTC connection aimed at a local STUN listener (UDP) and a local TURN listener (TCP).
The test asserts that exactly the gate-allowed requests reach the server, that zero UDP
datagrams and zero TCP connections arrive, and that the WebRTC constructors are undefined in the
page and in an `about:blank` frame; a negative control runs the same page in a plain context
(flags, no init script) and shows the TURN listener does get a TCP connection, so the
assertion is live. It also checks that off-storefront and robots-refused
redirects stop before the hop is requested, that an own-host redirect is paced and recorded, that
a gzip document is kept decoded, and that a script navigation is flagged. It is marked `browser`:
CI installs Chromium and refuses any skip; where Chromium cannot launch it skips itself. To run it
inside the job image:

```sh
docker run --rm --network host --ipc=host --init -v "$PWD/tools:/work:ro" \
  -e PYTHONPATH=/work/page_capture:/work/browser_capture:/work/browser_capture/tests \
  -e CHROMIUM_ARGS='--no-sandbox --disable-dev-shm-usage --single-process --no-zygote' \
  pi-browser-capture:dev sh -c "pip install -q pytest && cd /work/browser_capture && \
  python -m pytest tests/test_browser_pw_live.py -q"
```
