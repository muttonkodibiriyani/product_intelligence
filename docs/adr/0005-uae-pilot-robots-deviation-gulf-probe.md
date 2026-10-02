# ADR-0005: UAE-only pilot, Sephora robots deviation, Gulf-egress probe

- Status: accepted (owner decisions, 30 Sep 2026, relayed by the program coordinator)
- Date: 2026-09-30
- Supersedes: ADR-0004 for the pilot scope (KSA dropped for now)
- Requirement IDs: SCP-02, SCP-08, SCP-11 (decision log), SRC-01, SRC-08, SRC-14 (deferred)

## Context
Recon (`docs/recon/sephora_me.md`, `docs/recon/ulta_me.md`) found that Ulta ME has no KSA
storefront, so a KSA Ulta ↔ Sephora comparison is impossible online. Sephora ME's richest
structured sources (the `/{locale}/api/v1` BFF, listing paging, `Product-Variation`, Bazaarvoice
review routes and the SFCC image path) are disallowed in `www.sephora.me/robots.txt`. From our
Indian datacenter egress, both sites block page routes (Sephora: Akamai 403; Ulta UAE: Cloudflare
WAF 403). The ladder probe had not been run.

## Decisions
1. **Pilot scope = UAE only.** Ulta UAE (`ulta.ae`) vs Sephora UAE (`sephora.me` `ae-en` / `ae-ar`),
   EN + AR. KSA is dropped for now and shown as out of pilot scope on the coverage register
   (SCP-02/SCP-08), not as blocked.
2. **Robots deviation for Sephora ME (SRC-01, SRC-08).** The owner approves collection from Sephora's
   robots-disallowed paths, including the `/{locale}/api/v1` BFF, at polite pacing: ~1 req/s with
   jitter, run off-peak (UAE night). This is a deviation from SRC-08 and is recorded in the
   traceability matrix next to the ADR-0003 deviation. It does **not** cover login, cart,
   checkout or account routes, and it does not approve any specific bot-protection technique.
   The ADR-0003 ladder applies unchanged, and each escalation is audit-logged.
3. **Gulf-egress probe approved.** One Cloud Run job in `me-central1` and/or `me-central2`
   against `sephora.me` (`ae-en`, `ae-ar`) and `ulta.ae`. Budget **< $1** (cost line in
   `docs/recon/sephora_me.md` §8.1). It starts with a normal browser User-Agent and ordinary
   requests, and records exactly what works from Gulf egress. It is built as a separate task
   after this recon PR merges.
4. **Own collection only (owner direction, 30 Sep).** The pilot must prove that our own platform
   collects the data with no vendor and no Alshaya help: no Alshaya contact, export or allowlisting.
   The PR7 offline import (SRC-14) is a later option only and is out of the full-crawl scope for now.
   The order is: probe → full crawl if access works. If a site still blocks ordinary Gulf-egress
   traffic, a per-site Proxy Decision Report goes to the owner, covering a UAE residential proxy for
   product-data calls only, with images fetched direct. The owner decides and buys. Agents purchase
   nothing and sign up for nothing.

## Consequences
- Sephora PR6 may prefer BFF JSON over HTML. Pacing and off-peak scheduling are part of the
  connector contract, and robots-disallowed fetches are tagged as such in the audit log.
- Any recurring GCP runtime beyond the one-off probe still needs owner approval with a monthly
  cost line (blueprint §13).
- Ulta's Algolia (if found) is not covered by decision 2, which is Sephora-specific. Using it needs
  its own owner decision.
