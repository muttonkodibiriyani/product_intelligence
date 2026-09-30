# ADR-0006: Ladder access rulings: plain-HTTP rung 1, no stealth, stop at blocks

- Status: accepted (owner rulings, 30 Sep 2026, relayed by the program coordinator)
- Date: 2026-09-30
- Amends: ADR-0003 (escalation ladder) and blueprint §6.3
- Requirement IDs: SRC-08, SEC-05 (owner deviations), SRC-01, SEC-10 (audit trail)

## Context
ADR-0003 defined rung 1 as `curl_cffi` browser impersonation and rung 3 as stealth browsers
(Scrapling / Camoufox / patchright, fingerprint rotation, persistent profiles, cookie reuse).
The owner has since narrowed what the ladder may do. The guardrail for UAT-25 is: when ordinary
access is blocked, mark the source blocked, stop and report.

## Decisions
1. **Rung 1 is plain HTTP.** `httpx` with normal, honest headers and session reuse. There is
   **no** TLS/JA3 or HTTP/2 fingerprint impersonation; `curl_cffi` is rejected.
2. **Rung 2 is a real browser.** Playwright Chromium or Firefox, headless or headed, with
   **no** stealth patches or fingerprint spoofing.
3. **Rung 3 is disabled: never attempted or recorded.** Stealth browsers, fingerprint
   rotation and cookie reuse are not used. The number 3 stays reserved so rung numbering is stable. It is refused in `pi_core`
   (constructing or recording rung 3 is an error) and by database CHECK constraints
   (`rung <> 3`).
4. **Blocked after rungs 0/1/2/4: stop and report.** The source context is marked blocked,
   collection for it stops, the coverage loss is visible, and a **Proxy Decision Report** is
   sent. The owner decides whether to buy rung 5 (residential proxy). Nothing escalates on its
   own beyond the approved rungs.
5. **Never work around a safety-classifier refusal.** This covers routing the task through
   another agent, model or tool. A refusal is reported as a blocker.

The ADR-0003 and ADR-0005 hard lines stand unchanged: no logins, no paywall bypass, no
cart/checkout, polite pacing, and every escalation audit-logged.

## Fetch methods
`FetchMethod` values recorded on every evidence row, each tied to exactly one rung:

| Rung | `FetchMethod` values |
|---|---|
| 0 | `site_api`, `embedded_json`, `sitemap` |
| 1 | `plain_http` |
| 2 | `playwright` |
| 3 | *(none: disabled)* |
| 4 | `egress_variation` |
| 5 | `residential_proxy` |

## Consequences
- `pi_core` enums follow this table. Required renames:
  - `LadderRung.IMPERSONATED_HTTP = 1` → `LadderRung.PLAIN_HTTP = 1`.
  - `LadderRung.STEALTH_BROWSER = 3` stays only as a **forbidden** member, so the number is
    reserved. `pi_core` refuses to select or record it (forbidden-rung policy), and
    `CHECK (rung <> 3)` rejects it in the database.
  - `FetchMethod.CURL_CFFI = "curl_cffi"` → `FetchMethod.PLAIN_HTTP = "plain_http"` (rung 1).
  - `FetchMethod.SCRAPLING`, `FetchMethod.CAMOUFOX` and `FetchMethod.PATCHRIGHT` are removed.
  - Unchanged: `SITE_DATA`, `BROWSER`, `EGRESS_VARIATION` and `PAID_PROXY` rungs; the `site_api`,
    `embedded_json`, `sitemap`, `playwright`, `egress_variation` and `residential_proxy`
    methods.
- The DB schema adds `CHECK (rung <> 3)` wherever a rung is stored, with a parity test against
  `pi_core`.
- UAT: SRC-08 accepts that rung 3 is never attempted or recorded and that rung 1 does no TLS
  impersonation. UAT-25 asserts stop, mark blocked and report.
- Coverage may be lower on bot-protected sources. The Proxy Decision Report is the only path
  past a block.
- robots.txt is matched per RFC 9309 (wildcards, `$`, longest match, Allow wins ties). Every
  source obeys it except those configured `tag_only` (Sephora, ADR-0005). The status of the
  robots.txt fetch decides what happens when there is no usable file (coordinator decision,
  2026-09-30). This is deliberately stricter than RFC 9309 §2.3.1.3 for 4xx other than 404/410:
  - 404/410: no robots.txt; all allowed, per RFC.
  - A 2xx HTML page instead of robots.txt: unreadable; refuse every URL on the host.
  - 401/403/429 and every other 4xx: refuse every URL on the host. We are being blocked or throttled, and policy is
    to stop, not to assume allow.
  - 5xx or unreachable: refuse every URL on the host.
  See `packages/pi_fetch/README.md` (runbook).

## Amendment 1 (2026-09-30 UTC): owner rulings from the Gulf probe
1. **Browser engine choice.** Playwright's stock Chromium, Firefox and WebKit engines are all
   ordinary rung-2 clients, headless or headed, desktop or mobile profile. Using the engine
   that a site serves normally is allowed; for ulta.ae that is WebKit, because Chromium and
   Firefox got a Cloudflare 403. No stealth patches, no cookie reuse, a fresh context per
   attempt, and no challenge solving. If the working engine starts being challenged, collection
   stops and is reported; it does not rotate engines or user agents to get past the challenge.
   To make this boundary mechanical:
   - The engine and device profile are **pinned per source in configuration** by owner or
     coordinator decision (for example, ulta.ae uses WebKit).
   - `pi_fetch` has **no automatic engine fallback**. A blocked engine returns a blocked
     result.
   - The engine, headless/headed mode and device profile are recorded in evidence metadata.
2. **ulta.ae first-party calls.** The data the page itself loads (`/graphql`,
   `query-index.json`, `promotion-schedule.json`) is read inside the browser session. ulta.ae's
   `robots.txt` is obeyed, including for those API and JSON paths. The robots override from ADR-0005 applies to Sephora only.
3. **ulta.ae search via Algolia.**
   - **(A) Primary route:** read the search and listing responses the page loads inside the
     browser.
   - **(B) Approved as complement and fallback:** direct read-only search queries to ulta.ae's
     Algolia host, using the public search-only key the page embeds. Allowed uses are
     catalogue enumeration, coverage cross-checks and filling gaps. Conditions:
     - pacing of at most 1 req/s with jitter, run off-peak;
     - the same index and parameters as the site frontend;
     - no admin or write endpoints;
     - the key is read at runtime from the page or from Secret Manager, is never committed, and
       is redacted in fixtures.

     Recorded as `FetchMethod.site_api` (rung 0).
   - **Guardrail:** B is allowed only while ulta.ae itself is reachable by our browser. If
     ulta.ae blocks us, collection does not quietly switch to Algolia-only. It pauses and is
     reported, and the owner decides.
   - **Enforcement (review gates for any Algolia-route PR):**
     - **Key hygiene:** the key is redacted everywhere: stored request URLs, headers,
       `x-algolia-api-key` query parameters, captured JSON, logs, exceptions and fixtures. A
       test asserts that a recorded request never contains the key.
     - **Provenance:** recorded as `site_api` (rung 0). No new `FetchMethod` value. The
       evidence request URL must show the Algolia host.
     - **Mechanical guardrail:** `pi_fetch` refuses the Algolia route for a source context
       that is blocked or paused, and emits a report or event instead of falling back.
       Tested: ulta.ae blocked ⇒ Algolia request refused.
     - **Read-only:** only the query endpoint paths and methods are allowlisted. Settings,
       keys, batch and other paths are rejected.
     - **Pacing:** at most 1 req/s with jitter and off-peak, enforced per host in the
       `pi_fetch` rate limiter.
4. **Ulta ME mobile app study** (`com.ub.mena`): on hold until the owner says go.

## Amendment 2 (2026-09-30 UTC): owner approves rung 5 for ulta.ae
The owner has answered the ulta.ae Proxy Decision Report: he bought a UAE residential proxy
(IPRoyal, AE exit) and approved rung 5 for **ulta.ae only**. This supersedes the 48 h cool-off.
Rung 5 is the rung-2 browser (Amendment 1: pinned stock WebKit, no stealth) sending its traffic
through the proxy. It does not add any new client technique. Conditions:

1. **Scope:** ulta.ae only. Sephora and every other source stay without a proxy. The proxy is
   enabled per source in configuration and recorded as `FetchMethod.residential_proxy` (rung 5),
   with the engine, device profile and egress in the evidence metadata.
2. **Same page and robots transport:** `robots.txt` is fetched through the same pinned engine and
   the same proxy egress as the pages. The fail-closed status matrix applies, and HTML or a challenge served with a 2xx
   means unreadable, which refuses the host. There is no fallback to another transport, engine or egress.
3. **Stop at the first challenge:** a challenge is classified by the response body and markers
   (for example, a Cloudflare "Just a moment..." or managed-challenge page), **not** by the status code.
   Any challenge (whether served as 403, 429 or 503), and any 401 or 403, stops the whole run and
   marks ulta.ae blocked. There is no solving, no retry and no switch of engine, user agent or egress.
   Only a plain 429 without challenge markers backs off per host. **Two consecutive 429s stop the
   run.** If the ~20-page test is challenged, Ulta stays blocked and no further proxy spend is made.
4. **Sequence and volume:** a ~20-page test first. Then, if the test is clean, **one** full-catalogue snapshot, stored permanently.
   There is no recurring Ulta crawl (on-demand cadence, blueprint §6.4). The pace is at most 1 page per 5–10 s, off-peak.
5. **Minimal proxy traffic:** heavy assets (images, media, fonts, third-party trackers) are
   blocked in the proxied browser, and images are fetched directly from the CDN, not through the proxy.
   A per-run proxy byte counter is recorded in the run manifest. The **hard stop at 1.8 GB** (the balance is 2 GB bought at $6.25/GB; 0.2 GB is kept for a re-test; more only if the
   owner approves more) is **enforced inside `pi_fetch`**: a request that would cross the cap is not sent,
   and the run aborts. The proxy configuration is **refused for any source other than ulta.ae**.
   Both are covered by tests.
   Direct image fetches obey the image CDN's own `robots.txt` and have their own per-host pacing.
6. **Credentials:** they are read at runtime from Secret Manager
   (`pi-proxy-iproyal-ae`, latest version). They are never printed, logged, committed or put in
   fixtures, and they are redacted in reprs, audit events and exceptions. The secret must be rotatable
   without code changes. The password was briefly visible in the owner chat, so it should be
   rotated **before first use**; the coordinator has asked the owner to do this. If it is not
   rotated before first use, this is recorded as an owner-accepted risk and it is rotated after the demo.
7. **Unchanged:** logins, cookie reuse, checkout, stealth (rung 3), TLS impersonation and
   challenge solving remain prohibited. Classifier refusals are never routed around.

**Recorded concern (Reviewer, owner-accepted risk):** using a residential proxy while the site's
WAF is actively challenging our other egresses sits uneasily with "not permission to bypass
access controls". The owner accepted this risk with the stop-at-first-challenge condition above.
**Legal/ToS review waived by the owner:** the cadence decision (2026-09-30, blueprint §6.4) makes a
legal/ToS review a precondition for rung 5. The owner's explicit instruction to build and crawl
ulta.ae now waives that precondition for this snapshot. The review by counsel remains an open item
for the owner, and it is required before any further Ulta refresh.

**Vendor note:** residential proxy exits are other people's connections. We rely on IPRoyal's stated
consent-based pool, which we have not verified independently.

**Proxy Decision Report (#19):** superseded by this amendment. It is closed as answered, with the
owner's decision recorded here.
