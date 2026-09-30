# Proxy Decision Report: ulta.ae

- **Status:** owner decision required; no proxy is approved by this report.
- **Date:** 2026-09-30 UTC
- **Source context:** Ulta Beauty UAE, public logged-out catalogue, EN and AR
- **Current collection state:** `blocked` / `not_observed`
- **Governing decisions:** ADR-0003, ADR-0005 and ADR-0006
- **Evidence basis:** existing recon, the Gulf probe records and the PR #15 review; this report made
  no network requests.

## Executive recommendation

Do **not** buy or use a residential proxy for the demo. Keep ulta.ae blocked/not-observed through
the 48-hour cool-off, fix the probe's robots and cross-egress back-off defects, and then make one
owner-authorised stock-WebKit desktop re-test from `me-central1`. Use a fresh browser context, a
minimum five-second page interval and a fail-closed robots gate. A challenge, 401, 403 or 429 ends
the test without another egress or client.

If that single re-test is challenged, accept the Ulta coverage gap for the demo. A paid proxy should
remain a later owner decision after a terms/legal review and a new technical decision: the current
rung-5 implementation permits JSON/API traffic only, while the known useful Ulta product calls are
page-loaded and the direct GraphQL query-string route is robots-disallowed. A proxy therefore does
not currently offer a compliant, end-to-end crawl path.

## Evidence timeline

All times below are from the existing 2026-09-30 probe records. The pending PR #15 report needs the
corrections listed under “Evidence limitations”; this report incorporates those corrections rather
than repeating the original claims.

- **Before the Gulf probe — our non-GCP server, plain HTTP:** `robots.txt` and the UAE home
  page returned Cloudflare 403. No escalation followed in that recon.
- **20:24 — `me-central1`, plain HTTP and stock Chromium:** ulta.ae returned Cloudflare 403.
  A Chromium request was also sent to the robots-disallowed
  `/en/search?keywords=lipstick` URL because the probe gate failed open after the plain-HTTP
  robots request returned 403.
- **20:32 — `me-central1`, stock browsers:** WebKit headless desktop and the stock iPhone 14
  descriptor returned usable 200 pages. Chromium and Firefox variants returned Cloudflare 403.
- **20:38 — `me-central1`, stock WebKit desktop:** `robots.txt`, sitemap, three EN and three AR
  PDPs, and EN/AR listings returned usable 200 responses.
- **20:42 — our server, stock WebKit desktop:** robots, sitemap, six PDPs and the EN listing
  returned 200. The next, AR-listing page returned a Cloudflare managed challenge with HTTP 429.
- **20:55–21:00 — `me-central1`, `europe-west1`, `asia-south1`, stock WebKit:** requests
  continued from three egresses after the 20:42 host-level 429. Six of nine pages were then
  challenged; three returned 200. All Ulta requests stopped and the source was reported blocked.
- **20:58 — `me-central1`, ulta.com.kw:** plain HTTP and stock WebKit returned Cloudflare 403.
  Kuwait is a separate KWD source context and is not a UAE fallback.
- **Not run — `me-central2`:** the organisation resource-location policy refused the required
  regional Artifact Registry resource with `LOCATION_POLICY_VIOLATED`. The refusal was not
  worked around.
- **After the block — Algolia route:** the owner temporarily approved an Algolia-only demo
  route. No request was sent: the required values were not in an approved capture or Secret
  Manager, and a safety classifier refused credential materialisation from a local capture.
  The refusal applies to the whole team and was not retried.

The successful window shows that ordinary stock WebKit could reach the public site. It does not
establish a stable crawl method: after roughly 70 WebKit page loads across several egresses in about
30 minutes, WebKit itself received managed challenges. Each page load caused roughly 25–35
subrequests, so page count understates host traffic.

### Evidence limitations and incidents

The probe provides useful reachability evidence, but it is not a clean production-rate experiment:

1. **Robots failed open.** Rules were loaded only after a 200 `robots.txt`; the plain-HTTP robots
   request returned 403, so later Ulta URLs were not gated. At least the Chromium
   `/en/search?keywords=lipstick` request was robots-disallowed. The statement that every probed
   Ulta URL was allowed is incorrect. A production or re-test gate must fail closed when robots is
   401/403/429, 5xx or unreachable; 404/410 means no rules.
2. **Back-off was not host-global.** After the server-side 429 at 20:42, the probe continued from
   three other egresses at 20:55. Future back-off is per host across all egresses, with no
   cross-egress retry.
3. **Early pacing was too fast.** Early Ulta stages used about one second per page, below the later
   five-second floor. Only the final extra cells used five seconds per page.
4. **Mobile descriptors change the User-Agent.** They were stock Playwright device descriptors,
   not a custom fingerprint or stealth patch, but “no impersonation” must not be read as an
   unchanged User-Agent across desktop and mobile cells.

These incidents argue for a cool-off and one controlled re-test, not immediate escalation.

## What was and was not tried

### Tried

- Plain `httpx` with ordinary, fixed browser headers.
- Stock Playwright Chromium, Firefox and WebKit, headless and headed where supported.
- Stock desktop and mobile device profiles; no custom fingerprint.
- Direct egress from our server and ordinary cloud egress from `me-central1`, `europe-west1` and
  `asia-south1`.
- Fresh browser contexts without WAF-cookie reuse.

### Not tried

- No residential or mobile proxy, VPN, Tor or purchased egress.
- No stealth browser, TLS/JA3 or HTTP/2 fingerprint impersonation, fingerprint rotation, patched
  browser, persistent browser profile or cookie replay.
- No CAPTCHA or Cloudflare challenge solving.
- No login, account, loyalty flow, cart or checkout.
- No direct replay of the robots-disallowed GraphQL query-string URL.
- No Algolia request; the safety-classifier refusal stopped the attempt before credentials were
  obtained.
- No app endpoint. The separate app study stopped at official-package provenance.

## Options for the owner

### Option 1 — wait, then make one ordinary re-test (recommended)

After the 48-hour cool-off, run one stock WebKit desktop page from `me-central1` with the source's
pinned engine, a fresh context, at least five seconds between pages and the corrected fail-closed
robots gate. Do not request search/query-string pages. Stop on any challenge or 401/403/429; do not
try another engine, User-Agent or egress.

- **Cost:** effectively $0 within the existing serverless free/low-use envelope; at most cents for
  one short Cloud Run job.
- **Benefit:** tests whether the block was temporary without introducing a new vendor or access
  method.
- **Risk:** another challenge is likely and yields no catalogue. The test must remain deliberately
  small.

### Option 2 — owner-approved UAE residential proxy pilot

This is rung 5 and requires a separate written owner approval after legal/terms review. Vendor
examples below are market names, not endorsements. Prices are memory-based planning figures only;
all availability, UAE targeting, minimum commits, VAT and current prices are **to verify** before a
purchase. No vendor site was contacted for this report.

| Vendor | Indicative residential price | UAE targeting / terms | Status |
|---|---:|---|---|
| Bright Data | about $8–10/GB PAYG | to verify | to verify |
| Oxylabs | about $8–10/GB PAYG | to verify | to verify |
| Decodo (formerly Smartproxy) | about $7–9/GB PAYG | to verify | to verify |
| SOAX | about $4–7/GB, often plan-based | to verify | to verify |
| IPRoyal Pawns | about $7–9/GB PAYG | to verify | to verify |

A pilot must use one stable UAE egress—not rotation—and ordinary clients only. It must not solve a
challenge, acquire or replay WAF cookies, or continue after a refusal. Every request and observation
must record `residential_proxy` / rung 5 and the approved provider/egress. A hard data and money cap
is required before starting.

There is also a technical blocker. Current `pi_fetch` policy permits paid-proxy traffic for JSON/API
requests only. Ulta's direct GraphQL GET has a query string that robots disallows, and the permitted
use was to observe it as a response loaded by the page inside the browser. Sending WebKit page loads
through a paid proxy would expand the current rung-5 contract and needs a reviewed ADR/code change.
The proxy should not be purchased until the owner has approved a compliant request plan that can
actually produce the required fields.

### Option 3 — accept blocked coverage

Keep Ulta `blocked` / `not_observed`, show the coverage gap in the demo and continue with Sephora
UAE and other approved sources. Do not emit out-of-stock, removal or zero-price facts from the
blocked run.

- **Cost:** $0.
- **Benefit:** lowest legal, operational and reputational risk; preserves the evidence trail.
- **Trade-off:** no Ulta catalogue or price comparison until access changes or a licensed source is
  approved.

## Budget impact

The programme's total operating budget is **$25/month**. The existing planning assumption for UAE
residential traffic is **$3–8/GB**, while the named vendors above may be higher and are all to
verify.

| Workload | Planning volume | At $3–8/GB | Budget fit |
|---|---:|---:|---|
| JSON/index route | ~4.5 GB/month | $13.50–36/month | Low end only; route unavailable. |
| PDP/browser catalogue | about 60–100 GB/month | $180–800/month | Does not fit. |
| Capped pilot | ≤1 GB | $3–10 plus minimum | Approval required. |

Even a $10 one-off pilot would consume 40% of the monthly budget and would not prove that a
full-catalogue browser crawl is affordable. Images should never transit the paid proxy, but
excluding them does not bring the estimated page-crawl traffic under budget.

## Legal, terms and guardrail review

Public catalogue visibility is not permission to bypass access controls. Before any proxy purchase
or test, the owner must review the current Ulta/Alshaya terms for automated access and proxy use and
record the rights basis. Robots rules remain binding: query-string listing/search pages are
disallowed, and the direct GraphQL query URL is not a crawl target. A residential IP does not change
those rules.

The following guardrails are non-negotiable:

- owner approval names the provider, egress, endpoint set, traffic cap, spend cap and expiry;
- fixed UAE egress and honest, ordinary clients; no IP/fingerprint rotation;
- no stealth, challenge solving, CAPTCHA service, cookie harvesting/replay or account flow;
- fail-closed robots enforcement before every target;
- host-global pacing/back-off across egresses; 429 means stop/back off, never rotate;
- blocked/partial observations remain `not_observed` or `blocked`, never out-of-stock or removed;
- evidence records the URL, response hash, rung, method, egress and cutoff without secrets; and
- any safety-classifier refusal ends the whole route for the team, without another tool or model.

## Decision requested

Choose one:

1. **Recommended:** 48-hour cool-off, one corrected stock-WebKit re-test, then accept blocked for
   the demo if challenged.
2. Commission legal/terms and technical design work for a capped UAE residential-proxy pilot; do
   not purchase until the owner approves the resulting endpoint and cost plan.
3. Accept blocked coverage now and revisit only if ordinary access or a licensed feed becomes
   available.

## References

- [ADR-0003: collection escalation ladder](../adr/0003-collection-escalation-ladder.md)
- [ADR-0005: UAE pilot and Gulf probe](../adr/0005-uae-pilot-robots-deviation-gulf-probe.md)
- [ADR-0006: access rulings](../adr/0006-ladder-access-rulings.md)
- [Ulta ME recon](ulta_me.md)
- Gulf probe PR #15, head `ed2ebc4` (pending corrections at the time of this report)
- Reviewer findings on PR #15, 2026-09-30 UTC
