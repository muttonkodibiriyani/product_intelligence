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

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker (for the local stack, later PRs).

```bash
make install   # uv sync
make check     # ruff + mypy --strict + pytest with coverage — same as CI
```

## Repository layout

```
packages/        Python packages (uv workspace)
  pi_core/       shared domain model: enums, money, context
docs/            blueprint, ADRs, requirement traceability, runbooks
.github/         CI workflows and PR template
```

Further packages (`pi_fetch`, `pi_connectors`, `pi_images`, `pi_normalize`, `pi_quality`,
`pi_match`, `pi_pipeline`), the database, semantic layer and web app arrive in the PRs
listed in blueprint section 16.

## Status

M0 · Foundation — in progress.
