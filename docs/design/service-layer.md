# Design: backend service layer (read API)

| | |
|---|---|
| Status | Proposed (design PR; implementation follows in the PRs listed in §12) |
| Owner | Deep Coder |
| Task | 01a0f488-eab6 |
| Consumers | Web app (FE), exports, AI assistant tools (`docs/design/ai-assistant.md`, #32) |
| Decisions it builds on | ADR-0002 (Firebase + Postgres), ADR-0007 (markets as data, dataset contract v2, scopes), the coordinator's metric ruling (below) |
| Deploys | Infra |

## 1. What and why

One **read API** is the single source of product and metric numbers for the web app, the exports
and the AI assistant. Today the dashboard and the assistant would each read `pi.dataset/v1` and
compute gaps and indexes themselves, so the same question could get two different answers.

**Coordinator ruling (binding):** the service layer computes every metric: price index and gaps,
promotions, assortment, availability and coverage. It uses Decimal money, counts only reviewed
pairs (§7.2), applies the n ≥ 5 rule, and returns explicit `not_enough_data` states (such as
`retailer_partial`). Everything else is a thin client:
- the dashboard;
- exports;
- the assistant's tools, which forward the user's ID token and map 1:1 onto endpoints.

There is **no metric code in TS**, not even a mirror. There is one implementation, in Python, tested
once.

**Out of scope:**
- writes. Review-queue actions, alerts, reports and admin changes come later, through separate
  audited endpoints;
- free-form queries. There is no SQL, no query strings and no arbitrary projection;
- live collection. The API never fetches from retailer sites.

## 2. Shape of the system

```mermaid
flowchart LR
  PUB["publish (demo_export → publish_dataset, later the pipeline)"] --> GCS[("GCS datasets/&lt;market&gt;/&lt;scope&gt;/<br/>pi.dataset/v2 + fact extracts")]
  GCS -->|generation check, 60 s| API["pi_api on Cloud Run (me-central1)<br/>FastAPI · pi_metrics · SnapshotSource"]
  WEB[Web app] -->|Firebase ID token| API
  AST["Assistant tools (Genkit)"] -->|user's ID token, forwarded| API
  EXP[Exports] --> API
  API -. later, owner approval .-> PG[("Cloud SQL / pi_db<br/>PgSource, read-only role + RLS")]
```

The code is split into packages. Each package depends only on the one before it:

| Package | Contents | I/O |
|---|---|---|
| `pi_core` (exists) | Money, currencies, markets, enums, listing and offer models | none |
| `pi_dataset` (PR-B) | pydantic models for `pi.dataset/v2`, the JSON Schema in `docs/contracts/`, a validator library, and a v1 → v2 read adapter | none |
| `pi_metrics` (new) | Pure metric functions over a loaded dataset: gaps, index, promotions, assortment, availability, coverage, and the cohort and absence rules | none |
| `pi_api` (new) | FastAPI app, auth, `DataSource` implementations, routers, the OpenAPI export | GCS, Firebase certs |

`pi_metrics` has no web or cloud imports, so the same numbers can be produced by a CLI, a notebook
or a batch export without the server.

## 3. Data path (v1: snapshots, no Cloud SQL)

Per the coordinator's direction, **Cloud SQL is not used now**. The API serves published,
versioned snapshots.

- **Source of truth for the API:**
  - `gs://<bucket>/datasets/<market>/<scope>/latest.json.gz` (`pi.dataset/v2`, ADR-0007 §6);
  - the immutable dated copies next to it;
  - optional fact extracts (`facts/observations.jsonl.gz` or Parquet) when the history outgrows
    one JSON document.

  The layout is the one ADR-0007 §6 fixes, so the §7 scope rules stay path-based.
- **Loading.** At cold start, `SnapshotSource`:
  1. lists the scopes the service is configured for (`PI_API_DATASETS=ae/pilot,…`, from the
     deploy config, not code);
  2. downloads each object;
  3. validates it with `pi_dataset` (the same library the publisher uses);
  4. builds in-memory indexes: by id, by brand, category and retailer, and a normalised EN/AR
     text key (case, diacritics, Arabic letter variants).

  A document that fails validation is **never served**. The previous good generation stays live,
  and if there is none the endpoint returns `503 data_unavailable`.
- **Freshness.** Each instance compares the object `generation` with the loaded one at most once
  every 60 s: one metadata GET. A new generation loads in the background and swaps in atomically,
  so readers see either the old dataset or the new one, never a mix. `meta.generation` and
  `meta.cutoff` are on every response.
- **ETag cache.** A response's `ETag` is the hash of the dataset generation, the API version and
  the canonical request, **and the caller's role and a digest of their scope claims**, so two
  users who may see different fields or datasets never share a validator. Clients send
  `If-None-Match` and get `304` while nothing has changed.
  `Cache-Control: private, max-age=60`, never `public`, because responses depend on the user.
- **Size.** Today's pilot dataset is a few MB. The budget is ≤ 50 MB of JSON per instance; beyond
  that, history moves to the fact extracts and is read lazily per product. The instance has
  512 MiB.
- **Transition.** Until the producers emit v2 (PR-B defines it, and Infra then switches
  `demo_export`/`publish_dataset`), `SnapshotSource` reads `datasets/uae/latest.json` (v1)
  through the read adapter in `pi_dataset`. The adapter maps the fixed `u`/`s` slots to register
  source keys **from the document's `meta.retailers[].key`**, never from literals. v1 support is
  removed when the dashboard moves to v2.
- **Swappable backend.** Routers and `pi_metrics` depend only on this protocol:

  ```python
  class DataSource(Protocol):
      def dataset(self, market: CountryCode, scope: str) -> LoadedDataset: ...  # validated, indexed
      def scopes(self) -> Sequence[ScopeRef]: ...
      def generation(self, market: CountryCode, scope: str) -> str: ...
  ```

  A later `PgSource` implements it against `pi_db` with a read-only role and RLS keyed on the
  user's claims. Cloud SQL costs about $10–15/month and **needs the owner's approval**; nothing in
  this design depends on it.

## 4. Auth

- **Token.** Every `/v1/*` call needs `Authorization: Bearer <Firebase ID token>`.
- **Verification.** The token is verified in-process against Google's public certificates, which
  are cached for their `max-age`. The checks are:
  - the signature (RS256), `aud = productintelligence-beeb3`, `iss`, `exp`/`iat`, and `auth_time`;
  - the custom claim `role ∈ {viewer, admin}` (set by `infra/scripts/invite_user.py`, #23).

  A missing or invalid token → `401`. A valid token without a known role → `403`.
- **The assistant forwards the signed-in user's token.** It never uses a service-account identity
  for data reads, so the user's own permissions apply to every tool call.
- **Roles:**

  | | viewer | admin |
  |---|---|---|
  | All read endpoints | ✓ | ✓ |
  | Admin-only fields: `evidence[].runId`, `evidence[].source`, coverage internals (rungs, run ids, block counts) | stripped | ✓ |
  | `/v1/matches?reviewState=proposed\|rejected` (the review queue view) | – | ✓ |

  Admin-only fields live in **separate response models**; they are not filtered out after the
  fact. A viewer response model does not have the field, so it cannot leak.
- **Scopes (ADR-0007 §7, built with PR-F).**
  - A `ScopeFilter` is derived from the `scopes` claim and applied inside the `DataSource` query
    layer, so every endpoint is covered by construction.
  - It is fail-closed once `PI_API_SCOPES_ENFORCED=true`: a viewer with no `scopes` claim sees no
    dataset.
  - `admin` or `scopes.all` gives full access.
  - Until PR-F exists, the flag is off, and behaviour matches today's Storage rules.
- **Revocation.** `check_revoked` is **off** by default. It would cost an extra Auth call per
  request, and ID tokens live one hour. Admin-only routes turn it on.
- **Abuse limits.** Each instance has a per-uid token bucket (default 10 req/s, burst 30; config).
  The bucket is **per instance**, so a user's effective ceiling is the limit × `max-instances`
  (2 → 20 req/s). That is accepted for the pilot; a global limit would need shared state
  (Firestore or Redis) and is not proposed. App Check can be added in front later if the owner
  enables it (as in the assistant design).
- **CORS.** Same-origin through a Firebase Hosting rewrite (`/api/**` → the Cloud Run service), so
  the dashboard's CSP `connect-src 'self'` is unchanged. See §11 Q1 for the region caveat.

## 5. Conventions every endpoint follows

**Envelope** (agreed with the AI Assistant Engineer):

```jsonc
{
  "status": "ok" | "not_enough_data",
  "data": { ... },                       // present when ok (and on partial rows; see compare)
  "reason": "cohort_too_small",          // when not_enough_data
  "detail": {"en": "...", "ar": "..."},  // human text for the reason
  "cohort": {"description": "exact approved/locked pairs, same size, both priced", "n": 12},
  "caveats": [{"en": "Retailer X partial: 412 products loaded", "ar": "..."}],
  "evidence": [{"productId": "...", "retailer": "<source_key>", "url": "https://...",
                "capturedAt": "2026-09-30T20:42:00Z", "runId": "…admin only…"}],   // ≤ 20
  "meta": {
    "apiVersion": "1.0.0", "endpoint": "compare", "metricVersion": "2026-10-01.1",
    "generation": "1727…", "cutoff": "2026-09-30T00:00:00Z",
    "market": "AE", "currency": "AED", "scope": "pilot",
    "filters": { ... }                   // the validated, normalised input, echoed
  }
}
```

**The `not_enough_data` reasons** form a closed enum:
- `capability_off`
- `field_not_collected`
- `retailer_blocked`
- `retailer_partial`
- `cohort_too_small`
- `matches_unreviewed`
- `no_match`
- `not_in_scope`
- `currency_mismatch` (new: sides in different currencies, ADR-0007 §6; see §7.2)

An empty result is `ok` with `total: 0` only when the data was complete. Otherwise it is one of
these reasons. A missing value is never a zero.

**Errors** use a transport-level shape (not an envelope), `{"error": {"code": "...", "message": "..."}}`:

| Status | Code |
|---|---|
| 400 / 422 | `invalid_request` (unknown keys are rejected) |
| 401 | `unauthenticated` |
| 403 | `forbidden` / `out_of_scope` |
| 404 | `not_found` |
| 409 | `stale_cursor` (the cursor's generation is no longer loaded; restart paging) |
| 429 | `rate_limited` (with `Retry-After`) |
| 503 | `data_unavailable` |

No stack traces or dataset internals appear in messages.

**Money and numbers:**
- **Money** is `{"amount": "129.00", "minor": 12900, "currency": "AED"}` (ADR-0007 §6):
  - `amount` is a decimal **string** at the currency's ISO 4217 exponent (from `pi_core`, e.g.
    `"3.250"` KWD);
  - `minor` is an integer.

  A response in one market also carries `meta.currency`.
- **Every metric value** (percentages, indexes, rating averages, medians) is a decimal string
  matching `^-?\d+(\.\d+)?$`. Counts are integers. **No JSON floats anywhere.** A CI test walks
  the OpenAPI schema and fails on `type: number`.
- **Rounding** happens once, at the edge. The rule is half away from zero (`ROUND_HALF_UP` on
  `Decimal`):
  - money at the currency exponent;
  - percentages and indexes at 1 dp;
  - rating averages at 2 dp.

  Internal sums use unrounded Decimals.

**Source text:**
- Retailer text (brand, name, SKU, shade names, category labels, promo text) is returned **raw**,
  with only control characters (C0/C1 except `\t\n`) stripped.
- Each such schema property carries the OpenAPI extension `x-pi-source-text: true`.
- The assistant treats every string not on its trusted list as untrusted, and escapes it.
- Evidence URLs are returned raw. Clients filter them to https plus their host allowlist.

**Input:**
- query models are strict; unknown keys give `422`;
- free text ≤ 120 chars;
- lists ≤ 25 values;
- `limit` ≤ 100 (default 25; the assistant caps itself at 25);
- cursor paging (`cursor` is opaque and bound to the generation, so a stale cursor gives `409
  stale_cursor`);
- dates are ISO-8601;
- enums are closed.

**Parameters are data (ADR-0007):**
- `market` (ISO country), `scope`, `retailers` (register `source_key`s), `brand` and `category`
  are validated against the loaded dataset's own `markets[]`, `retailers[]` and taxonomy;
- `market` may be omitted only when the caller's visible datasets contain exactly one market;
- no source key, brand or country appears as a literal in `pi_api`/`pi_metrics`, enforced by the
  ADR-0007 literal guard test.

## 6. Endpoints (v1)

All endpoints are `GET` unless marked otherwise, and all are read-only. **One assistant tool
maps to one endpoint** (blueprint §11); the dashboard uses the same ones.

| Endpoint | Assistant tool | Purpose |
|---|---|---|
| `/v1/meta` | – | Markets, scopes, retailers (id, name, logo, country, status, since), capabilities, per-field status, taxonomy, and the cutoff and generation. Drives the pickers |
| `/v1/products` | `search_products` | Search and filter product cards |
| `/v1/products/{id}` | `get_product` | Card plus per-retailer offers, gap and match |
| `/v1/products/{id}/history` | – | Price, regular and promo series per retailer |
| `POST /v1/compare` | `compare` | Pair rows plus summary |
| `/v1/index` | `index_trend` | Fixed-basket price index points |
| `/v1/promotions` | `promotions` | Promo share and items |
| `/v1/assortment-gaps` | `assortment_gaps` | Present at one retailer, absent at another |
| `/v1/availability` | – | Stock-out and low-stock shares (unknowns separate) |
| `/v1/launches` | `launches` | First-seen items |
| `/v1/reviews-summary` | `reviews_summary` | Rating averages and counts |
| `/v1/coverage` | `coverage_status` | Per-retailer coverage and trust |
| `/v1/matches` | – | Match edges and rationale |
| `/v1/export/{view}` | – | CSV/JSONL of a view |
| `/healthz`, `/readyz` | – | Liveness; readiness means a validated dataset is loaded. No auth, no data |

**Common filters** on the list and metric endpoints: `market`, `scope`, `retailers`
(`base,other`, or N for coverage and assortment), `brand[]`, `category[]`, `from`, `to`.

- **`/v1/products`:** `q`, `brand[]`, `category[]`, `retailer[]`, `matched`, `priceMin`,
  `priceMax` (decimal strings, in `meta.currency`), `sort=name|price_asc|price_desc|gap`,
  `limit`, `cursor`. Returns `{total, truncated, nextCursor, items: ProductCard[]}`.
  - A `ProductCard` has: `id`, `brand`, `name`, `category`, `size` (string plus unit), `image`
    (null until the contract carries it; never invented), per-retailer `price: Money | null`, and
    `match {class, reviewState, confidence}`.
- **`/v1/products/{id}`:** the card, plus `offers[retailer]`:
  - `price`, `regular`, `promoPct`, `rating{average, count}`, `size`, `shadeCount`, `sku`, `url`,
    `early`, `capturedAt`, `availability`;
  - `gap {gapAmount: Money, gapPct, cheaper, convention} | null`, with `gapExcludedReason` when
    null;
  - `match {class, reviewState, confidence, rationale}`.
- **`/v1/products/{id}/history`:** `from`, `to`. Returns `series[retailer] = [{date, price, regular,
  promo, availability}]`. The trend needs `capabilities.history`, otherwise `capability_off`.
  Missing days are `null` with a `notObserved` window, never carried forward.
- **`POST /v1/compare`:** the body is `{ids[2..6]}` or `{brand?, category?}`, plus
  `retailers {base, other}`.
  - `rows[]`: `{id, name, basePrice, otherPrice, gapAmount, gapPct, cheaper, counted,
    excludedReason}`.
  - `summary {n, medianGapPct, meanGapPct, cheaperCounts{<source_key>: n}, equalCount,
    basket {base, other}} | null`.
  - Rows are always returned. The summary follows the cohort rule (§7).
  - With more than two retailers, a row is `exact` only if every pair among them has an exact
    edge; otherwise it is partial (ADR-0007 §5).
- **`/v1/index`:** `retailers {base, other}`, `brand`, `category`, `from`, `to`. Returns
  `{points: [{date, index, n}], trendAvailable, definition}`.
- **`/v1/promotions`:** `retailer[]`, `brand`, `category`, `minPct`. Returns
  `{promoShare{<source_key>: pct}, items[{id, name, retailer, price, regular, statedPct}]}`.
  Needs `capabilities.promotions`.
- **`/v1/assortment-gaps`:** `missingAt`, `presentAt`, `brand`, `category`. Returns `{total,
  byBrand[{brand, count}], items: ProductCard[]}`, with the absence rules (§7).
- **`/v1/availability`:** `retailer[]`, `brand`, `category`, `date` (default: the latest).
  Returns, per retailer, a count for **every** blueprint state (`pi_core.AvailabilityState`):
  `inStock`, `lowStock`, `outOfStock`, `notDeliverable`, `removed`, `notObserved`, `blocked`,
  `unknown`. Shares use only the observed states (`AvailabilityState.is_known`) as the
  denominator, and the response states that denominator.
  - `notObserved`, `blocked` and `unknown` are never folded into out-of-stock or removed.
  - `removed` is reported only when the retailer's crawl for that date was **complete**
    (`status = supported`, no `notObserved` window covering the date and category). After a
    partial or blocked run the product is `notObserved`, and a caveat names the run.
  - A retailer that is `partial` or `blocked` for the date gets its counts plus
    `not_enough_data` / `retailer_partial` or `retailer_blocked` for the shares.
- **`/v1/launches`:** `retailer`, `since`, `category`. Returns `items[{id, name, retailer,
  firstSeen}]`. Needs two or more runs (`capability_off:history`).
  - A product is a launch on date *d* only if it was **not** seen at that retailer on the
    previous date *and* that previous run was **complete** for its category (`supported`, no
    `notObserved` window covering it). First-seen after a partial or blocked run is not a launch:
    the retailer's catalogue simply wasn't observed. Those items are withheld and counted in a
    caveat ("n items first seen after an incomplete run").
  - First-seen on the first date of the dataset is never a launch.
- **`/v1/reviews-summary`:** `id | brand | category`. Returns `{n, avgRating, ratingCount}` per
  retailer. The rating distribution and themes → `field_not_collected`. There is no review text.
- **`/v1/coverage`:** `retailer[]`. Returns `retailers[{id, name, status, since, note,
  productCount, matchedCount, freshness}]`, `capabilities`, `fields` and `notObserved`. Admins also
  get rungs, run ids and block counts.
- **`/v1/matches`:** `class`, `reviewState`, `retailers`, `brand`, `limit`, `cursor`. Returns
  edges with confidence and rationale. The review states are the canonical `pi_core.ReviewState`
  set: `proposed`, `approved`, `rejected`, `locked` (there is no `accepted`, `auto_accepted` or
  `pending` state; "accepted" was the v1 UI label). Viewers see `approved|locked`; admins see all
  states. **`locked` stays distinct from `approved`** all the way from `pi_db` through v2 to here.
  The v1 exporter merged both into `accepted`; the v1 adapter maps that to `approved` and adds a
  caveat that locked edges can't be told apart in v1.
- **`/v1/export/{view}`:** `view ∈ {products, compare, index, promotions, assortment-gaps,
  coverage}`, `format=csv|jsonl`, plus that view's filters.
  - It streams exactly the rows the view's endpoint returns, from the same `pi_metrics` call.
  - Row cap 50 k.
  - A manifest header row (or `#` comment for CSV) gives the cutoff, generation, filters and
    apiVersion.
  - Each export is audited: one structured Cloud Logging entry (`pi_api.export`) with the uid,
    role, view, filters, row count, generation and apiVersion, and never row content. It goes to
    the project's default `_Default` bucket (30-day retention, within the free allotment). A
    longer retention sink needs the owner's approval and is not proposed.

## 7. Metric rules (owned by `pi_metrics`)

These rules come from the Reviewer's REQUEST_CHANGES on #32, and are binding for the API and every
client.

1. **Money** is Decimal throughout, and rounds once at the edge (§5).
2. **Counted pairs.** Price gaps and indexes count a pair only if **all** of these hold:
   - `matchClass = exact`;
   - `reviewState ∈ {approved, locked}` (both are human-confirmed; `locked` is also frozen
     against re-matching);
   - the same normalised size;
   - both sides priced;
   - neither side `early` (recon samples);
   - the same currency. Otherwise the reason is `currency_mismatch`. **There is no FX path in
     v1 of the API:** neither contract carries rates, and no rate source is approved. Adding one
     means a dated, sourced rate table in the contract (`meta.fx[]`, with the rate's date and
     source) and a `metricVersion` bump; converted values would then be labelled. Until then a
     cross-currency pair is never converted.

   `proposed` and `rejected` edges are never counted. Every excluded row
   carries `excludedReason`.
3. **Absence claims (assortment gaps).**
   - If the "missing at" retailer is `partial` → `not_enough_data` / `retailer_partial`.
   - If it is `blocked` → `retailer_blocked`.
   - A product that was not observed is never reported as absent.
   - Rows are labelled `unmatched`, not "missing", unless matching for that brand and category was
     reviewed.
4. **Cohorts.** Summary statistics (median and mean gap, index points, promo share) need n ≥ 5.
   - Below that → `cohort_too_small`, and the rows are still returned.
   - If n is 0 because no candidate pair was reviewed → `matches_unreviewed`.
5. **Gap convention.** `gapAmount = other − base`, `gapPct = (other − base) / base × 100`,
   `cheaper ∈ {base, other, equal}`. `convention` is stated in the response.
6. **Index.** Σ other / Σ base × 100 over a **fixed basket**: the pairs counted on the first date
   of the window, and still counted on each later date. Each point reports its own `n`, and the
   cohort rule applies **per point**: a point with n < 5 has `index: null` and
   `reason: cohort_too_small`, and the line has a gap there, not an interpolated value. If the
   first date's basket has n < 5, the whole response is `not_enough_data` / `cohort_too_small`.
   A single date gives one point and `trendAvailable: false`. There is no extrapolation.
7. **Markets are data.** Currency and exponents come from `pi_core`, and retailers from the
   dataset. There are no literals.

Every metric function takes typed inputs and returns `(value | NotEnoughData, cohort, caveats)`,
so the envelope is assembled mechanically. `metricVersion` changes whenever a definition changes,
and is recorded in `docs/decision-log.md`.

## 8. OpenAPI and typed clients

- The FastAPI app generates **OpenAPI 3.1** from the pydantic v2 response and query models.
  Shared value types come from `pi_core` and `pi_dataset`.
- `make openapi` writes `docs/contracts/pi-api.openapi.json`. A CI test regenerates it and fails
  on any diff, so the committed schema is always the served one.
- The FE generates TS types from it, and the assistant generates zod. Breaking changes bump the
  major `apiVersion` and get a new `/v2` prefix. Additive fields are minor bumps. Clients must
  ignore unknown response fields; requests stay strict.
- The schema extensions are `x-pi-source-text` (§5) and `x-pi-admin-only` (documentation only;
  the models already exclude these fields for viewers).
- **Golden responses.** `docs/contracts/golden/` holds request/response pairs generated from the
  synthetic fixture datasets (§10). They let FE and assistant tests run without the server,
  and they review metric changes as diffs.

## 9. Hosting and cost (≤ $25/month total cap)

**Hosting:**
- **Runtime.** Cloud Run service `pi-api`, **me-central1**, running a container image (Python
  3.12, uvicorn, one worker) from Artifact Registry in the same region.
- **Scaling.** `min-instances=0` (scales to zero), `max-instances=2`, concurrency 40,
  1 vCPU / 512 MiB, request-based billing (CPU only during requests), timeout 30 s.
- **Identity.** A dedicated runtime service account `pi-api@` that can **read objects** under
  `datasets/` and nothing else. It has **no** Secret Manager or DB roles, and no Firebase admin
  roles. Token verification needs only public certificates.
  - IAM conditions on object names work only with **uniform bucket-level access (UBLA)** on the
    bucket; Infra confirms it is on (or enables it) before granting.
  - A `resource.name.startsWith("projects/_/buckets/<bucket>/objects/datasets/")` condition
    covers `objects.get`, but **not** `objects.list`, which is checked against the bucket. The API
    therefore never lists: it reads the configured `PI_API_DATASETS` paths, and the generation
    check is an object metadata GET. The grant is a custom role with `storage.objects.get` only
    (not `objectViewer`, whose list permission would be denied by the condition anyway).
- **Deploy.** Infra deploys it, with a Cloud Build or GitHub Actions workflow that Infra owns.
- **Approval first.** The Cloud Run service `pi-api` and its Artifact Registry repository are
  **new standing billable resources** (small, see below, but not zero). They fall within the
  owner's $25/month GCP delegation to the Program Coordinator. Neither is created until a
  **coordinator approval entry is recorded in `docs/decision-log.md`**, naming both resources, the
  region and scaling limits, and citing the cost estimate below against the remaining budget. If
  the estimate exceeds the remaining budget, the decision escalates to the owner. S4's deploy
  handoff is gated on that entry.

**Estimate** (verify against the GCP price list on the day; me-central1 is a Tier 2 region):

| Item | Assumption | Est. $/month |
|---|---|---|
| Cloud Run requests + CPU | ≤ 50 k requests × ~150 ms at 1 vCPU ≈ 7.5 k vCPU-s, 3.75 k GiB-s: within the free tier if it applies to the region, otherwise well under $1 | $0–1 |
| Cold starts | Load a few MB of JSON plus validation, ~2–4 s. Accepted for the pilot; `min-instances=1` would cost ≈ $10–15 and **is not proposed** | $0 |
| GCS reads | One generation check per instance per minute while warm, plus downloads on change | < $0.10 |
| Artifact Registry | One image of ~150 MB (keep the last 3 tags) | < $0.10 |
| Egress | JSON responses, a few hundred MB | < $0.10 |
| **Total** | | **≈ $0–1.5** |

Cloud SQL (a `PgSource` backend) would add about $10–15 and is **not** part of this design.

## 10. Test plan (coverage ≥ 85%, offline only)

- **`pi_metrics` unit and property tests (Hypothesis):**
  - gaps are antisymmetric under swapping base and other;
  - index scale: multiplying all "other" prices by k multiplies the index by k;
  - the basket stays fixed across dates;
  - only permitted pairs are counted;
  - n < 5 → `cohort_too_small`, including per index point;
  - only `exact` + `approved|locked` edges count, and a locked edge stays `locked` end to end;
  - partial or blocked → the absence rules;
  - no launch and no `removed` after a partial or blocked prior run;
  - every `AvailabilityState` appears in `/v1/availability`, with only known states as the
    denominator;
  - rounding is half away from zero, at each currency's exponent;
  - no float ever reaches the output.
- **Fixture datasets** (synthetic, committed, no retailer data):
  - `ae_pilot` (two retailers, AED);
  - `kw_three_retailers` (KWD 3 dp, N = 3, one partial, one blocked);
  - `fr_two_retailers` (EUR, a non-Gulf market);
  - a v1 document for the adapter.
- **API tests.** FastAPI `TestClient` with an **in-test RSA key and fake certificate endpoint**, so
  no network is used. Covered:
  - auth matrix: no token, bad signature, expired, wrong `aud`, no role, viewer, admin;
  - scope claims with enforcement on and off;
  - viewer responses contain no admin-only field (a schema walk);
  - strict inputs return `422`;
  - `ETag`/`304`, with different ETags for a viewer and an admin (and for different scope
    claims) on the same request, and a stale cursor returns `409`;
  - the `503` path on an invalid dataset;
  - the atomic reload on a generation change (fake storage client).
- **Contract tests:**
  - the committed OpenAPI equals the generated one;
  - there is no `type: number` in the schema;
  - every scraped string field carries `x-pi-source-text`;
  - the golden responses are reproduced byte for byte.
- **The ADR-0007 literal guard** covers `pi_api` and `pi_metrics`.
- **Performance smoke** (local, not CI-gating): p95 < 300 ms warm for each endpoint on the
  fixtures (web app target p95 ≤ 3 s end to end).
- **Security:**
  - gitleaks;
  - no credentials in images or config (the service needs none);
  - control characters are stripped from source text;
  - a bounded response size (≤ 20 evidence items, `limit` ≤ 100).

## 11. Open questions

1. **Hosting rewrite region.** Firebase Hosting → Cloud Run rewrites may not support every
   region. If me-central1 isn't supported, the web app calls the `run.app` URL directly: CORS
   allowlists the two Hosting origins, and Infra adds that URL to CSP `connect-src`.
   **Infra to confirm.**
2. **v2 timing.** Serve v1 through the adapter first (faster), or wait for v2 producers?
   *Proposal:* the adapter, so FE and the assistant can switch early. v2 follows with PR-B and the
   Infra producer change.
3. **Images.** Neither v1 nor v2 has image URLs yet. `image` stays `null` until the contract adds
   them (tracked with PR-B). The API never invents them.
4. **Export formats.** CSV and JSONL in v1. Excel and Parquet come later, if FE asks.
5. **FE views.** The FE's list of views and fields (requested) may add endpoints or fields.
   Additive changes need no ADR.

## 12. Delivery plan

The order, per the coordinator: this design → PR-B (contract v2 definition) → the implementation
PRs below → PR-D/E.

| PR | Contents |
|---|---|
| S1 | `pi_metrics`: rules §7 plus the fixture datasets, golden outputs and property tests |
| S2 | `pi_api` skeleton: auth, envelope and errors, `SnapshotSource` (v1 adapter + v2), `/v1/meta`, `/v1/products*`, `/v1/coverage`, OpenAPI export plus the drift test, Dockerfile |
| S3 | Metric endpoints: compare, index, promotions, assortment-gaps, availability, launches, reviews-summary, matches |
| S4 | `/v1/export/*`, the deploy handoff doc for Infra (service account, IAM condition, Hosting rewrite or CORS), and the runbook |

FE and the assistant switch their data reads to the API after S2 and S3. Their generated types and
zod come from `docs/contracts/pi-api.openapi.json`.
