# Product Intelligence

Competitive product and price intelligence platform. It collects complete public
catalogues (every product, variant, visible field and image), keeps an append-only
history, matches identical and comparable products, and serves image-first analytics,
a comparison board and an AI assistant behind a login.

**Pilot:** Ulta Beauty vs Sephora · KSA (fallback UAE) · 2026.

- Full design: [`docs/blueprint.md`](docs/blueprint.md)
- Short architecture overview: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- How we work (PRs, CI gates, merge rules): [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Decisions: [`docs/adr/`](docs/adr)
- Requirement traceability: [`docs/requirements/traceability.csv`](docs/requirements/traceability.csv)

## Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker, and for the emulators the
[Firebase CLI](https://firebase.google.com/docs/cli) plus Java 11+.

```bash
make install     # uv sync
make test-db     # throwaway tmpfs PostgreSQL for DB tests on 127.0.0.1:55433 (TEST_DB_PORT=…)
make check       # ruff + mypy --strict + pytest with coverage — same as CI
make test-db-down

cp .env.example .env   # optional: override ports/credentials (git-ignored)
make up          # PostgreSQL 16 + pgvector on 127.0.0.1:55432 (waits until healthy)
make db-shell    # psql into the local database
make emulators   # Firebase auth/firestore/storage emulators, UI on http://127.0.0.1:54000
make down        # stop the stack; data stays in the pi_pgdata volume
```

Local stack ports (all bound to `127.0.0.1`):

| Service | Port |
|---|---|
| PostgreSQL + pgvector | 55432 |
| Auth emulator | 59099 |
| Firestore emulator | 58080 |
| Storage emulator | 59199 |
| Emulator UI | 54000 |
| Emulator hub | 54400 |
| Emulator logging | 54500 |

The emulators run against the demo project id `demo-productintelligence` in single-project
mode. A `demo-*` id has no cloud counterpart, so the emulators cannot reach the real
`productintelligence-beeb3` project or use real credentials. Dagster and Cube join
`infra/docker-compose.yml` in later PRs.

## Repository layout

```
packages/        Python packages (uv workspace)
  pi_core/       shared domain model: enums, money, context
infra/           docker-compose (local stack), Firebase emulator config
docs/            blueprint, ADRs, requirement traceability, runbooks
.github/         CI workflows and PR template
```

Further packages (`pi_fetch`, `pi_connectors`, `pi_images`, `pi_normalize`, `pi_quality`,
`pi_match`, `pi_pipeline`), the database, semantic layer and web app arrive in the PRs
listed in blueprint section 16.

## Status

M0 · Foundation — in progress.
