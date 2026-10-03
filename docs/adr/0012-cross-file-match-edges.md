# ADR-0012: Match edges across per-source files (Ulta, Sephora and Faces)

- Status: proposed (drafted by the Matching Scientist on task 01a102de, 3 Oct 2026)
- Date: 2026-10-03
- Amends: ADR-0010 §4 "Matches" ("edges are never made across files") and its consequence
  "Cross-source matches". Everything else in ADR-0010 is unchanged.
- Applies to: `pi_match` (the incremental matcher), a new `pi.matches/v1` file, `pi_dataset.compose`
  (applying it), `pi_api` config, the publisher and the deploy config.
- Owner decision (relayed by the coordinator, 3 Oct 2026): "product matching across all these 3,
  as when we add new product matching must work", with the steer **accuracy first**: a precision
  lower bound of at least 98% per category on a double-labelled gold set that includes Faces
  pairs, hard constraints never overridden, and `proposed` (not an accepted exact) when unsure.

## Context
Each retailer is now its own file: `ulta_ae` comes read-only from the owner's combined file
`datasets/ae/beauty/latest.json`, and `sephora_me` and `faces_ae` come from PI's per-source
files. Today an edge lives inside one file's product, so ADR-0010 only counts a pair when one file
holds both offers. Faces (1457 products) can therefore never be matched, and Ulta and Sephora are
matched only through a combined Ulta+Sephora file that has to be rebuilt and redeployed for every
change. Neither works when new products arrive on every publish.

The data has no shared barcode. Of the Faces SKUs, 121 are valid GTINs, while the Ulta and Sephora
SKUs are the retailers' own ids, so no GTIN pairs exist across them. Matching rests on brand, name,
size, shade, concentration and kind. That makes careful calibration and review mandatory.

## Decision
1. **Edges get their own file, keyed by stable listing ids.** The PI team publishes one match file
   per scope, `datasets/ae/matches/latest.json` (schema `pi.matches/v1`). It holds no products,
   offers or prices, only edges and the matcher's state. A listing id is `(retailer, token)`.
   The token is the exporter's per-retailer group token (`<slot>-<retailer product id>-<size>-<unit>`,
   for example `f-000110051079-180-ml`). That is the product id of a one-retailer product, or
   that retailer's half of an `m-<token>-<token>` pair id. It is built from the retailer's own
   product id, so it survives re-publishes. An offer whose token cannot be read (a hashed `p-` id,
   an early sample) cannot get an edge from this file. It is counted as `unkeyed`, never guessed.
2. **An edge names two listings of two different retailers.** Each edge carries `matchClass`,
   `reviewState`, `decidedBy`, `confidence`, `method` (the matcher's `algo_version`), `stage`,
   `reasons` and a feature fingerprint for each side. Like `MatchEdge`, it is the only evidence of
   identity. Nothing is transitive: edges u–s and s–f say nothing about u–f, and a u–f pair
   without its own edge reads `no_match`.
3. **Classes, accuracy first.**
   - Hard constraints run first and nothing overrides them. These are: same brand key; two valid
     GTINs that differ never match; a known concentration must agree (EDP ≠ EDT ≠ parfum); kind
     must agree (minis, refills and sets stay separate); for `exact`, the size must be known and
     equal, and a shade code or name known on both sides must agree. An equal GTIN does not
     override a rule conflict.
   - `exact` edges are `proposed` unless the pair's category has a calibrated auto-accept
     threshold, that is, the precision lower bound (Wilson 95%) on the gold set is ≥98% for that
     category. Until a category passes, nothing in it is auto-approved. `approved` and `locked`
     otherwise come only from human review.
   - Same product but a different size or shade is `family` with `proposed`, and never exact.
   - Unsure pairs (below the exact score, or a concentration known on one side only) are not
     edges. They go into the file's `review` queue, so they never show as matched.
   - Each listing has at most one exact edge per other retailer. A one-to-one conflict is
     resolved deterministically (state, then confidence, then ids), and the loser goes to review.
4. **Decisions persist; rejected pairs never return.** A `rejected` pair stays in the file as a
   hard negative and is never proposed again, whatever later scores say. Human decisions
   (`approved`, `locked`, `rejected` by a human) are carried over unchanged on every run. A model
   or threshold change never rewrites them (MAT-05, MAT-07).
5. **Incremental, deterministic, idempotent.** A run reads the three published source files
   read-only, plus the previous match file. Only listings that are new, or whose fingerprint
   changed (brand, name, size, shade, concentration, kind, GTIN), are re-scored, against their
   brand block in the other retailers. Unchanged pairs keep their edge byte for byte. Listings no
   longer present keep their edges, but these are dormant because compose ignores an edge with a
   missing side. The same inputs give byte-identical output, and a second run with the same
   inputs changes nothing. The run time is a recorded input, never read from a clock.
6. **Composition applies the file.** `PI_API_MATCHES=<path>` assigns a match file to a scope. It
   is optional, and without it everything behaves exactly as in ADR-0010. After `compose`, every
   non-rejected edge whose two listings are both in the view joins their products into one
   product. Merges add edges in a deterministic priority order (locked, approved, proposed, then
   confidence, then ids). An edge that would put two offers of one retailer in one product is
   skipped and logged (`edge_conflict`). The merged product takes its fields and its id from the
   member with the smallest retailer id, as in ADR-0010 field precedence, and the other members'
   ids resolve to it through `pi_api.ids`. When an in-file edge and the match file name the same
   listing pair, the match file's state wins, because it carries the review. A file whose scope or
   vertical differs from the view is refused, and the previous view stays live (ADR-0010 §5).
7. **Ulta stays read-only.** Ulta listings are read from the protected file and nothing is written
   to it. The match file is PI-owned and holds no Ulta prices or content beyond listing tokens and
   fingerprints. `--drop-source ulta_ae` is never used, and the protected file's generation is
   checked before and after every publish.
8. **Precision gate in CI.** A gold set (`packages/pi_match/gold/`) holds labelled listing pairs
   covering every pair of retailers and each category, double-labelled from saved evidence, with
   disagreements adjudicated. CI re-scores it on every change to `pi_match`. Precision of `exact`
   (and its Wilson lower bound) per category, and overall, may not fall below the pinned baseline.
   A category is auto-accept eligible only at a lower bound of ≥98% with at least 30 labelled
   pairs. The set is reported as `single_labelled` until a second labeller has passed, and it does
   not claim ≥600 pairs until it has them.
9. **Publishing.** Matching runs whenever a source file is re-published. Its output is published
   create-only to `datasets/ae/matches/<ts>.json` and then `latest.json`, through the same
   guarded publisher. This needs no new cloud resource: the run is local or in CI, so there is no
   added cost. Pointing production at the file (`PI_API_MATCHES`) is a deploy, and the owner runs it.

## Consequences
- New Faces, Sephora or Ulta products are matched on the next publish without rebuilding any
  combined file, and all three retailer pairs are covered.
- `matched=true` (ruling A) will include `proposed` exact edges, labelled "Unreviewed match".
  Counted metrics still need `approved` or `locked`. Until review or calibration, comparisons
  show matches as unreviewed and compute no gaps from them. That is the price of accuracy first.
- A product can now combine offers from several files. Its pairs remain per edge.
- The existing 255 Ulta–Sephora edges in the matched combined file can be seeded into the match
  file by listing token, keeping their states. The combined file is then no longer needed for
  matching.
- `pi_api` gets a minor version bump when composition learns the match file.
