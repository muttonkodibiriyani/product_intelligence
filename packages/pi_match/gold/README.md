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
