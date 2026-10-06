# capture_read — saved pages to readings, inside the bucket's region

A Cloud Run job (also runs locally) that turns a `page_capture` run's saved pages into
`pi_capture` readings. It reads the run's page rows, opens each saved page, checks it against the
sha256 the row recorded, and runs the reader for the row's retailer. It writes one
`ProductCapture` JSON line per product row. Landmark pages give one row per variant.

It fetches nothing from any retailer and has no proxy. Every byte it reads comes from our own
bucket, so it runs in the bucket's region to avoid egress charges.

## Environment

| Variable | Meaning |
| --- | --- |
| `BUCKET` | GCS bucket name, or `file:<dir>` for a local run |
| `SRC_PREFIX` | the capture run's prefix, e.g. `uae_groups/wave1-20261003` |
| `LOCALE` | read only page rows with this locale, e.g. `en-AE` |
| `CAPTURE_EGRESS` | egress label of the capture run, recorded on every capture |
| `RETAILERS` | optional comma list; read only these retailers |
| `OUT` | output folder under the prefix; default `readings` |
| `CLOUD_RUN_TASK_INDEX` / `CLOUD_RUN_TASK_COUNT` | parts are split by a stable hash of their name |

## Output under `<SRC_PREFIX>/<OUT>/`

- `<part>.jsonl.gz` holds the readings for one input part. It is written only after the whole part is
  read, so a rerun skips parts already present and picks up parts a running capture added later.
- `errors/<part>.jsonl.gz` lists each page that gave no readings, with its state and reason:
  `sha_mismatch`, `not_product`, `reader_error` or `no_rows`.
- `status.t<N>.json` holds the task's counts.

## Readers

Centrepoint, Splash, Babyshop, Home Centre and Max use `pi_capture.landmark`. Faces uses
`pi_capture.faces`. Every other retailer uses the generic readers.
