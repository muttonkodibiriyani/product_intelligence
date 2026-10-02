# Runbook: onboard a new site (any brand, retailer, vertical or country)

This is the order of work for adding a source under ADR-0007. The access rules come from
ADR-0003, ADR-0005 and ADR-0006 and are unchanged. If any step below seems to need more than they
allow, **stop and ask the coordinator**; the owner decides.

> Some tooling named here lands in ADR-0007 follow-up PRs: the register loader,
> `make new-connector`, the contract suite and dataset contract v2. Until then, do the same step by
> hand, following the existing connectors (`packages/pi_connector_ulta`) and the Sephora and Ulta
> recon docs. Each step says what to do in the meantime.

## Stop rules (apply at every step)
- **Challenge:** stop at the **first** challenge (a Cloudflare "Just a moment…" page, an Akamai,
  PerimeterX or DataDome interstitial, a CAPTCHA) and at any 401/403. Do not solve it, retry it,
  or switch engine, user agent or egress. The source is marked `blocked` and reported.
- **429:** a plain 429 backs off per host; two in a row stop the run.
- **robots.txt:** it is obeyed, and a file that can't be read refuses the whole host (fail-closed
  matrix, ADR-0006). A robots deviation needs an owner decision **for that one site**.
- **Forbidden always:**
  - rung 3 and stealth;
  - TLS/JA3/HTTP2 impersonation;
  - logins, cookie reuse or WAF-cookie replay;
  - cart and checkout;
  - third-party search APIs that the site's own page does not load.
- **Proxy:** never, unless all of these hold:
  - the owner has approved and bought it **for this site**;
  - an ADR amendment exists;
  - the source has been added to `PROXY_SOURCES` and `APPROVED_DEVIATIONS` in a reviewed PR.

  The same applies to a robots `tag_only` deviation (`APPROVED_DEVIATIONS` only). A YAML edit never
  approves anything.
- **Images:** image fetches follow the same rules. The image host's own robots.txt is checked (with
  the same fail-closed matrix), images have their own per-host pacing, and the stop rules above
  apply. Images are always fetched direct, never through a proxy.
- **Classifier refusal:** if a safety classifier or permission guard refuses a step, report it.
  Never route around it.
- **Secrets:** no secrets in git, fixtures, logs or messages. Keys found in page config are written
  as `REDACTED`.

## 0. Intake (coordinator and owner)
Write down, in the onboarding task:
- **What is compared:** which comparison this serves, for example "brand X vs brand Y in country Z,
  delivery channel", or "retailers A, B and C for category Q".
- **The site:** site, country, currency, locales, and vertical (`beauty`, `food_menu`, `apparel`,
  or a new one, which needs its own `VerticalProfile` first).
- **Food only:** which branches or delivery zones, and which channels (delivery, pickup, dine-in
  with evidence).
- **New country:** any legal or consumer-data constraint, recorded as an owner decision before any
  collection.

## 1. Register the source
Create `config/sources/<source_key>.yaml` (ADR-0007 §2) with the strictest defaults:

```yaml
source_key: <site>_<country>         # e.g. brandx_kw
vertical: food_menu
contexts: [{country: KW, currency: KWD, time_zone: Asia/Kuwait, locales: [en-KW, ar-KW], channel: delivery}]
access: {rung_max_allowed: 2, robots_mode: obey, proxy: null, page_interval_s: 1.0}
cadence: on_demand
approvals: []
```

- Leave `browser` unset until recon (step 2) shows which stock engine the site serves normally. The
  engine is then pinned by an owner or coordinator decision.
- *Until the loader lands:* put the same facts in the recon doc header. The `FetchPolicy` mappings
  are set in the connector's run tool.

## 2. Recon (read-only, polite, documented)
Write `docs/recon/<source_key>.md`. The rules:
1. **robots.txt first**, fetched once and recorded (status, and the rules that matter). Plan only
   allowed paths.
2. **Rung 0:** the site's own data:
   - sitemaps and category trees;
   - JSON-LD (`Product`, `Offer`, `Menu`, `MenuItem`);
   - embedded state (`__NEXT_DATA__` and similar);
   - JSON the page itself loads.

   Record the data shape: where price, stock, variants, size or portion, images, and (for food)
   branches and channels come from.
3. **Rung 1:** plain `httpx`, normal headers, at ≤1 req/s with jitter. A handful of URLs only.
4. **Rung 2:** a stock Playwright engine, no stealth, with a fresh context. Only if rung 1 doesn't
   serve the data.
5. **Rung 4:** another egress, such as Cloud Run in the country's region, as a separately approved
   probe with a budget line. Only if rungs 0, 1 and 2 are blocked.
6. **Blocked after rungs 0, 1, 2 and 4:** stop. Mark the source `blocked`, and write a **Proxy
   Decision Report** covering:
   - the attempts made;
   - the evidence;
   - an estimate of pages and GB;
   - the cost line below.

   Send it to the coordinator. Nothing escalates on its own.
7. **Expected totals:** note the site's own totals (product count per category, or menu item count
   per branch) so step 5 can reconcile against them.

Tests and fixtures never make live requests. Recon is the only live step before the snapshot, and
it stays small.

## 3. Build the connector from the template
```bash
make new-connector SOURCE=<source_key> VERTICAL=<vertical>   # after the ADR-0007 template PR
```
- Implement the three methods. `discover` is rung 0 only. `requests_for` does no I/O. `parse` is
  pure.
- Emit vertical attributes that validate against the vertical's profile, for example
  `food_menu@1`.
- Map partial or blocked data to `not_observed`/`blocked`, **never** `out_of_stock`/`removed`.
  Record `field_gaps` for anything not published.
- *Until the template lands:* copy the shape of `packages/pi_connector_ulta`: the connector,
  tests, fixtures and README, plus its workspace, mypy and coverage entries.

## 4. Fixtures
- Record a small, representative set from the recon: a normal product or item, one with variants,
  one on promotion, one out of stock (only where the site shows it explicitly), and a blocked or
  challenge page for the negative path.
- Strip all cookies and `Set-Cookie`, auth and tracking headers. Replace keys and tokens with
  `REDACTED`.
- Run the contract suite and gitleaks:

  ```bash
  make check
  # the same pinned image and config as CI
  docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.30.1 \
    detect --source /repo --config /repo/.gitleaks.toml --redact --no-banner --exit-code 1
  ```

  In a `git worktree`, the container can't follow the `.git` file and reports "scanned ~0
  bytes". Add `--no-git` there, and treat a 0-byte scan as a failed scan, not a pass.

- Open the connector PR and get the Reviewer's approval. The coordinator merges.

## 5. On-demand snapshot
1. **Trial run (~20 pages)** first, in the site's off-peak window, at the pinned engine and
   interval. Check the run manifest:
   - blocks (must be zero);
   - parse failures;
   - bytes per page;
   - elapsed time.

   Any challenge means the source stays blocked; stop.
2. **Full snapshot:** exactly **one**, and only if the trial is clean and the coordinator says go.
   Cadence is on demand; there is no schedule.
3. **Reconcile** the counts against the site's own totals from step 2.7. Write the gaps into the
   recon doc.

## 6. Load
- Load into `pi_db` through the pipeline: drafts go through `to_canonical`, then the quality gate.
  Quarantined rows stay visible; nothing is dropped silently.
- Evidence (the raw payload) is stored write-once. Observations are insert-only.
- A **bounded batch** (the ~20-page trial, a `MAX_PAGES` run, a run stopped by a block or the byte
  cap, or one category) is loaded as **partial**. The crawl run status and the context's
  `coverage_status` are `partial`. Listings the batch did not reach stay `not_observed`, never
  `removed` or `out_of_stock`. Only a complete, reconciled snapshot may set `supported`.

## 7. Match
- Run `pi_match` for each source pair in the market (ADR-0007 §5), with the vertical's rules.
- A new vertical has auto-accept **off** until its gold set exists. Everything goes to the review
  queue.
- For food, cross-brand pairs are `substitute` and need a human decision.

## 8. Publish
- Update the coverage register for this source: status, gaps, blocked contexts and the rung used.
- Publish the dataset in the v2 contract to `datasets/<market>/<scope>/`. *Until PR-B/PR-C:* use
  the current `demo_export`, which only knows the pilot pair; the new site waits for v2.
- Add or extend the `ComparisonSet` that the intake (step 0) asked for.
- Record the run's actual cost in the manifest and the decision log.

## Cost estimate line (fill in per site, before step 5)
Put this line in the recon doc and in any Proxy Decision Report. Use measured numbers from the
trial run where you have them.

```
Cost (<source_key>): pages≈<P> (items × variants × locales × contexts)
  direct:  Cloud Run ≈ <P × s/page> vCPU-s + egress ≈ $<X> (GCP price list on the day; images direct)
  proxied: GB ≈ <P> × <avg MB/page, assets blocked> / 1000 ≈ <G> GB × $<rate>/GB ≈ $<Y>
           (only if approved for this site; hard byte cap = <cap> GB enforced in pi_fetch)
```

An illustration, not a quote: 4,000 pages × 0.25 MB per page = 1.0 GB, which at $6.25/GB (the
IPRoyal plan the owner bought for ulta.ae) is about $6.25 proxied. Use the trial run's
`proxy_page_bytes` mean instead of guesses. Food adds a factor for branches × channels. Image bytes
are never counted as proxied, because images are always fetched direct.

## Checklist
- [ ] Intake recorded (comparison, country, vertical, channels/branches)
- [ ] Register entry at strictest defaults; approvals listed as decision refs only
- [ ] Recon doc: robots, rung results, data shape, expected totals, cost line
- [ ] Stopped at the first challenge if any; Proxy Decision Report if blocked
- [ ] Connector from template; contract suite and `make check` green; gitleaks clean
- [ ] Trial run clean → one full snapshot on the coordinator's go
- [ ] Loaded, quality-gated, matched (review queue for a new vertical)
- [ ] Coverage and dataset published; cost recorded
