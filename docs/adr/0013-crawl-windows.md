# ADR-0013: Declared crawl windows, per-retailer states and retained offers (pi.dataset/v3)

- Status: proposed (drafted by the Deep Coder on lane B task 01a11c55, 8 Oct 2026)
- Date: 2026-10-08
- Amends: `docs/contracts/pi-dataset-v2.md` rule 6 ("never carried forward") for windowed bodies
  only, as a **declared exception**, not as carry-forward. pi.dataset/v2 itself stays frozen; the
  window and the per-retailer states exist only in v3.
- Applies to: `pi_dataset.v3` (`CrawlWindow`, `RetailerV3.window`/`fields`/`capabilities`,
  `OfferV3.notObservedReason`, `NotObservedV3.context`), `pi_dataset.compose`
  (`resolved_retailers`, `window_gap_days`), `scripts/demo_export` (`--run`), and the stage/publish
  guard (Infra's deploy PR).
- Owner decision (relayed by the Coordinator, ruling 01a11c69-277e-723b-9b4f-7a727bdcf1d0 on the
  program-coordination anchor, 8 Oct 2026): an explicit, declared crawl window; one run per
  retailer; at most 4 Dubai calendar days; the latest in-window value with its own `capturedAt`;
  nothing from outside the window; field status `ok` with basis `window`; a window over 4 days
  fails; tests; and this note saying the window is a declared exception to contract rule 6, not
  carry-forward. Further rulings recorded here: 01a11c69-5216 (per-retailer `fields.regular`,
  `capabilities.promotions` and `window`), 01a11c6a-8815 (window gap), 01a11c6c-0d27 (stock option
  A and the known gap), 01a11c71-37ee (the gap guard is enforced in code), 01a11cb7-030e and
  01a11cb9-f2b0 (segments and retained markers ship with the exporter, this note and the tests).

## Context
A full crawl of a large retailer does not finish in one Dubai day: Ounass takes four. Under rule 6
a one-date body may only publish values captured on that date, so a multi-day crawl either
publishes a fraction of its catalogue or has to be stitched from several days by guessing which
days belong together. Guessing from date gaps or row counts can merge two separate runs, so a value
from last week could sit beside one from today under one date.

Bodies holding several retailers (the Ulta + Sephora beauty body) also carried one `meta.fields`
and one `meta.capabilities` for the file: an OR-ed roll-up. When one retailer had promotions or a
regular price and the other did not, the other was shown as `ok` / `true` because of its neighbour.

## Decision
1. **A window is declared, never inferred.** The exporter takes `--run SOURCE=ID[+SEGMENT...]` for
   every exported source. A retailer's window is `CrawlWindow(run_id, segments, start, end)`, where
   `start`/`end` are the first and last capture of its offers. The run comes from the stored run
   id, so two runs on adjacent days are never merged. Without `--run`, a retailer whose values come
   from more than one run is refused ("one run per retailer"). With `--run`, a value from a run
   outside the declared set is refused, and the primary run must have a capture.
2. **Segments.** A crawl that was resumed under new run ids lists them as `segments`. The window
   covers the run and its segments (`run_ids`), and a segment may not repeat a run. Segments are the
   only way to put more than one run in a window, and they are named in the body.
3. **At most 4 Dubai calendar days** (`MAX_WINDOW_DAYS = 4`), counted first to last inclusive in
   the market's time zone. Exactly 4 passes; one minute past the 4th day fails.
4. **The declared exception to rule 6.** A windowed body keeps `meta.dates = (cutoff day,)` and
   publishes, for each offer, the **latest real in-window value** with its own `capturedAt`, even
   when that capture was on an earlier day of the window. This is not carry-forward. The value was
   observed inside the run that the body declares, and its `capturedAt` says when. A value from
   outside the window is never published: an offer with no in-window capture is `null`, not
   "removed" or "out of stock", and an offer missing on a later day of the crawl is not taken as
   out of stock either. Validation (`v3.py`) holds every observed offer's `capturedAt` to
   `[start, end]`.
5. **One observation per offer (stock option A).** Price and regular price always come together
   from the latest real capture in the window. Stock comes only from **the same run and the same
   Dubai day as `capturedAt`**: the latest real stock read that day. A blocked or `not_observed`
   read is skipped, never published as out of stock. With no real read that day, stock is `null`
   and is never borrowed from another day. `capturedAt` stays the price capture's time.
6. **Per-retailer states.** Every body the exporter writes carries `retailers[i].window`, `.fields`
   and `.capabilities`. One retailer's `regular`, `stock` or `promotions` never shows `ok` / `true`
   because of another. `compose.resolved_retailers` refuses a body of several retailers that lacks
   them; only a single-retailer body may fall back to its `meta`.
7. **Retained offers are marked and covered.** A listing seen in an earlier succeeded run, but with
   no capture in the window, is kept in the body with no value and `notObservedReason = retained`,
   from the closed set `retained | blocked | rate_limited | capture_in_progress |
   planned_not_captured`. Its `runId` must lie outside the window's `run_ids`. Every marked offer is
   covered by a `notObserved` entry for the same retailer, context, category and dates, and the
   exporter writes those entries. Retained fields roll up as `partial`. A marked offer without a
   window is refused. Early offers (captured before the window, unmarked) are exempt from the span
   but fail if their `runId` is one of the window's runs.
8. **A retailer with no window is not checked, and is withheld downstream.** A listed retailer with
   no rows in the export has `window = None`, and its offers keep the plain rule-6 meaning. Bodies
   exported before v3 have no window either. No cross-retailer comparison treats a missing window
   as a gap of 0 or falls back to `meta.asOf`. The stage/publish guard (01a11c71-37ee, Infra's
   deploy PR #304) serves a windowless retailer only as **withheld**, beside at least one windowed
   retailer and with disclosures that reach the set's last window day; a set where no retailer has
   a window is refused.
9. **Window gap across retailers (`WINDOW_GAP`).** A cross-retailer metric is computed only when the
   two sides' window **end** days are at most **7 Dubai days** apart (`compose.window_gap_days`;
   two windows ending on the same local day are 0 apart). Beyond that the metric is withheld with
   reason `WINDOW_GAP`, and the gap is always disclosed in the basis. The publish guard refuses a
   gap of 8 and passes 7.

## Consequences
- A multi-day crawl publishes its whole catalogue under one date, and every value says when it was
  captured. A one-day body publishes the same values as before; the only additions are the window
  and per-retailer state fields.
- **KNOWN GAP: stock has no time of its own.** Stock is from the same run and the same Dubai day as
  `capturedAt`, but its exact time within that day is not published. A consumer can rely on the
  date, never on the hour. A per-field `stockCapturedAt` is a follow-up task after the P0
  (01a11c6c-0d27). It is disclosed here rather than left silent.
- Re-exporting is required to get windows. An old body with no window can still be read, but it
  cannot be served alongside windowed bodies until it is re-exported.
- `--history` exports are unchanged and refuse `--run`: history is a daily series under rule 6.
