# Contributing

## Workflow

1. Branch from latest `main`: `feat/…`, `fix/…`, `chore/…`, `docs/…`. One concern per branch.
2. Keep PRs small. Fill in the PR template (requirement IDs, tests, cost impact).
3. Run `make check` locally before pushing. It runs exactly what CI runs.
4. Conventional commit style for the squash message, e.g. `feat(pi_fetch): add block detection`.

## Merge rules (always, no exceptions)

GitHub Free private repositories do not enforce branch protection, so these rules are enforced
by whoever merges:

1. **Rebase on the latest `main`.** Conflicts are resolved on the branch, never on `main`.
2. **CI must be fully green on the rebased head**: ruff lint, ruff format, mypy `--strict`,
   pytest with coverage ≥ 85 %, secret scan.
3. If `main` moved after CI started (another PR merged), rebase again and wait for green again.
4. **Squash merge**, then delete the branch.
5. Nothing is pushed directly to `main`.

## Quality bar

- Zero lint and type errors; tests type-checked too.
- New behaviour ships with tests; bug fixes ship with a regression test.
- Money is `Decimal` + currency; never floats.
- Persisted enum values are never renamed without a migration.
- No secrets in the repository: use Secret Manager or local, git-ignored files.
- Any new paid resource (Cloud SQL tier, proxy, etc.) needs owner approval noted in the PR.

## Definition of done

Code, tests and docs; CI green; `docs/requirements/traceability.csv` updated when a
requirement's status changes; Arabic RTL checked for UI work.
