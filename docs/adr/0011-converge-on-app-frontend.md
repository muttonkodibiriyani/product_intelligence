# ADR-0011: One front end, the API-backed `/app`

- Status: accepted. Owner decision relayed by the coordinator on 1 Oct 2026.
- Date: 2026-10-01
- Drafted by: the coordinator. Every item below is the owner's decision, as given in the owner chat, including drill-down, cross-filtering, the "Ryzan AI Assistant" name and copying MIT components into the repo.

## Context
Two web front ends ship from the same Hosting site:

- `/` is the v3 static dashboard (`apps/web/src/`). It reads the dataset file from Storage
  directly. Pages: Dashboard (Leadership summary and Pricing desk presets), Explorer, Pricing,
  Promotions, Assortment, Availability, Compare, Assistant, Coverage & health.
- `/app` is the Next.js app (`apps/web/app/`). It reads only `GET /api/v1/*`. Pages: landing,
  Explore, Product, Compare, Promotions, Launches.

The owner opens `/`, so fixes made only in `/app` did not reach the first screen. Two front ends
double the work for every page, and the static one bypasses the API's caveats, withholding and
auth checks.

## Decision
Converge on `/app` and retire the static dashboard. Every step keeps the demo working:

1. **1 Oct (today's deploy).** Fix `/`, the page the owner sees:
   - every tab leads with widgets that have real data;
   - widgets still waiting on data go into one compact "Coming as data arrives" strip below the
     fold;
   - Sephora and Ulta thumbnails.

   `/` stays read-only on the dataset file, with no data or format change. `/app` ships from #106.
2. **Every-page pass on `/app`.** Port the static pages into `/app`, with drill-down on every chart
   element, cross-filtering, and the "Ryzan AI Assistant" UI.
3. **Parity.** When `/app` covers every static page, `/` redirects to `/app` and
   `apps/web/src/` is removed, along with its build-reproduction check.

Tooling:
- ECharts stays the only chart library.
- Tremor and shadcn/ui are design references only. MIT-licensed components may be copied into the
  repo with their licence notices kept, with no CDN and no runtime fetches outside our API, keeping
  the CSP intact.
- Google Stitch is for layout mockups only, and no real data is sent to it.

## Consequences
- No new features land in `apps/web/src/` after step 1, only fixes needed to keep the demo working.
- Honesty rules apply to both front ends:
  - no empty hero cards;
  - no trend from fewer than two dates;
  - no invented discounts;
  - data cutoff and source are labelled.
