# Image-similarity evidence (UAE catalogue, 2026-10-04)

This report evaluates `pi_image` as a **candidate signal**, not a match decision. Image evidence
never overrides brand, size, concentration, shade, refill, set or other hard rules. Cross-brand
hits remain alias suggestions for human review only.

## Reproducible inputs and run

- 18,261 listing refs; refs SHA-256
  `26dbb9ac69df92062819a5a898c12cba33bb03c08f56451ad6363dd64dae56f1`.
- 18,008 eligible unique URLs fetched from the three approved CDN hosts at no more than one
  request/second/host: 18,000 images and 8 final Faces 4xx responses. `stopped_hosts` was empty.
  One repeated `image unavailable` URL marker was deliberately not fetched.
- SigLIP model `Xenova/siglip-base-patch16-224`, revision
  `4649052661e53c7000355844105f8a1792088239`, quantised ONNX SHA-256
  `ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058`.
- Final gates: pHash <= 6 **and** dHash <= 8 for near-duplicates; top-10 SigLIP ANN in both
  directions; cosine >= 0.95 for ANN-only cross-brand alias suggestions.

The final run produced 39,229 same/unknown-brand candidates and 1,168 cross-brand review-only
alias suggestions. Its per-source image outcomes were:

| Source | OK | Placeholder | Missing/fetch failed |
|---|---:|---:|---:|
| Faces | 1,357 | 92 | 8 |
| Sephora | 8,702 | 827 | 0 |
| Ulta | 6,689 | 545 | 41 |

All 1,464 placeholder listing rows were excluded from both candidate outputs; an explicit audit
found zero placeholder leaks.

## Threshold evidence

The hash calibration used existing adjudicated gold only. `unsure` rows are reported but excluded
from precision denominators. “Strict” means gold `exact`; “useful candidate” means `exact`,
`family` or `related` rather than `different`.

| dHash max (pHash <= 6) | Rows | Exact / decidable | Strict precision (Wilson 95%) | Useful precision (Wilson 95%) |
|---:|---:|---:|---:|---:|
| 4 | 1,362 | 180 / 205 | 87.80% [82.62%, 91.60%] | 100% [98.16%, 100%] |
| **8** | **1,627** | **188 / 227** | **82.82% [77.38%, 87.17%]** | **100% [98.34%, 100%]** |
| 12 | 1,735 | 188 / 228 | 82.46% [76.99%, 86.84%] | 100% [98.34%, 100%] |

dHash 8 retains every exact hit found at 12 while removing 108 rows; dHash 4 loses eight exact
hits. That is why 8 is the default.

The gold set has no pair whose two normalised brand keys differ, so it cannot support an honest
alias precision estimate. A broad calibration pass contained 229,658 raw cross-brand top-k hits;
cosine 0.95 plus the hash gate reduced that to 1,529 review rows. The complete final run produced
1,168. This threshold controls review volume only; aliases are never candidates or auto-accepted.

## Incremental yield beyond name/brand blocking

The blocking input contained 5,000 pairs and the fixed adjudicated gold contained 972 pairs.
The table separates total machine yield from what is actually human-labelled. “Useful precision”
is calculated only on the incremental rows intersecting gold; unseen catalogue rows are not
silently labelled.

| Retailer pair | Image candidates | Beyond blocking | Extra gold exact | Incremental useful / decidable | Useful precision (Wilson 95%) | Strict exact precision (Wilson 95%) |
|---|---:|---:|---:|---:|---:|---:|
| Faces-Sephora | 15,770 | 14,442 | **3** | 52 / 53 | 98.11% [90.06%, 99.67%] | 5.66% [1.94%, 15.37%] |
| Faces-Ulta | 7,438 | 6,864 | **0** | 48 / 48 | 100% [92.59%, 100%] | 0% [0%, 7.41%] |
| Sephora-Ulta | 16,021 | 14,214 | **2** | 23 / 23 | 100% [85.69%, 100%] | 8.70% [2.42%, 26.80%] |

Thus image similarity adds five confirmed exact pairs in the existing gold: three
Faces-Sephora and two Sephora-Ulta. It also creates a large review/blocking surface of
family/related and unlabelled rows; matcher hard rules must classify or reject those rows.

## Human-review packet

The stratified packet contains 313 rows:

- 135 rows already adjudicated in gold: 5 exact, 2 family, 116 related, 1 different, 11 unsure.
- 178 unseen rows (108 normal candidates, 70 aliases) are explicitly review-only and
  human-validated: 177 exact and one different. None may become auto-accepted products,
  and aliases remain review-only.
- Machine evidence (`same_bytes`, pHash/dHash gate, cosine, rank and route) is nested separately
  from `human_label`. The attestation is recorded in `approval.json` with source message
  `01a1055c-65e9-7953-a3ba-e9c8f8a765af`; the explicit exceptions and correction are from
  `01a10562-2264-77d6-abd0-cfe3c3466630` and `01a10564-5969-71a6-afba-f03f831a4379`.

The Shiseido case demonstrates the boundary: Sephora `s-P10058416-150-ml` vs Ulta
`u-UB0000007780-150-ml` has pHash 0, dHash 1, cosine 0.9870 and rank 1, but remains gold
`unsure` because “Blue Expert” vs “Expert Sun” may be a rename or reformulation.

Generated artifact SHA-256 values (artifacts are intentionally not committed because they contain
catalogue metadata and image URLs):

| Artifact | SHA-256 |
|---|---|
| `image_meta.json` | `75a1095c8ece2fb6a7abc45d807df9d55bb3829f0efa385772131c077e15889e` |
| `image_status.jsonl` | `975a1c644af96911fd625e7d5bc50fdda02832d16ca76ee388bcc02e23b1f131` |
| `image_signals.jsonl` | `3593f987f7ec22b1956f5b265333990b7a893dc400e8aacf520195a967ae73e9` |
| `alias_suggestions.jsonl` | `4d5f955b4ee78ed3e6c82495559103112eec84d56bc877e35a5dd8afd1c1080a` |
| enhanced `summary.json` | `2256b8c96f953be5b5aab6df62fa04a748b6504e57c3be79e4912d8b52d9a7bd` |
| `review_sample.jsonl` (owner labels) | `0bb6ebbd03efedfdedb4c6b5fbdb0b362a92bb5e8e6bfa1fe8243799a12e15c9` |
| `approval.json` | `233a21e485f110e6111dd904706548a6569e364ebbca7f834f272178fb97d16b` |
| `top_candidates.jsonl` | `668c9e8d00bdc9c868434d684618311131d9f9a65a1060e2c63e4e3e7df420ac` |
