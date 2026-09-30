# Decision log

This log records routine program decisions. The coordinator decides these under the owner's
delegation of 2026-10-01; architecture-level decisions go in `docs/adr/`. Newest entries are
at the top.

| Date | Decision | Why | By |
|---|---|---|---|
| 2026-10-01 | The owner delegated routine technical, scope and sequencing calls to the coordinator. Questions are sent with a recommendation; after 5 min the owner chat decides. Cloud spend is allowed within $25/month. Guardrails and irreversible actions are not delegated. | Keep the program moving | Owner |
| 2026-10-01 | Ulta ME app (com.ub.mena) endpoint study started as task 01a0f40c, observe-only (no pinning bypass or hooking, guest only), assigned to Crawl Engineer B. | Owner "app: go" | Owner / Coordinator |
| 2026-10-01 | Algolia route for ulta.ae: A primary, B approved as a fallback. Recorded as `site_api` (rung 0), with no new enum value. There are 5 review gates (key redaction, provenance, mechanical guardrail, read-only allowlist, per-host pacing). | Owner decision; see ADR-0006 Amendment 1 | Owner / Coordinator |
| 2026-10-01 | Stock WebKit is accepted for ulta.ae, where Chromium and Firefox get a Cloudflare 403. The engine is pinned per source, there is no automatic engine fallback, and the engine is recorded in evidence. If it gets challenged, stop. | Within the owner's approved client list and ADR-0006 | Coordinator |
| 2026-10-01 | pi_fetch interface v0.2: connectors emit source-keyed drafts. `to_canonical(draft, source_id, evidence_id, source_listing_id, ingested_at, ctx)` fully validates the result. Ids read from `CollectionContext` are allowed on drafts. | Connectors can't know DB ids and must not fabricate them | Coordinator |
| 2026-10-01 | pi_fetch is implemented by the Deep Coder; the Crawl Engineer remains design owner. Only #9 edits `pi_core` (shared ListingFields/OfferFields base). | The Crawl Engineer is busy with the probe; avoid two writers on `pi_core` | Coordinator |
| 2026-09-30 | Availability contract v2: out_of_stock, removed and not_deliverable require `field_state.availability_state = observed`. `FieldState.OBSERVED` is a qualifier only, never a reason for a null value. | No false stock-outs or removals | Coordinator |
| 2026-09-30 | Price and stock contract for pi_core and pi_db (see pi_core/docs/models.md). Price ranges use `price_range_min`/`price_range_max`; `price_current` is NULL for range and quote_only. `low_stock` is true exactly when the flag is TRUE. Evidence records the rung and method as NOT NULL, and rung 3 is rejected. | One contract for both the models and the schema | Coordinator |
| 2026-09-30 | Gulf probe run as a staged matrix from Cloud Run me-central1, with a least-privilege service account and full cleanup, under $1. | Owner "go deep" | Owner / Coordinator |
