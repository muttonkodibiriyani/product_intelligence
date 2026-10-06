# P1 three-retailer Insights report

The P1 report at `/app/{locale}/insights/three/` is merged into `/app/{locale}/insights/`, which
covers every active shop with a shop selector (`?shop=<retailer>`). The old address redirects there.

The API contract is still pair-based (`/api/v1/insights?retailers=a,b`), so the page requests each
unordered pair of active shops and shows every pair on its own. This is not a three-way aggregate:
the page does not add, average, rank, or otherwise combine pair metrics. Every count is copied from
a governed API response and links to its evidence (Compare for a pair, Explore for a filtered list).
`unreviewed` matches remain visible as withheld and are never included in the counted value.

Stock-outs are counts per shop, never percentages or a ranking of shops. A whole brand the source
reports unavailable (an Ulta outage) is shown apart as "source reports unavailable", never as sold
out, and is left out of the headline count.

Retailer coverage comes from `/meta`. `partial`, `blocked`, and `pending` states are shown as
caveats rather than treated as complete. With fewer than two collected shops the page says so.
