# Gold set (ADR-0012 §8)

`sample-v1.json` (`pi.gold-sample/v1`): 972 listing pairs across ulta_ae, sephora_me and
faces_ae (435 ulta–sephora, 277 faces–sephora, 260 faces–ulta). They were sampled on
2026-10-03 from the matcher's candidates over the published source files, stratified by
retailer pair, score band and category.

- **Labels:** exact 436, related 318, family 94, unsure 107, different 17.
- **Labelling:** two labellers labelled blind from saved evidence (names, URL slugs, sizes,
  images): Quill (Matching Scientist) and the Extraction Verifier. Agreement was 0.867, with
  Cohen's kappa 0.80 over five classes and 0.89 for exact vs not
  (`agreement.txt`). All 129 disagreements were adjudicated, and both adjudication logs are
  kept (`adjudication-*.jsonl`).
- **Rulings applied:**
  - Either labeller unsure ⇒ unsure.
  - A multi-shade parent listing with the shade unobserved is never exact.
  - A set, duo or coffret is related to its single, never exact or family.
  - A name/slug conflict is unsure.
  - Shiseido Blue Expert vs Expert Sun stays unsure until an image check.
- **Limits:**
  - Both labellers are agents. ADR-0012 §8 lets no agent-only labels enable auto-accept,
    so auto-accept stays off until a human confirms the labels.
  - The v1 rules were tuned with all of v1 in view, so the hash-chosen held-out third is
    reported apart but is not a clean hold-out. Gold v2, sampled from the matcher's own
    outputs, will be.

`baseline.json` pins `[right, total]` per emitted class and category. `test_gold.py` fails
when precision or the Wilson 95% lower bound falls below it. Re-pin it with
`uv run python -m pi_match.gold --write`, and only with the Reviewer's written approval.

## Image packet (`sample-v2-images.json`)

`sample-v2-images.json` (`pi.gold-sample/v1`, `source: image-packet-i3`) holds the 313-row
stratified image packet from the pi_image i3 run (#227, `packages/pi_image/EVIDENCE.md`).
`packet_sha256` pins the input. Each row keeps its image evidence (`image_evidence`: pHash and
dHash distance, cosine, rank, route).

- **`pairs` (137 labelled):**
  - 135 rows that were already in v1. Each v1 pair is copied with its label unchanged (`v1_id`).
    These are the v1 adjudicated labels, not new owner labels, so `disagreements` is empty.
    `sample-v1.json` is not edited.
  - 2 rows the owner labelled one by one (`labeller: owner`, message
    `01a10562-2264-77d6-abd0-cfe3c3466630`): one exact and one different (a refill vs its EDP).
- **`pending_owner_review` (176, `label: null`):** a bulk approval for #227 review-only
  suggestions, not identity labels. A heuristic pass over their names and sizes finds 67 with
  different sizes, 83 with different concentration words (EDT vs Parfum), 13 with a set, mini or
  refill on one side only, and some unrelated products. `review_hints` carries those flags for
  a per-row owner review. These rows count toward nothing: not ADR-0012 §8, and not
  `baseline.json`.
- **Limits:** the packet was drawn by the image signal itself (177 machine "exact" against
  1 "different" before review). It measures the image gate's precision, not recall and not
  negatives, and it is not a clean hold-out for the name rules.
- **What the labelled rows show:** of the 137 rows, 40 pass the image gate (pHash ≤ 6 and
  dHash ≤ 8, or cosine ≥ 0.95). Their exact precision is 6/34 decidable (17.6%, Wilson 95%
  8.3–33.5%; fragrance 4/27). As a same-line signal (exact, family or related) the figure is
  33/34 (Wilson 85.1–99.5%). Packshots are shared across sizes, concentrations and refills, so
  an image can queue a pair for review but never decide identity.
- **Provenance of `ulta_ae` rows:** they come from the owner-loaded combined data already
  in the packet. They are read only, never taken from the scraped feed, and no Ulta listing is
  changed.
- **No auto-accept:** auto-accept stays off. The two owner labels are human labels under
  ADR-0012 §8, but enabling auto-accept is not decided here.
