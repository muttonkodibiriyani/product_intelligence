# Demo dataset exporter

This read-only script converts the latest AED observations in a local `pi_db` into the
frontend's `pi.dataset/v1` snapshot. It performs no retailer or Algolia requests.

The export grain is product family × pack size. Shade variants collapse into one offer and
the representative variant is the lowest-priced in-stock variant (or the lowest-priced
variant when stock is unknown). Current match edges pair Ulta and Sephora groups greedily by
highest confidence; excess many-to-one edges remain unmatched.

Run from the repository root:

```sh
uv run python scripts/demo_export/export.py \
  --database-url "$PI_DATABASE_URL" \
  --output "$OUTPUT_PATH" \
  --ulta-recon-observed-count 3 \
  --ulta-recon-source 'docs/recon/gulf_probe_results.md (PR #15 @ 1056679)'
```

Inputs are the read-only local `pi_db` URL plus optional reviewed Ulta recon metadata. The single
output is the plain JSON file at `OUTPUT_PATH`; use a scratch path outside the repository. This is
a one-shot command: it reads each UAE source context's newest crawl run, writes atomically, prints
the cutoff and SHA-256, then exits. It never polls or waits for a crawl.

Only after the reviewed Ulta fixture is present on `main`, an early recon sample may be added:

```sh
uv run python scripts/demo_export/export.py \
  --database-url "$PI_DATABASE_URL" \
  --output "$OUTPUT_PATH" \
  --ulta-early-fixture /path/to/committed/ulta_ae_pdp_trimmed.html \
  --ulta-captured-at 2026-09-30T20:42:00Z \
  --ulta-fixture-commit <main-commit-containing-reviewed-fixture> \
  --ulta-recon-observed-count 3 \
  --ulta-recon-source 'docs/recon/gulf_probe_results.md @ <main-commit>'
```

The three Ulta fixture arguments are optional and must be supplied together. Only use a fixture
that is present on `main` after its redaction and robots review; the commit is embedded in the
evidence label. If that review has not merged, omit the fixture. The timestamp must be the capture
time, not the export time. Fixture observations are marked `early: true`; real Ulta rows loaded
into `pi_db` are exported normally and inherit the source's partial/complete status. Recon samples
are excluded from product coverage, matching and price comparison totals. The recon observed count
is never inferred: when supplied, it must include the report path and commit as its source.

The exporter reads money as `Decimal` and accepts AED values with at most two fractional digits.
The final JSON uses JSON numbers because JSON has no decimal scalar; values are never emitted as
strings or synthesized from missing data. Only observations from each UAE source context's newest
crawl run are exported, so an older observation cannot appear under the current cutoff date.

Validate the result with the frontend-owned validator before handoff:

```sh
node /path/to/contract/validate.js /path/to/dataset.json
```
