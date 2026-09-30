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
| `load.py` | Idempotent load of a synced folder into `pi_db`. It keeps a part ledger, creates one `crawl_run` per language only once that language has rows, and `--finish` closes them. `succeeded` is strict: `mode=full`, `limit=0`, `trpc=true`, `stopped=complete`, every seeded page and stock read done with no block, 429, transport, HTTP or parse skip. Everything else, including every PLAN run, is `partial`. Prices are parsed as exact decimals, and a price without a currency is stored as `unknown`, never AED. |

Env for `run.py`:
- `BUCKET` (`file:<dir>` for local tests);
- `PREFIX`, `CUTOFF` (ISO-8601);
- optional: `PACE` (>= 1.0 s, enforced), `LIMIT`, `TRPC`, `PLAN`.

`progress.json` records `mode`, `limit` and `trpc`.

Off-peak window: runs are scheduled in the UAE night, 18:00Z-02:00Z (22:00-06:00 Gulf time), and `CUTOFF` must fall inside it. Longer passes are split across nights, and each continuation excludes work already done (`plan.py --done`). The single exception was the owner-approved first snapshot (execution `9drcr`, 2026-09-30/10-01): it ran to its own 03:20Z cutoff.

A stock-read variant with no `inStock` value is not recorded as an observation; it is counted as `trpc_instock_unknown`.

Tests use synthetic payloads only (`tests/sephora_synth.py`).
