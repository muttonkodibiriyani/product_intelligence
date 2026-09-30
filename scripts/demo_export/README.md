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
  --database-url 'postgresql+psycopg://pi:pi_local_only@127.0.0.1:55432/pi' \
  --output /path/in/your/scratch/dataset.json \
  --ulta-early-fixture /path/to/committed/ulta_ae_pdp_trimmed.html \
  --ulta-captured-at 2026-09-30T20:42:00Z
```

The Ulta fixture arguments are optional and must be supplied together. They are intended only
for committed, redacted captures approved for the demo. The timestamp must be the capture time,
not the export time. Ulta observations are always marked `early: true` while Ulta is blocked.
They are recon samples only: the frontend excludes them from product coverage, matching and price
comparison totals. The retailer note separately reports the three products observed during recon
and zero Ulta products loaded into `pi_db`.

Validate the result with the frontend-owned validator before handoff:

```sh
node /path/to/contract/validate.js /path/to/dataset.json
```
