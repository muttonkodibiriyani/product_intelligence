# P1 three-retailer Insights report

The P1 report is available at `/app/{locale}/insights/three/` when three active retailers are
available. The current API contract is intentionally pair-based (`/api/v1/insights?retailers=a,b`),
so the page requests the three unordered pairs and renders them as separate evidence cards.

This is not a three-way aggregate. The page does not add, average, rank, or otherwise combine pair
metrics. Every count is copied from a governed API response, and every pair links to the existing
Compare evidence view. `unreviewed` matches remain visible as withheld and are never included in
the counted value.

Retailer coverage comes from `/meta`. `partial`, `blocked`, and `pending` states are shown as
caveats rather than treated as complete. If fewer than three supported/partial retailers exist, the
page explains why it cannot produce the report. Product images are not invented: they are only
shown by a future contract that supplies an approved image reference; this page currently exposes
the governed evidence link instead.

The three-retailer API contract can be introduced later as a separate reviewed change. Until then,
this shell provides the requested decision surface without promoting proposed or incomplete data.
