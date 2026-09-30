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

## Amendment 1 (2026-10-01): owner rulings from the Gulf probe
1. **Browser engine choice.** Playwright's stock Chromium, Firefox and WebKit engines are all
   ordinary rung-2 clients, headless or headed, desktop or mobile profile. Using the engine
   that a site serves normally is allowed; for ulta.ae that is WebKit, because Chromium and
   Firefox got a Cloudflare 403. No stealth patches, no cookie reuse, a fresh context per
   attempt, and no challenge solving. If the working engine starts being challenged, collection
   stops and is reported; it does not rotate engines or user agents to get past the challenge.
2. **ulta.ae first-party calls.** The data the page itself loads (`/graphql`,
   `query-index.json`, `promotion-schedule.json`) is read inside the browser session. ulta.ae's
   `robots.txt` is obeyed. The robots override from ADR-0005 applies to Sephora only.
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
4. **Ulta ME mobile app study** (`com.ub.mena`): on hold until the owner says go.
