# Gulf-egress probe: results (task 01a0f3d2-fb2d)

Run 2026-09-30, 20:24–21:00 UTC (off-peak Gulf). Tool: `tools/gulf_probe` (image built from
`tools/gulf_probe/Dockerfile`, run as a Cloud Run job and locally in Docker).

**Access used: ordinary only.** Plain `httpx` with normal browser headers (rung 1) and stock
Playwright Chromium/Firefox/WebKit, headless or headed (Xvfb), desktop or built-in mobile descriptors
(rung 2), from several egresses (rung 4). Every attempt got a fresh browser context, and three
consecutive blocks per (site, client) stopped that client. No TLS/HTTP2 impersonation, stealth
patches, fingerprint rotation, challenge solving or cookie reuse. Sephora's robots-disallowed paths
are owner-approved (ADR-0005).

Corrections after review (PR #15):
- **Pacing.** `PROBE_PACE` defaulted to 1 s (+0–60 % jitter). Only the last run (stage x,
  20:55–21:00) used 5 s per page for ulta.*. The earlier ulta.ae runs (stages 1, 2, 4 and our server,
  20:24–20:44) ran at ~1 req/s, **below the decision-log floor of ≥5 s per page** for ulta.ae.
- **Mobile descriptors change the User-Agent.** Playwright's built-in `iPhone 14` / `Pixel 7`
  descriptors send a mobile Safari/Chrome UA from a Linux engine, which is UA impersonation in
  effect. That is recorded here as a recon observation only. pi_fetch is desktop-only (ADR-0006
  Amendment 1), so it is not carried forward.
- **The robots gate failed open for ulta.*.** Rules were loaded only after a 200 robots.txt. httpx
  got a Cloudflare 403 on robots.txt, so ulta.* URLs requested before a browser fetched a usable
  robots.txt in the same run went **ungated**. One of them was robots-disallowed:
  `https://www.ulta.ae/en/search?keywords=lipstick` (Chromium, 20:28, Cloudflare 403). See
  [Robots gate incident](#robots-gate-incident-fail-open). The gate now fails closed (`analysis.robots_gate`, tested).
- **No cross-egress retry.** After our server got the 429 managed challenge (20:42), ulta.ae was
  requested again from me-central1, europe-west1 and asia-south1 (20:55–21:00). Egress comparison was
  the probe's purpose, but a host-level back-off must hold across egresses. Production rule
  (decision log, #17): pacing and back-off are **per host, independent of egress**, with no
  cross-egress retry after a 429 or challenge. pi_fetch's `HostPacer` is keyed by host.

## Verdict

| Site | Works with | Blocked | Status |
|---|---|---|---|
| sephora.me (UAE, `ae-en`/`ae-ar`) | plain httpx **from me-central1**; Chromium headless (me-central1); Firefox headless (our server) | plain httpx from our server (Akamai 403) | **usable**: crawl egress me-central1, plain httpx |
| ulta.ae | stock WebKit only (headless, desktop and iPhone 14) from me-central1, europe-west1, asia-south1 and our server, **until ~20:55 UTC** | plain httpx, Chromium (headless/headed/mobile), Firefox (headless/headed) = Cloudflare 403 everywhere. From 20:55 WebKit also gets the Cloudflare managed challenge ("Just a moment...") | **blocked / not_observed**, paused for the owner (recommended: 48 h cool-off, then one WebKit page from me-central1) |
| ulta.com.kw (Kuwait, KWD; never mixed with UAE) | none | httpx and WebKit = Cloudflare 403 (me-central1, 20:58) | **blocked** |

No Proxy Decision Report is needed for Sephora. For ulta.ae the owner decides after the cool-off.

## Timeline

| UTC | Egress | What happened |
|---|---|---|
| 20:24 | me-central1 | Stage 1: Sephora all 200 on httpx (robots, 80/80 product sitemaps, PDPs, category, search); Chromium 200. ulta.ae: httpx + Chromium = Cloudflare 403. |
| 20:32 | me-central1 | Stage 2 (ulta.ae) / Stage 4 (Sephora stability). ulta.ae: **WebKit** headless desktop + iPhone 14 = 200 usable; Firefox (headless/headed), Chromium headed and Chromium mobile = 403. Sephora: 6/6 PDPs (EN+AR), listings, sitemaps, image all 200. |
| 20:38 | me-central1 | ulta.ae WebKit stability: robots.txt, sitemap, 3 EN + 3 AR PDPs and EN/AR listings = 200 usable. |
| 20:42 | our server | ulta.ae WebKit: robots, sitemap, 6/6 PDPs, EN listing = 200; the 11th page (AR listing) = **429 Cloudflare managed challenge** (Arabic "لحظة…" page served with status 429). Sephora httpx = Akamai 403 ×3 (then stopped); Sephora Firefox = 200 usable. |
| 20:45 | me-central1 | Sephora catalogue verification (46 requests, below). |
| 20:55–21:00 | me-central1, europe-west1, asia-south1 | ulta.ae extra cells at 5 s/page: WebKit now **challenged** ("Just a moment...") on 6 of 9 WebKit pages (headed ×3 at me-central1; home at europe-west1; category + PDP at asia-south1); WebKit 200 on the other 3. Kuwait blocked. **Stopped all ulta requests** (WebKit ruling condition 4) and reported. |

Interpretation: Cloudflare on ulta.ae first blocked by client (only WebKit passed), then escalated
to challenging WebKit after about 70 WebKit page loads across GCP ranges in ~30 minutes. Each page
load fires 25–35 subrequests. The probe did not rotate engines or user agents and did not wait on or
solve any challenge.

## Refusals / not tested

- **me-central2 (Dammam): not tested.** Creating an Artifact Registry repo there was refused with
  `LOCATION_POLICY_VIOLATED` (organisation resource-location policy). It was not worked around.
- **Our server, ulta.ae extra cells: not run**, because of the stop above.
- **Chromium on our server: not tested.** Chromium crashes in this host's Docker ("Page crashed",
  infrastructure, not a site block). It works on Cloud Run.
- `m.ulta.ae` does not resolve (no separate mobile-web host); mobile web = same host with the mobile
  descriptor (WebKit iPhone 14 = 200 at 20:32).
- The Ulta ME app (`com.ub.mena`) is on hold and was not touched. Algolia was not called directly.

## Matrix

Outcome counts per egress × site × client × entry point. `usable` = the page yielded a price.
`skip:after_blocks` = the client was stopped after three consecutive blocks.
`skip:robots_disallowed` never fired. That is **not** because every URL was allowed: the gate failed open (see [Robots gate incident](#robots-gate-incident-fail-open)).

| egress | site | client | entry | outcomes (count) |
|---|---|---|---|---|
| me-central1 | sephora | plain_http | robots | 200 ×1 |
| me-central1 | sephora | plain_http | sitemap_index | 200 ×1 |
| me-central1 | sephora | plain_http | sitemap_category | 200 ×1 |
| me-central1 | sephora | plain_http | home | 200 ×2 |
| me-central1 | sephora | plain_http | alt_domain | 200 ×1 |
| me-central1 | sephora | plain_http | sitemap_product | 200 ×80 |
| me-central1 | sephora | plain_http | pdp | 200 usable ×4 |
| me-central1 | sephora | plain_http | category | 200 ×1 |
| me-central1 | sephora | plain_http | search | 200 ×1 |
| me-central1 | sephora | plain_http | image | 403 cloudflare ×1 |
| me-central1 | ulta | plain_http | robots | 403 cloudflare ×1 |
| me-central1 | ulta | plain_http | sitemap_index | 403 cloudflare ×1 |
| me-central1 | ulta | plain_http | home | 403 cloudflare ×1, skip:after_blocks ×1 |
| me-central1 | ulta | plain_http | listing | skip:after_blocks ×1 |
| me-central1 | ulta | plain_http | search | skip:after_blocks ×1 |
| me-central1 | sephora | chromium-headless-desktop | home | 200 ×1 |
| me-central1 | sephora | chromium-headless-desktop | pdp | 200 usable ×1 |
| me-central1 | sephora | chromium-headless-desktop | category | 200 ×1 |
| me-central1 | sephora | chromium-headless-desktop | search | 200 ×1 |
| me-central1 | ulta | chromium-headless-desktop | home | 403 cloudflare ×1 |
| me-central1 | ulta | chromium-headless-desktop | listing | 403 cloudflare ×1 |
| me-central1 | ulta | chromium-headless-desktop | search | 403 cloudflare ×1 |
| me-central1 | ulta | firefox-headless-desktop | home | 403 cloudflare ×1 |
| me-central1 | sephora | plain_http | stab_pdp | 200 usable ×6 |
| me-central1 | ulta | firefox-headless-desktop | listing | 403 cloudflare ×1 |
| me-central1 | ulta | webkit-headless-desktop | home | 200 usable ×1 |
| me-central1 | ulta | webkit-headless-desktop | listing | 200 usable ×1 |
| me-central1 | ulta | chromium-headed-desktop | home | 403 cloudflare ×1 |
| me-central1 | ulta | chromium-headed-desktop | listing | 403 cloudflare ×1 |
| me-central1 | ulta | firefox-headed-desktop | home | 403 cloudflare ×1 |
| me-central1 | sephora | plain_http | stab_listing | 200 ×2 |
| me-central1 | ulta | firefox-headed-desktop | listing | 403 cloudflare ×1 |
| me-central1 | ulta | chromium-headless-mobile | home | 403 cloudflare ×1 |
| me-central1 | sephora | plain_http | stab_sitemap_product | 200 ×2 |
| me-central1 | ulta | chromium-headless-mobile | listing | 403 cloudflare ×1 |
| me-central1 | ulta | webkit-headless-mobile | home | 200 usable ×2 |
| me-central1 | sephora | plain_http | stab_image | 200 generic ×1 |
| me-central1 | ulta | webkit-headless-mobile | listing | 200 usable ×1 |
| me-central1 | sephora | chromium-headless-desktop | stab_pdp_browser | 200 usable ×1 |
| me-central1 | ulta | webkit-headless-desktop | stab_robots | 200 ×1 |
| me-central1 | ulta | webkit-headless-desktop | stab_sitemap | 200 ×1 |
| me-central1 | ulta | webkit-headless-desktop | stab_pdp | 200 usable ×6 |
| me-central1 | ulta | webkit-headless-desktop | stab_listing | 200 usable ×2 |
| me-central1 | sephora | plain_http | page_param | 200 ×6 |
| me-central1 | sephora | plain_http | cat_total | 200 ×9 |
| me-central1 | sephora | plain_http | search_total | 200 ×1 |
| me-central1 | sephora | plain_http | sample_pdp | 200 usable ×30 |
| asia-south1 | ulta | plain_http | x_robots | 403 cloudflare ×1 |
| asia-south1 | ulta | plain_http | x_sitemap | 403 cloudflare ×1 |
| asia-south1 | ulta | plain_http | x_home | 403 cloudflare ×1 |
| asia-south1 | ulta | chromium-headless-desktop | x_home | 403 cloudflare ×1 |
| asia-south1 | ulta | webkit-headless-desktop | x_home | 200 usable ×1 |
| asia-south1 | ulta | plain_http | x_category | skip:after_blocks ×1 |
| asia-south1 | ulta | chromium-headless-desktop | x_category | 403 cloudflare ×1 |
| asia-south1 | ulta | webkit-headless-desktop | x_category | 403 cloudflare ×1 |
| asia-south1 | ulta | plain_http | x_pdp | skip:after_blocks ×1 |
| asia-south1 | ulta | chromium-headless-desktop | x_pdp | 403 cloudflare ×1 |
| asia-south1 | ulta | webkit-headless-desktop | x_pdp | 403 cloudflare ×1 |
| asia-south1 | ulta | plain_http | x_mobile_host | skip:after_blocks ×1 |
| asia-south1 | ulta | webkit-headless-mobile | x_mobile_host | ERR ×1 |
| asia-south1 | ulta_img | plain_http | x_img_robots | 404 ×1 |
| asia-south1 | ulta_img | plain_http | x_image | 200 ×1 |
| europe-west1 | ulta | plain_http | x_robots | 403 cloudflare ×1 |
| europe-west1 | ulta | plain_http | x_sitemap | 403 cloudflare ×1 |
| europe-west1 | ulta | plain_http | x_home | 403 cloudflare ×1 |
| europe-west1 | ulta | chromium-headless-desktop | x_home | 403 cloudflare ×1 |
| europe-west1 | ulta | webkit-headless-desktop | x_home | 403 cloudflare ×1 |
| europe-west1 | ulta | plain_http | x_category | skip:after_blocks ×1 |
| europe-west1 | ulta | chromium-headless-desktop | x_category | 403 cloudflare ×1 |
| europe-west1 | ulta | webkit-headless-desktop | x_category | 200 usable ×1 |
| europe-west1 | ulta | plain_http | x_pdp | skip:after_blocks ×1 |
| europe-west1 | ulta | chromium-headless-desktop | x_pdp | 403 cloudflare ×1 |
| europe-west1 | ulta | webkit-headless-desktop | x_pdp | 200 usable ×1 |
| europe-west1 | ulta | plain_http | x_mobile_host | skip:after_blocks ×1 |
| europe-west1 | ulta | webkit-headless-mobile | x_mobile_host | ERR ×1 |
| europe-west1 | ulta_img | plain_http | x_img_robots | 404 ×1 |
| europe-west1 | ulta_img | plain_http | x_image | 200 ×1 |
| me-central1 | ulta | plain_http | x_robots | 403 cloudflare ×1 |
| me-central1 | ulta | webkit-headed-desktop | x_home | 403 cloudflare ×1 |
| me-central1 | ulta | webkit-headed-desktop | x_category | 403 cloudflare ×1 |
| me-central1 | ulta | webkit-headed-desktop | x_pdp | 403 cloudflare ×1 |
| me-central1 | ulta_kw | plain_http | kw_robots | 403 cloudflare ×1 |
| me-central1 | ulta_kw | plain_http | kw_sitemap | 403 cloudflare ×1 |
| me-central1 | ulta_kw | plain_http | kw_home | 403 cloudflare ×1 |
| me-central1 | ulta_kw | webkit-headless-desktop | kw_home | 403 cloudflare ×1 |
| me-central1 | ulta_kw | plain_http | kw_listing | skip:after_blocks ×1 |
| me-central1 | ulta_kw | webkit-headless-desktop | kw_listing | 403 cloudflare ×1 |
| me-central1 | ulta_kw | plain_http | kw_pdp | skip:after_blocks ×1 |
| me-central1 | ulta_kw | webkit-headless-desktop | kw_pdp | 403 cloudflare ×1 |
| our-server | ulta | webkit-headless-desktop | stab_robots | 200 ×1 |
| our-server | sephora | plain_http | stab_pdp | 403 akamai ×3, skip:after_blocks ×3 |
| our-server | ulta | webkit-headless-desktop | stab_sitemap | 200 ×1 |
| our-server | ulta | webkit-headless-desktop | stab_pdp | 200 usable ×6 |
| our-server | ulta | webkit-headless-desktop | stab_listing | 200 usable ×1, 429 cloudflare ×1 |
| our-server | sephora | plain_http | stab_listing | skip:after_blocks ×2 |
| our-server | sephora | plain_http | stab_sitemap_product | skip:after_blocks ×2 |
| our-server | sephora | plain_http | stab_image | skip:after_blocks ×1 |
| our-server | sephora | firefox-headless-desktop | stab_pdp_browser | 200 usable ×1 |

## Robots gate incident (fail-open)

`run.py` loaded a host's rules only after a 200 robots.txt and let every URL through while no
rules were loaded. httpx got a Cloudflare 403 on ulta.ae/ulta.com.kw robots.txt, so each run
requested the ulta.* URLs below before a usable robots.txt was parsed (or never had one). Rules
are per process, so each run starts ungated. The "disallowed" column is judged against the ulta.ae
robots.txt the probe fetched (`samples/probe/ulta_ae_robots.txt`). It is used for ulta.com.kw
too, whose robots.txt was never readable (403). **44 URLs were requested ungated; 1 is
disallowed** (the search URL), and it got a Cloudflare 403. `HTTP None` = transport error (e.g.
m.ulta.ae does not resolve).

Fix (this PR): `analysis.robots_gate` fails closed. For any non-Sephora host, a URL is requested
only if robots.txt was parsed and allows it, or robots.txt answered 404/410. Not fetched,
401/403/429/5xx, a challenge page or an error means refuse everything except `/robots.txt`. A 200
challenge page is no longer parsed as robots.txt. Tested in `test_robots_gate_fails_closed`.
The incident is recorded in the decision log (#17).

| UTC | run | client | HTTP | disallowed by ulta.ae robots.txt | URL |
|---|---|---|---|---|---|
| 2026-09-30T20:27:11 | stage1-me-central1-20260930T202453Z | plain_http | 403 | no | https://www.ulta.ae/sitemap.xml |
| 2026-09-30T20:27:13 | stage1-me-central1-20260930T202453Z | plain_http | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:27:57 | stage1-me-central1-20260930T202453Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:27:59 | stage1-me-central1-20260930T202453Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/makeup |
| 2026-09-30T20:28:00 | stage1-me-central1-20260930T202453Z | chromium-headless-desktop | 403 | yes | https://www.ulta.ae/en/search?keywords=lipstick |
| 2026-09-30T20:32:47 | stage2-me-central1-20260930T203224Z | firefox-headless-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:32:51 | stage2-me-central1-20260930T203224Z | firefox-headless-desktop | 403 | no | https://www.ulta.ae/en/makeup |
| 2026-09-30T20:33:15 | stage2-me-central1-20260930T203224Z | webkit-headless-desktop | 200 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:33:34 | stage2-me-central1-20260930T203224Z | webkit-headless-desktop | 200 | no | https://www.ulta.ae/en/makeup |
| 2026-09-30T20:33:40 | stage2-me-central1-20260930T203224Z | chromium-headed-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:33:44 | stage2-me-central1-20260930T203224Z | chromium-headed-desktop | 403 | no | https://www.ulta.ae/en/makeup |
| 2026-09-30T20:33:49 | stage2-me-central1-20260930T203224Z | firefox-headed-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:33:57 | stage2-me-central1-20260930T203224Z | firefox-headed-desktop | 403 | no | https://www.ulta.ae/en/makeup |
| 2026-09-30T20:34:06 | stage2-me-central1-20260930T203224Z | chromium-headless-mobile | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:34:08 | stage2-me-central1-20260930T203224Z | chromium-headless-mobile | 403 | no | https://www.ulta.ae/en/makeup |
| 2026-09-30T20:34:29 | stage2-me-central1-20260930T203224Z | webkit-headless-mobile | 200 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:34:50 | stage2-me-central1-20260930T203224Z | webkit-headless-mobile | 200 | no | https://www.ulta.ae/en/makeup |
| 2026-09-30T20:35:21 | stage2-me-central1-20260930T203224Z | webkit-headless-mobile | 200 | no | https://www.ulta.ae/ar/ |
| 2026-09-30T20:56:21 | stagex-me-central1-20260930T205558Z | webkit-headed-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:56:27 | stagex-me-central1-20260930T205558Z | webkit-headed-desktop | 403 | no | https://www.ulta.ae/en/shop-makeup-nails |
| 2026-09-30T20:56:35 | stagex-me-central1-20260930T205558Z | webkit-headed-desktop | 403 | no | https://www.ulta.ae/en/buy-signature-lip-pencil |
| 2026-09-30T20:56:43 | stagex-me-central1-20260930T205558Z | plain_http | 403 | no | https://www.ulta.com.kw/sitemap.xml |
| 2026-09-30T20:56:49 | stagex-me-central1-20260930T205558Z | plain_http | 403 | no | https://www.ulta.com.kw/en/ |
| 2026-09-30T20:56:52 | stagex-asia-south1-20260930T205629Z | plain_http | 403 | no | https://www.ulta.ae/sitemap.xml |
| 2026-09-30T20:56:56 | stagex-me-central1-20260930T205558Z | webkit-headless-desktop | 403 | no | https://www.ulta.com.kw/en/ |
| 2026-09-30T20:56:57 | stagex-asia-south1-20260930T205629Z | plain_http | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:57:01 | stagex-me-central1-20260930T205558Z | webkit-headless-desktop | 403 | no | https://www.ulta.com.kw/en/shop-makeup-nails |
| 2026-09-30T20:57:04 | stagex-asia-south1-20260930T205629Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:57:08 | stagex-me-central1-20260930T205558Z | webkit-headless-desktop | 403 | no | https://www.ulta.com.kw/en/buy-signature-lip-pencil |
| 2026-09-30T20:57:33 | stagex-europe-west1-20260930T205712Z | plain_http | 403 | no | https://www.ulta.ae/sitemap.xml |
| 2026-09-30T20:57:38 | stagex-europe-west1-20260930T205712Z | plain_http | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:57:45 | stagex-europe-west1-20260930T205712Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:57:54 | stagex-europe-west1-20260930T205712Z | webkit-headless-desktop | 403 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:58:00 | stagex-europe-west1-20260930T205712Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/shop-makeup-nails |
| 2026-09-30T20:58:07 | stagex-asia-south1-20260930T205629Z | webkit-headless-desktop | 200 | no | https://www.ulta.ae/en/ |
| 2026-09-30T20:58:09 | stagex-asia-south1-20260930T205629Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/shop-makeup-nails |
| 2026-09-30T20:58:19 | stagex-asia-south1-20260930T205629Z | webkit-headless-desktop | 403 | no | https://www.ulta.ae/en/shop-makeup-nails |
| 2026-09-30T20:58:20 | stagex-asia-south1-20260930T205629Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/buy-signature-lip-pencil |
| 2026-09-30T20:58:24 | stagex-europe-west1-20260930T205712Z | webkit-headless-desktop | 200 | no | https://www.ulta.ae/en/shop-makeup-nails |
| 2026-09-30T20:58:25 | stagex-europe-west1-20260930T205712Z | chromium-headless-desktop | 403 | no | https://www.ulta.ae/en/buy-signature-lip-pencil |
| 2026-09-30T20:58:29 | stagex-asia-south1-20260930T205629Z | webkit-headless-desktop | 403 | no | https://www.ulta.ae/en/buy-signature-lip-pencil |
| 2026-09-30T20:58:32 | stagex-asia-south1-20260930T205629Z | webkit-headless-mobile | None | no | https://m.ulta.ae/ |
| 2026-09-30T20:58:55 | stagex-europe-west1-20260930T205712Z | webkit-headless-desktop | 200 | no | https://www.ulta.ae/en/buy-signature-lip-pencil |
| 2026-09-30T20:58:56 | stagex-europe-west1-20260930T205712Z | webkit-headless-mobile | None | no | https://m.ulta.ae/ |

## Where the data lives

### sephora.me (Next.js RSC + tRPC on SFCC)

- **PDP** `/{locale}/p/{slug}/{P-id}` (or a numeric variant id). JSON-LD gives name, brand, image,
  description, price, currency (AED), availability and rating. It has **no** sku or GTIN.
  - The RSC payload (`self.__next_f`) holds `productDetails`: `id` (P-id = the stable
    `source_listing_key`), `name`, `c_brand{id,name}`, `images`, and **`c_variantsInfo[]`**, one
    entry per shade/size with `product_id` (variant id), `c_variation_attribute_name` (shade or size
    label), price fields and `swatchImage`. See fixture `sephora_rsc_variants.json`.
  - No EAN/GTIN was seen in the RSC or tRPC payloads.
- **Stock**: the page makes a tRPC call,
  `/api/trpc/…products.getProductAvailability?batch=1&input={"json":{"locale":"en-AE","productId":…}}`.
  It returns per-variant `inStock`, `isLowStock`, `globalStock`, and `warehouseStock`/`storesStock`
  with `stockLevel`. It is not robots-disallowed and is in scope at polite pacing.
- **Listings** `/{locale}/shop/{path}/{CID}`: the RSC `productResponse{limit, offset, total}` plus
  `products[]` (productId, productName, c_brand, c_price, c_variantsCount, representedProduct,
  hitType=master). See fixture `sephora_search_listing.json`. Pagination is **client-side only**:
  `?page=`, `?start=` and `?offset=` are ignored by the server render (offset stays 0).
- **Images**: `img-product.sephora.me` (200, 406 KB JPEG) and `img-content.sephora.me`. The legacy
  SFCC host `bkwk-prd.my.commercecloud.salesforce.com` returns Cloudflare 403, so don't use it.
- **Egress**: me-central1 works with plain httpx. Our server's IP gets Akamai 403 (`AkamaiGHost`,
  "Access Denied"). This is recorded and not worked around.

### ulta.ae (Alshaya, Adobe Edge Delivery + Adobe Commerce)

- **PDP** `/{en|ar}/buy-{slug}`: JSON-LD includes name, brand, **sku**, description, price, currency,
  availability and rating.
- The page makes first-party calls: `www.ulta.ae/graphql?query=…ProductQuery…`, which returns
  price, original price, `inStock`, images and variants (fixture `ulta_ae_graphql_product.json`),
  plus `/en/query-index.json`, `/en/global-query-index.json` and `/promotion-schedule.json`.
- **robots.txt disallows every query-string URL** (`Disallow: /*?`, `*/?*`). Exceptions:
  `Allow: /*.json?`, `/*media_*?` and `/*?selected*`. Also disallowed: `*/fragments/`, `*/tools/`,
  `*/cart/`, `*/user/`, `*/footer`, `*/header`. Consequences:
  - The GraphQL GET (query string) must **not** be replayed as a crawl target. It may only be read
    as a response the page itself makes inside the browser session.
  - `/en/search?keywords=` is disallowed.
  - Listing pagination via query URLs is disallowed.
  - `*.json?` index files are allowed.
- **Images**: `media.alshaya.com/adobe/assets/urn:aaid:aem:…/as/{SKU}_{n}.jpg?width=…` gives 200 on
  plain httpx from europe-west1 and asia-south1. Its robots.txt is 404, which means allow-all
  (RFC 9309).
- Pacing: ≥5 s per page. A 429 or challenge means backoff and `not_observed`, never
  OUT_OF_STOCK/REMOVED.

## Sephora UAE catalogue verification (owner request)

Live, from me-central1 with plain httpx at ~1 req/s, 20:45 UTC; 46 requests. The owner chat's count
was 7,903 P-ids / 8,744 variant pages (ae-en); mine was the union of both locale sitemap sets.

| Measure | Sitemap | Live | Method |
|---|---|---|---|
| Products (masters) | 8,299 P-ids ae-en (union of en-AE + ar-AE sitemap sets); 8,300 ae-ar | Makeup 2,839 · Fragrance 2,061 · Skincare 2,607 · Bath & Body 807 · Hair 1,146 = **9,460** (with cross-listing overlap; Gifts 765 and Men 6 overlap; Accessories C305 = 0). The ae-ar Makeup total is identical (2,839). Page 1 of every listing: 212/214 distinct products are in the sitemap (the 2 missing are brand-new items). | `productResponse.total` in the listing RSC. De-dup by id wasn't possible (client-side pagination). |
| "All products" | n/a | Empty search `?q=` → **17,076** | Counts **variant-level hits**: page 1 repeats the same master with different `representedProduct` ids. It matches the sitemap's ~17.05–17.09k product + variant URLs, so it is not a product count. |
| Variants / SKUs | 8,746 variant pages (union); owner-chat estimate ≈12.8k SKUs | Seeded sample of 30 P-ids (`random.Random(20260930)` over the sorted ae-en P-id set): 59 live variants = 1.97/product → **≈16.3k SKUs (bootstrap 95% CI 11.6k–21.9k)** | Length of `c_variantsInfo` on each PDP. |
| Sitemap vs live | n/a | Only **17/59 (29%)** live variants have their own sitemap variant page. 17/30 products have at least one variant with no variant page (e.g. Bleu de Chanel Parfum 50/100/150 ml: 0 variant pages; Lustreglass Lip Tint: 8 shades, 0 pages). 2/30 products list stale variant ids the PDP no longer offers. | Per-slug diff of sitemap numeric-variant URLs vs `c_variantsInfo` ids. |

Conclusions:

1. **170k → ~8.3k products is real.** The 170k figure is 10 GCC country/language prefixes ×
   ~17k URLs, repeated in both the en-AE and ar-AE sitemap sets. The live category totals are
   consistent with ~8–9k UAE products (categories overlap).
2. **The sitemap misses shades and sizes.** The crawl must expand variants from each PDP's
   `c_variantsInfo` and not rely on sitemap variant URLs. The SKU count is likely ~16k.
3. **"ar has more P-ids than en" is a sitemap-generation artefact.** Each locale sitemap set has
   duplicates and gaps (the en-AE set alone has 811 duplicate entries and gives 8,002 ae-en P-ids;
   the ar-AE set gives 8,299). The union across both sets is ae-en 8,299 vs ae-ar 8,300 (1 ar-only
   P-id, 0 en-only). **Seed the crawl with the union of both sets.**

## Fixtures (`docs/recon/samples/probe/`, redacted, no cookies or headers)

| File | What |
|---|---|
| `sephora_pdp_trimmed.html` | Sephora PDP, title + JSON-LD only |
| `sephora_rsc_variants.json` | `productDetails.id` + first 3 `c_variantsInfo` entries |
| `sephora_search_listing.json` | `productResponse` + 2 listing hits |
| `sephora_akamai_403_our_server.html` | Akamai 403 served to our server's IP |
| `ulta_ae_pdp_trimmed.html` | ulta.ae PDP, title + JSON-LD |
| `ulta_ae_graphql_product.json` | Page-made GraphQL ProductQuery response (first 20 kB) |
| `ulta_ae_cf_challenge_webkit_head.html` | Cloudflare managed challenge served to WebKit (403) |
| `ulta_ae_cf_429_head.html` | Cloudflare challenge served with status 429 (Arabic page) |
| `ulta_com_kw_cf_block_head.html` | Cloudflare "Attention Required" block, ulta.com.kw |

## Cost and cleanup

- Cloud Run: 8 job executions, **1,043 s** total at 2 vCPU / 2 GiB = 2,086 vCPU-s + 2,086 GiB-s.
  At the higher (tier-2, me-central1) list rates that is about **$0.08**. It falls within the
  monthly Cloud Run free tier (180k vCPU-s), so the **expected billed amount is $0.00**.
- Artifact Registry: the ~1.5 GB image existed for under a day in 3 regions (< $0.01).
  Pushes were ingress (free).
- GCS: a few MB for under a day (< $0.01). Egress to the internet: a few MB (< $0.01).
- **Total ≈ $0.10 at list price, expected $0 billed. Cap was $1.00.**
- Requests: **232 top-level fetches** to target sites (sephora 159, ulta.ae 63, ulta.com.kw 6,
  media.alshaya.com 4). A browser page load also fires the page's own subresource requests.
- Deleted: the Cloud Run jobs in me-central1, europe-west1 and asia-south1; Artifact Registry repos
  `pi-probe` in the same three regions (images v1–v4); the bucket `gs://pi-probe-8208be84`; and
  the service account `pi-probe-runner` (its only role was objectCreator on that bucket). Local
  images and docker credentials were deleted too.
- Left enabled on purpose: the `run`, `artifactregistry` and `iam` APIs. `iam` had to be enabled to
  create the dedicated service account. Enabling APIs is free.
