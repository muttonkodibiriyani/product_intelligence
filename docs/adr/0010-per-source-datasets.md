# ADR-0010: Per-source dataset files, composed per scope by the API

- Status: proposed (drafted by the Deep Coder on the coordinator's owner-approved "scheme A"
  brief, 1 Oct 2026)
- Date: 2026-10-01
- Extends: ADR-0007 §6 (dataset layout), ADR-0008 §4 (`pi_api` reads v3)
- Applies to: `pi_dataset` (`compose`), `pi_api` (`config`, `source`, `/v1/meta`), the publisher
  and the exporter (`--sources`, #112), and the `pi-api` deploy config

## Context
The live beauty snapshot `datasets/ae/beauty/latest.json` is one combined file that holds both
`ulta_ae` and `sephora_me`, and it belongs to the owner's session. The owner's hard rule is that
the PI team never writes, cleans, re-matches or republishes Ulta content, and that no code path
updates or deletes `ulta_ae` rows or the shared rows they reference. The PI team still needs to
publish fresher Sephora data. A single-file layout forces a choice: rewrite the combined file,
which touches Ulta, or serve two overlapping files of one scope, which `select()` refuses as
`ambiguous_dataset` and which would show Sephora twice.

## Decision
1. **One source per file.** The PI team publishes `datasets/ae/<source>/latest.json` and writes
   only its own source: today `datasets/ae/sephora_me/latest.json`, made by the exporter with
   `--sources sephora_me` (its default; any Ulta source needs `--ulta-unblocked`) and written by
   Infra's publisher. The combined file is read only.
2. **Assignment in config.** `PI_API_DATASETS` entries are either a bare `path`, served whole
   exactly as before, or `source=path`, for example:

   ```
   PI_API_DATASETS=sephora_me=datasets/ae/sephora_me/latest.json,ulta_ae=datasets/ae/beauty/latest.json
   ```

   A source is assigned once. Several sources may share a path. A path is never both whole and
   assigned. The API is source-agnostic (ADR-0007): no retailer id appears in code.
3. **Only the assigned part is used.** `pi_dataset.compose.only(file, sources)` keeps the
   assigned retailers' entries, contexts, offers and `notObserved` windows, plus the match edges
   between two kept retailers. Everything else in the file is ignored. A file that lacks an
   assigned source is an error, not an empty source.
4. **One view per scope.** `compose(slices)` joins the assigned parts of one scope:
   - **Same scope or refuse.** kind, scope, vertical, profile and attribute set must be equal,
     and a market shared by two files must have one currency and time zone. Otherwise the view
     is not rebuilt.
   - **Same product id.** It is one product holding both offers (contexts are per retailer, so
     offers never collide), and the merge is logged. **Merging by id assumes canonical,
     source-disjoint ids**: the exporter derives one id per product token, whichever source
     offers it, so equal ids mean the same product and different products never share one.
     A file that breaks this would merge unrelated products; the per-source exporter keeps it.
   - **Field precedence.** No source owns a product id, so a merged product's own fields
     (brand, name, category, unit, shades, attributes, image) come from the slice that sorts
     first by its smallest retailer id. That is deterministic and independent of config order.
   - **Dates.** The view's dates are the union of the files' dates. A source's series are null
     on dates its file lacks: not observed, never carried forward. A retailer-wide
     `notObserved` window (no categories, no context) covers each run of those dates. So a date
     outside a source's file never backs an absence claim: no launch on its first date, no
     assortment gap or removal on the other source's dates.
   - **Matches.** Edges are never made across files. A pair is counted only if one file holds
     both offers and the edge.
   - **Meta.** `capabilities` are or-ed, a field status that differs between files is
     `partial`, `cutoff` and `generatedAt` are the latest, and `producer` is
     `pi_dataset.compose`. `/v1/meta.sources` gives each source's own cutoff, `generatedAt`,
     last date, match stage, capabilities, fields and product count.
5. **No silent fallback.** A composed view is first served only once every assigned file has
   loaded. If a file is bad, lacks its source or fails composition, the previous view stays live
   and the reason is logged. A source is never served from another file.
6. **Backward compatible.** Bare paths behave as in 1.4.x. `apiVersion` 1.7.0 adds only
   `meta.sources`. A bare path in the same scope as a composed view stays two datasets
   (`422 ambiguous_dataset`), so a deploy uses one form per scope.

## Consequences
- The PI team can publish Sephora on its own cadence without reading or writing Ulta data. No
  migration, and no stored rows are touched.
- **Union dates.** While the combined file is frozen, Ulta has no values on the newer Sephora
  dates. In 1.7.0, latest-date metrics (compare, price index, availability, summary) treat Ulta
  as not observed there, rather than showing its older price as current, and `meta.sources` shows
  each source's own cutoff. A stacked follow-up makes latest-date metrics read each retailer at
  its own latest observed date, with that `asOf` and a `stale_source` caveat. It is gated to land
  before the first new Sephora publish. Until then both files have the same dates.
- **Cross-source matches.** The combined file's Ulta–Sephora edges link to its own, older
  Sephora offers, so they are dropped. Counted Ulta–Sephora pairs come back only once a matched
  file with both offers is published. Whether, and by whom, that is done is the owner's call, since
  it is Ulta content.
- A product id shared across files (ids derive from the same product token) shows both offers
  under one product without a match edge. The catalogue counts it once.
- Infra's deploy smoke test checks the real files: the counts per source, and that scope,
  vertical and profile agree.
