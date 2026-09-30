.PHONY: install lint format types test check up down db-shell emulators

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

test:
	uv run pytest --cov --cov-report=term

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

db-shell:
	$(COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# Emulators only (auth, firestore, storage); never deploys. Firestore and Storage emulators need Java 11+.
emulators:
	cd infra && firebase emulators:start --project $(FIREBASE_PROJECT) --only auth,firestore,storage
