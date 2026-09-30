# sephora_snapshot

One-off Sephora UAE (`/ae-en`, `/ae-ar`) catalogue snapshot for the pilot (task 01a0f424-006c).
Ordinary access only (ADR-0005/0006):
- plain `httpx` with normal browser headers;
- sequential, ~1 req/s with jitter;
- no retries, no impersonation, no proxy.

A challenge or a 401/403 stops the whole job. Anything not fetched is absent, which the
loader treats as `not_observed`.

| Module | Role |
| --- | --- |
| `run.py` | Cloud Run job. Full mode: sitemaps -> EN PDPs -> tRPC stock -> AR PDPs, until `CUTOFF`. `PLAN=<object>`: a continuation run over a plan (tRPC unless `TRPC=0`, then the plan's AR PDPs). |
| `plan.py` | Builds a continuation plan from a finished snapshot folder: `--phase stock` (EN seeds, skips stock already read) or `--phase ar` (AR seeds, skips AR pages already fetched; run with `TRPC=0`). `--done` adds earlier continuation folders. |
| `load.py` | Idempotent load of a synced folder into `pi_db`. It keeps a part ledger, creates one `crawl_run` per language only once that language has rows, and `--finish` closes them. Only a complete full run is `succeeded`; PLAN and stopped runs are `partial`. |

Env for `run.py`:
- `BUCKET` (`file:<dir>` for local tests);
- `PREFIX`, `CUTOFF` (ISO-8601);
- optional: `PACE`, `LIMIT`, `TRPC`, `PLAN`.

Tests use synthetic payloads only (`tests/sephora_synth.py`).
