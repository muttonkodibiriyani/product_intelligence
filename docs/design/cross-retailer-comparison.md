# Cross-retailer product-family and variant comparison

| | |
|---|---|
| Status | Proposed; implementation is split into the slices in §12 |
| Owner | Product Intelligence |
| Task | `01a11fdf-e255-7e52-a91b-9054d5218281` |
| Builds on | ADR-0008, ADR-0010, ADR-0012, `pi.dataset/v3`, `pi.matches/v1` |
| Preserves | append-only evidence, Decimal money, per-source capture state, no hidden inventory |

## 1. Outcome and non-negotiable rules

The comparison view answers one question without changing the captured source records:

> For one canonical brand and product family, what listings and variants did each retailer
> publish, how do their commercial facts differ, and what evidence supports every value?

The implementation is an additive, read-optimised projection. Source datasets, match files,
images and attribute text remain immutable inputs. The projection never:

- merges or deletes retailer SKUs;
- treats a failed, partial or out-of-window capture as retailer absence;
- exposes hidden inventory quantities;
- converts money across currencies or uses binary floating point for commercial arithmetic;
- lets image similarity, a generated description or an unreviewed edge override a hard match rule;
- replaces retailer text, source images, evidence URLs or content hashes.

## 2. Current system and additive mapping

| Required concept | Existing source | Comparison projection |
|---|---|---|
| Brand | `ProductV3.brand`, matcher brand aliases | `BrandRef(raw, key, aliasEvidence)` |
| Product family | retailer `OfferContent.family`; `pi.matches/v1` family/exact edges | stable `FamilyId`, members and pairwise evidence |
| Retailer listing | offer context + matcher listing token | `ListingRef(retailer, context, token, sourceProductId)` |
| Variant/SKU | `OfferContent.variants`; otherwise offer SKU | one immutable `VariantRef` per retailer SKU |
| Capture truth | source window, `notObserved`, `notObservedReason`, field status | tri-state retailer matrix cell (§4) |
| Match truth | edge class/state/confidence/method/reasons/fingerprints | visible `MatchEvidence`; no transitive claim |
| Size/pack | raw `SizeV3`, matcher normalisation | raw and canonical axis values with conversion provenance |
| Shade/colour | variant shade and declared attributes | raw and folded display keys; distinct SKUs retained |
| Price/stock | offer series, promotions and evidence | dated `CommercialSnapshot`; Decimal-derived discount |
| Attributes | profile `attributeSet`, values and `attributeEvidence` | typed cells with explicit state and conflicts |
| Images | source URLs/assets and `pi_image` SHA-256 | immutable description record keyed by source image hash |

`ProductV3` continues to mean the served, accuracy-gated product grouping described by
ADR-0012. A comparison family is a separate navigation concept; it does not weaken metric
cohorts or turn a family edge into an exact product match.

## 3. Canonical hierarchy and identity

The read model has four levels:

```text
BrandRef
  ProductFamily
    RetailerListing
      VariantRef (one retailer SKU)
```

### 3.1 Stable identifiers

- `brandKey` is the matcher's versioned normalised brand key.
- `listingKey` is ADR-0012's stable `(retailer, token)` pair.
- `variantKey` is `(listingKey, retailerSku)`; a missing variant list produces one synthetic
  key from the offer SKU, explicitly marked `basis=offer_sku`.
- `familyId` is the SHA-256 digest of the sorted member listing keys plus the family algorithm
  version. Aliases retain the previous id when membership changes, so saved links resolve.

Family candidates come from the retailer's own family id and `exact`/`family` match edges.
Cross-retailer membership is accepted only from a human-accepted (`approved` or `locked`) edge,
or a category whose automatic threshold has passed ADR-0012's precision gate. Proposed edges are
visible as suggestions but do not make a retailer present in a canonical family. Every member
retains the direct edges that justify it; an A-B and B-C path never claims an A-C exact match.

### 3.2 Explainability

Each relationship returns:

```json
{
  "class": "exact | family",
  "reviewState": "approved | locked | proposed",
  "confidence": "0.0000..1.0000 | null",
  "method": "pi_match.incremental/…",
  "reasons": ["same_brand", "name_score", "size_differs"],
  "fingerprints": {"left": "…", "right": "…"}
}
```

Confidence is a decimal string. The UI labels proposed evidence and never counts it as confirmed.

## 4. Retailer have / do-not-have matrix

One family row has one cell per retailer. The state is not boolean:

| State | Meaning | May render “does not have”? |
|---|---|---|
| `present` | an accepted member listing exists in the selected capture | no |
| `absent` | no member exists **and** the source declares complete in-scope capture | yes |
| `not_observed` | source missing, blocked, partial, stale for the requested date, or field absent | no |
| `ambiguous` | only proposed/conflicting family evidence exists | no |

Every cell includes `asOf`, source generation, capture window/run, completeness basis and member
listing ids. A filter named `have=retailer` selects `present`; `dontHave=retailer` selects only
`absent`. `not_observed` is separately filterable and is never folded into absence.

## 5. Variant axes without SKU collapse

Normalisation produces display/comparison keys, not new identities:

```text
AxisValue {
  axis: size | volume | pack | shade | colour
  raw: JSON scalar/list exactly as published
  canonical: Decimal/text/list | null
  canonicalUnit: ml | g | count | null
  method: page | declared_unit | deterministic_conversion | text_rule | none
  ruleVersion: string | null
  evidence: source field + excerpt/hash pointer
  state: observed | unknown | not_observed | conflict
}
```

Volume converts `l`, `cl` and `fl oz` to ml; mass converts `kg`, `mg` and oz to g. Conversion uses
Decimal constants and records the original value, unit, rule and version. Mass and volume never
compare. Pack count is its own axis and never multiplies into size unless the source explicitly
publishes both components. Shade codes take precedence for equality; folded shade/colour names
are navigation hints. Two SKUs with equal axes remain two rows and surface a conflict/duplicate
hint rather than being collapsed.

Retailer ladders are grouped only within that retailer's published family id. Cross-retailer
side-by-side alignment is by compatible canonical axes and carries `exact`, `compatible`,
`ambiguous` or `not_comparable`, with the supporting axis evidence.

## 6. Commercial facts

Each retailer variant exposes the last accepted observation at or before `asOf`:

- current, original/regular and promotional/member price as Decimal amount plus ISO currency;
- discount amount `regular - current` and percent `(regular - current) / regular * 100`, only
  when both values are positive, same-currency and the current price does not exceed regular;
- promotion ids and public offer text/evidence where the source captured them;
- public availability enum and field state, never `availableVariants` or another quantity;
- launch/new-arrival evidence as first-observed date and/or a captured badge, including its basis;
- source `capturedAt`, requested `asOf`, and stale/not-observed reason.

An invalid discount is a typed conflict, not zero. A missing regular price means an unknown
discount. Cross-currency price ordering is refused unless a future version adds a dated,
evidence-backed FX input.

## 7. Images and descriptions

Generated descriptions live in an append-only `pi.image-descriptions/v1` sidecar:

```text
ImageDescription {
  retailer, listingKey, sourceUrl, sourceImageSha256,
  description, locale, confidence,
  modelProvider, modelName, modelVersion, promptVersion,
  generatedAt, runId, evidenceGeneration
}
```

`sourceImageSha256` is the human-auditable join to `pi_image.ListingImage.image_sha`. A record is
reused only for the same image hash plus model/prompt versions. A changed image appends a new
record; it never edits source content. Descriptions are presentation evidence and cannot add a
match feature or attribute value. `missing_image`, `fetch_failed`, `unreadable` and `placeholder`
produce explicit states and no description.

## 8. Attribute contract and validation

The engine is profile-driven and must accept profiles with 150 or more definitions without code
changes. Every declared definition and every emitted cell is validated.

The production admission envelope is 4 GiB/1 vCPU with
`ADMISSION_OTHERS_MAX_BYTES=80,000,000`. After the measured beauty, Faces and BLM bodies, inline
attributes have a **7,656,319 byte total budget across the loaded dataset**, not per product.
Canonical attribute cells therefore live in a normalised, key-deduplicated sidecar/index; family
list payloads carry only completeness counts and selected facet values, and detail evidence is
cursor-paged. Admission rejects a generation whose encoded inline attribute contribution exceeds
that total.

Definitions specify key, level, type, allowed values, unit/currency constraints, cardinality,
facet eligibility and labels. A comparison cell contains raw value, canonical value, definition
version, evidence pointer, confidence (for deterministic/model extraction), and one state:

- `observed`: one valid evidence-backed value;
- `unknown`: capture covered the field but published no value;
- `not_observed`: source/capture did not cover the field;
- `conflict`: multiple incompatible observed values or invalid conversion;
- `invalid`: wrong type, enum, unit, currency, cardinality or evidence reference.

Validation reports completeness as `validObserved / declaredApplicable`, plus counts for every
state. It never creates a value to improve completeness. Attribute evidence remains source text;
model-derived attributes require model/version, confidence and evidence hash and remain barred
from hard identity rules.

## 9. API and web experience

Add two cursor-paged endpoints:

- `GET /api/v1/families`: compact family rows, retailer matrix and facets;
- `GET /api/v1/families/{id}`: variants, commercial facts, match/axis evidence, descriptions and
  paged attribute blocks.

Filters are repeatable and server-side: retailer, brand, category, family, `have`, `dontHave`,
capture state, availability, launch/new arrival, discount, public offer, current price, size,
shade, colour and attribute-completeness band. Sorts cover name, price, discount, completeness,
newest capture and retailer coverage. Cursors bind to generation plus filter/sort fingerprint;
stale cursors return the existing `409 stale_cursor` contract.

The web route `/[locale]/compare/families` uses a virtualised semantic table on wide screens and
stacked family cards on narrow screens. Headers remain associated with cells, filters have labels,
evidence is reachable by keyboard, focus is restored after paging, and state is encoded in the
URL. The initial response excludes long attribute evidence and image descriptions; detail blocks
load on expansion. English and Arabic copy ship together.

## 10. Incremental updates, history and cache scope

An accepted ingestion emits a deterministic change set of listing keys and input fingerprints.
The comparison builder:

1. resolves changed listings and their previous/current accepted edges;
2. expands only to their old and new family members;
3. rebuilds those family projections and facet deltas;
4. appends projection events and a change audit;
5. atomically advances the comparison generation;
6. invalidates family ids and facet buckets named by the change set only.

Idempotency key: `(sourceGeneration, matchGeneration, attributeProfileVersion,
descriptionGeneration, builderVersion)`. Replaying it produces byte-identical output and no new
event. History is append-only; corrections point to the superseded event. Rollback moves the
served generation pointer to a prior accepted manifest and records who/why/when; it does not
delete observations, match decisions or projections.

## 11. Measurable gates

Gates run on deterministic synthetic fixtures plus saved, already-authorised captures. They make
no retailer requests.

| Gate | Target |
|---|---|
| Incremental matching | ≥ 5,000 candidate pairs/s on one CI core; unchanged pair scores = 0 |
| Family rebuild | ≤ 2 × affected-family members visited; unrelated cache keys invalidated = 0 |
| List API | p50 ≤ 100 ms, p95 ≤ 300 ms at 100k variants, warm process |
| Detail API | p50 ≤ 150 ms, p95 ≤ 500 ms; SQL/source reads bounded per page |
| Payload | list ≤ 200 KiB gzip at max page; detail block ≤ 400 KiB gzip |
| Frontend | first 50 rows commit ≤ 100 ms; scroll update ≤ 16 ms median |
| Memory | measured four bodies plus attributes peak ≤ 3,072 MiB in the 4 GiB/1 vCPU service |
| Inline attributes | ≤ 7,656,319 encoded bytes total under the 80,000,000-byte others cap |

Correctness fixtures cover false same-brand matches, conflicting GTIN/concentration/kind, same
family with different size/shade, identical axes on distinct SKUs, retailer-specific ladders,
partial captures, stale sources, missing regular price, currency mismatch, absent image bytes,
150+ mixed-type attributes, replay, rollback and targeted cache invalidation.

Performance failures print data scale, elapsed time, payload bytes and peak RSS. Small unit suites
assert algorithms; production-scale gates are opt-in locally and required by the existing CI test
commands once their fixtures are stable. This design does not change workflow files.

No API/data generation is published until the saved four-body-plus-attributes admission fixture
records a measured peak at or below 3,072 MiB and passes the byte-budget gates. The admission
record includes input object generations, byte counts, builder version, peak RSS and result.

## 12. Reviewable implementation slices

1. **Contracts and evaluators:** family/variant/attribute/image-description models, tri-state
   matrix, Decimal normalisers and correctness fixtures.
2. **Incremental projection:** affected-family change sets, append-only manifest/events,
   idempotent replay/rollback and targeted cache keys.
3. **Read API:** list/detail endpoints, facets, filters, cursor paging, payload and latency gates.
4. **Web:** accessible responsive side-by-side view, URL filters, sorting and virtualisation.
5. **Release:** generated API types, exact-head tests, independent review, queue merge, deploy,
   live smoke and recorded rollback evidence.

Each slice rebases on the current `origin/main`; no slice changes collection, saved source
captures, deployment credentials or `.github/workflows`.
