# pi_image: image-similarity signal for the cross-retailer matcher

Image evidence for `pi_match` (spec doc 01a102ea-27e4, Signals 3; task 01a102ea-4f57). For each
retailer listing it fetches the primary packshot politely, hashes it (pHash, dHash), flags
placeholders and, optionally, embeds it with SigLIP on CPU. It then proposes cross-retailer
candidate pairs. Scoring belongs to the matcher. **Image evidence never overrides a hard rule**:
the same photo is reused across sizes, EDP vs EDT, minis and refills.

## Run

```sh
uv run pi-image refs --dataset beauty.json --dataset faces.json --out refs.jsonl
uv run pi-image run --refs refs.jsonl --cache /dev/shm/pi-image --out out/image   # fetch + hash
uv run pi-image run --refs refs.jsonl --cache /dev/shm/pi-image --out out/image \
    --offline --embed siglip                                                       # + embeddings
```

`--offline` reads the cache only. `--embed siglip` needs the `embed` extra (`onnxruntime`). On
first use it downloads `Xenova/siglip-base-patch16-224` `onnx/vision_model_quantized.onnx` from
Hugging Face at a pinned revision, and refuses a file whose SHA-256 differs. It costs nothing
and takes about 0.2 s per image on CPU.

## Fetching

- HTTPS on the approved image CDNs only (`img-product.sephora.me`, `media.alshaya.com`,
  `www.faces.ae`). A redirect anywhere else is refused.
- Ordinary browser headers through `pi_fetch`, at most 1 request per second per host (with
  jitter), and one sequential worker per host.
- A 429, a 403 refusal or a WAF challenge stops that host for the run. Such a block is not cached,
  and the run exits 1 and lists the host in `image_meta.json` under `stopped_hosts`. Nothing tries
  to get around a block.
- The cache lives at `<cache>/images/<h[:2]>/<h>.{json,img}` (h = SHA-256 of the URL). Final
  outcomes are cached (ok, 4xx, not an image, too large); 5xx and network errors are retried on
  a later run.

## Outputs (`--out`)

| file | content |
|---|---|
| `image_status.jsonl` | one `ListingImage` per listing: `ok`, `placeholder` (with its rule), `missing_image`, `fetch_failed` or `unreadable`, plus the hashes and the SHA-256 of the image bytes |
| `image_signals.jsonl` | `ImageSignal` candidate pairs, `left_source < right_source`: `phash_distance`, `dhash_distance`, `cosine` (4 dp, null without embeddings), `rank`, `via` (`phash`, `ann` or `both`), `left_image_sha`, `right_image_sha` |
| `alias_suggestions.jsonl` | image hits whose brand keys are both known and differ. These are for brand-alias review only and are never candidates |
| `image_meta.json` | tool version, refs SHA-256, model pin, k, thresholds, placeholder hashes, counts and stopped hosts |

A pair is proposed when its pHash distance is ≤ `--phash-max` (default 6), or when either side
is in the other's top `--k` (default 10) by cosine. Output is deterministic for the same refs
and cache.

## Placeholders

Placeholder, missing and failed images are **no evidence**: they take part in no pair. The rules are:

- `url_marker`: the file name says so (placeholder, no-image, coming-soon, and so on).
- `blank`: nothing but background, or a near-flat picture.
- `shared: N brands`: one retailer shows the same picture (pHash within 4 bits) for ≥3 brands.
  Counting happens inside one retailer, so one packshot listed under "YSL" and "Yves Saint Laurent"
  at two retailers is not flagged, and neither is one photo reused across the sizes of a product.
- `known`: close to a reference placeholder hash supplied by the caller.

## Hashing notes

Before hashing, images are normalised: alpha is flattened onto white, the uniform border is
trimmed and the result is padded to a white square. pHash compares the low 8×8 DCT block with
the mean of its AC terms rather than the median. On 180 real packshots that were re-encoded and
re-cropped, the median variant moved by up to 28 bits and the mean variant by at most 8.

No retailer image is committed (the repo is public). Tests use the synthetic packshots in
`tests/image_fixtures.py` and never call a live site.
