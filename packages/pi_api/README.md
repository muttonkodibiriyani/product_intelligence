# pi_api

The read-only service layer (design: `docs/design/service-layer.md`). It serves `pi.dataset/v2`
snapshots through `pi_metrics`. Clients never compute metrics themselves.

- Every route, unknown paths included, needs `Authorization: Bearer <Firebase ID token>` with a
  `role` claim (`viewer` or `admin`). Cookies are ignored. Every response is
  `Cache-Control: private, no-store`.
- The contract is `docs/contracts/pi-api.openapi.json`, with golden responses in
  `docs/contracts/golden/pi-api/`. Regenerate both with `make openapi`.

| Env var | Meaning |
|---|---|
| `PI_API_FIREBASE_PROJECT` | Firebase project id (token `aud` and issuer) |
| `PI_API_DATASETS` | Comma-separated objects, e.g. `datasets/uae/latest.json` (gzip is detected) |
| `PI_API_BUCKET` / `PI_API_LOCAL_DIR` | Exactly one: the GCS bucket, or a local directory for dev |
| `PI_API_REFRESH_SECONDS` | Generation check interval (default 60) |
| `PI_API_RATE_PER_SECOND`, `PI_API_RATE_BURST` | Per-uid token bucket per instance (10, 30) |
| `PI_API_ALLOW_TEST` | `1` serves `meta.test` (synthetic) datasets; off by default |

Run locally: `PI_API_LOCAL_DIR=... uv run uvicorn --factory pi_api.app:app_from_env`.
Image: `docker build -f packages/pi_api/Dockerfile -t pi-api .` (from the repo root).
