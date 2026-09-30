.PHONY: install lint format types test uat uat-status check up down db-shell emulators migrate

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

types:
	uv run mypy

# DB tests run against the local stack (`make up`); override PI_DATABASE_URL to point elsewhere.
PI_DATABASE_URL ?= postgresql+psycopg://pi:pi_local_only@127.0.0.1:55432/pi
export PI_DATABASE_URL

test:
	uv run pytest --cov --cov-report=term

# UAT scenarios only; filter by milestone with e.g. `make uat M=m1`.
uat:
	uv run pytest tests/uat -m "uat$(if $(M), and $(M))" -rxX

# Regenerate docs/requirements/uat_status.md after adding or implementing UAT cases.
uat-status:
	PYTHONPATH=tests uv run python -m uat.report

# Everything CI runs. Must pass before any PR is merged.
check: lint types test

# ---------------------------------------------------------------- local stack (blueprint §3.3)
# Reads ./.env when present (copy from .env.example); otherwise compose defaults apply.
COMPOSE := docker compose -f infra/docker-compose.yml $(if $(wildcard .env),--env-file .env)
FIREBASE_PROJECT := productintelligence-beeb3

up:
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

migrate:
	uv run alembic -c packages/pi_db/alembic.ini upgrade head

db-shell:
	$(COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# Emulators only (auth, firestore, storage); never deploys. Firestore and Storage emulators need Java 11+.
emulators:
	cd infra && firebase emulators:start --project $(FIREBASE_PROJECT) --only auth,firestore,storage
