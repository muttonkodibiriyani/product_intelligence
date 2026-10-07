# Design: Similar / competing products (a separate signal, never an identity match)

| | |
|---|---|
| Status | Proposed (step 1 of 3); §5 decided by the coordinator on 2026-10-06. Design and a read-only coverage script only; no model, no pipeline, no API change. |
| Owner | Deep Coder |
| Code | `scripts/similar_coverage/coverage.py` (field coverage, aggregate counts only), tests in `scripts/similar_coverage/test_coverage.py` |
| Related | ADR-0012 (cross-file match edges: identity, which this is not); `docs/design/ml-layer.md`; `packages/pi_image` (SigLIP, CPU) |

## 1. What and why

Compare shows "no comparison" for many Ulta, Sephora and Faces products because exact pairs are
rare, and exact matching is a separate lane (ADR-0012, #232, #233). The owner also wants to see
how the three retailers **compete across different brands**: for a product at one retailer,
which products at the others are its closest alternatives by scent, look and price.

This is a **similarity** signal, not an identity:

- It is labelled **"Similar, not the same product"** wherever it is shown.
- It never becomes a `match_edge`, a `pi.matches/v1` edge or a `Product.matches` entry. It is
  never counted in compare, price gap, index, overlap or any match KPI. The metric layer counts
  only `approved` and `locked` identity edges (`COUNTED_STATES`) and never reads this signal.
- It never writes to `pi_db`, to the owner's Ulta rows or to `datasets/ae/beauty/latest.json`.
  Like the matches file, it is a separate per-scope file read at query time.

## 2. What the data holds today (from the code)

What each retailer could carry, per field, from a static read of the schema, exporter, loaders
and extractors. **Measured coverage on the live files is pending** (§6): only the owner can run
the script on the published copies, because this session's read of them was refused by a
classifier.

| Field | In `pi.dataset` | Ulta | Sephora | Faces |
|---|---|---|---|---|
| Name, brand, category path | v2, required | yes | yes | yes |
| Size `{value, unit}` | v2, optional | yes | yes | yes |
| Price series | v2 | yes | yes | yes |
| One image URL | v2 `offer.image` / `product.image` | yes | yes | yes (first only) |
| Gallery (several images) | v3 `content.images` | loader keeps it | loader keeps it | extracted; the feed keeps only the first |
| Description | v3 `content.description` | loader keeps it | loader keeps it | extracted; **dropped by the feed** (`pi_capture/feed.py:38-54`) |
| Concentration (EDP, EDT, …) | beauty@1 product attribute | NOT_PUBLISHED | not exported | extracted; dropped by the feed |
| Scent notes | **no field** | none | stored in labels (`c_notes`, `sephora_snapshot/load.py:340`); not exported | none |
| Scent family | **no field** (`fragrance_family` is in the capture registry; nothing fills it) | none | none | none |
| Gender | **no field** | none | none | extracted (`item_gender`); dropped by the feed |

Two consequences:

1. The published files the API serves are **v2** (the copies used for Insights are
   `pi.dataset/v2`). A v2 file carries no description and no gallery, so text similarity on the
   live data today can read only the **name and category**, plus a concentration parsed from the
   name (`pi_match.normalise.concentration`).
2. Notes, scent family and gender would need **export or feed changes** (Sephora `c_notes`, the
   Faces feed columns). Those are data artifact changes. §5 approves them as additive v2 fields,
   each in a separate small PR, with no v3 `content` republish. This design does not depend on
   them, but it gets much better with them.

## 3. Proposal

### 3.1 Candidates

For each product P, the candidates are products offered at **another** retailer (cross-retailer
only in v1, §5) that:

- share P's top-level category bucket (fragrance, makeup, skincare, hair, body; mapped from each
  retailer's own path);
- for fragrance, share P's **form** (eau, body mist, hair mist, oil, …) and, when both are
  known, its **concentration** (EDP with EDP). A concentration known on one side only is allowed
  and lowers the score (reason `concentration_unknown_one_side`);
- are not P itself under any identity: a candidate joined to P by an exact, family or
  substitute edge is shown in Compare, never in Similar.

Other brands are allowed and are the point; the same brand is allowed but flagged
(`same_brand`), so the UI can group by "other brands" first.

### 3.2 Score

Each modality gives a cosine or band score in `[0, 1]` and is **present** or **absent**. It is
never imputed:

| Signal | Input | Model / rule | Runs |
|---|---|---|---|
| `text` | name + category, plus description and notes when the file carries them | BGE-M3 dense (1024-d; the column `variant.text_embedding vector(1024)` already exists), multilingual (EN/AR) | locally on CPU, no API |
| `image` | the offer images | SigLIP base patch16-224, int8 ONNX (`pi_image.embed`, pinned revision) | locally on CPU |
| `price` | price per 100 ml or 100 g (`pi_match.unit_price`) in the same currency | band distance: same band 1.0, adjacent 0.5, else 0; bands are the retailer-neutral quantiles of the category | pure function |
| `attributes` | concentration, form, gender when known | agreement 1, unknown 0.5, conflict excludes | pure function |

`score = Σ wᵢ·sᵢ / Σ wᵢ` over the **present** signals only, with initial weights text 0.4,
image 0.3, price 0.2 and attributes 0.1. A pair needs at least **two present signals, one of
them text or image**; otherwise it is not emitted. The response lists which signals were
present, so a name-only similarity is never presented as a scent or look match. Weights and
thresholds change only with a version bump and a decision-log row, like `gatesVersion`.

### 3.3 Output

A per-scope file, `pi.similar/v1`, beside the matches file and read the same way:

```jsonc
{
  "schema": "pi.similar/v1",
  "meta": {"scope": "ae/beauty", "generatedAt": "…", "models": {"text": "BAAI/bge-m3@<rev>", "image": "siglip-base-patch16-224@<rev>"}, "weightsVersion": "…"},
  "similar": [
    {"product": "<id>", "retailer": "ulta_ae",
     "competitors": [
       {"product": "<id>", "retailer": "sephora_me", "score": "0.7400",
        "signals": {"text": "0.8100", "image": "0.6900", "price": "1.0", "attributes": null},
        "reasons": ["same_form:eau", "same_concentration:edp", "price_band:same", "other_brand"]}
     ]}
  ]
}
```

Top **k = 5** per other retailer. Scores are decimal text. Ids are the stable product ids, so
they resolve after a pair or split like every other id.

### 3.4 Quality

Before anything is shown, a small human evaluation: about 100 products stratified by
retailer and category, with each top-5 list judged "a plausible competitor: yes / no".
Precision@5 and the share of lists with at least one "yes" are reported per category. A
category below the bar (§5: precision@5 of at least 80%) is not shown. Agent labels alone are
not enough, as with auto-accept in ADR-0012.

### 3.5 Images and live traffic

Image similarity needs the image bytes. Fetching them from retailer image hosts is live traffic,
so it is phase 2 (§5): it goes through the Crawl Engineer and follows ADR-0006 (plain httpx,
≤1 request per second per host with jitter, no retry on a challenge). An existing cache is reused first. Without images, the
`image` signal is absent and §3.2 still holds.

## 4. Steps

1. **This PR.** The design and the coverage script. Owner run of the script on the published
   copies (§6).
2. **Pipeline PR.** A new `pi_similar` package (so `pi_match` stays stdlib-only): candidate
   generation, signals, scoring and the `pi.similar/v1` writer and reader. Synthetic fixtures,
   property tests (scores in `[0, 1]`; no identity edge ever emitted; absent signals never
   imputed; deterministic output), and a guard test that compare, index and insights give
   byte-identical output with and without a similar file. The models run behind an interface,
   so tests use fixed vectors and never download a model.
3. **API + FE.** `GET /api/v1/similar/{productId}` (API minor bump, coordinated at merge time)
   and a "Similar products at other shops" section on the product page, with the label, the
   per-signal chips and no price-gap number.

## 5. Decisions (coordinator, 2026-10-06)

1. **Data: yes.** Export Sephora `c_notes`, and the Faces description, gender and
   concentration columns that the capture already holds, as additive v2 fields. Each export is
   a separate small PR. Nothing else in `content` is republished.
2. **Images: text and price first.** The image fetch (§3.5) is phase 2: under ADR-0006 pacing,
   through the Crawl Engineer, with no new billable resource. Until then the `image` signal is
   absent.
3. **Model download: yes** for BGE-M3 (free, local). The weights go in `/dev/shm` or a cache
   path outside the repo and are never committed. Disk is checked first.
4. **Scope: cross-retailer only** for v1. Same-retailer competitors come later.
5. **The bar:** human precision@5 of at least 80% "plausible close competitor", on about 100
   products stratified by retailer and category. The owner may be asked to label a small
   sample. A category below the bar is not shown.

## 6. Coverage (pending the owner's run)

```sh
uv run python -m scripts.similar_coverage.coverage \
  <copy>/datasets/ae/beauty/latest.json <copy>/datasets/ae/faces_ae/latest.json > coverage.json
```

The script reads the files and prints **aggregate counts only** per retailer, for all offers
and for the fragrance subset. No name, description, URL or price is printed (a test pins this),
so the output can be pasted into this PR. A count a v2 file can't carry is `null`, not 0. The
counts cover concentration in the name, a concentration attribute, gender words, measured size,
priced, price per ml ready, category depth, image and, for v3, gallery, description, notes and
scent family words in the description, and the retailer family id. The table in §2 is filled
from that run, not from estimates.
