.PHONY: install lint format types test uat uat-status openapi check up down db-shell emulators migrate test-db test-db-down

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

# DB tests run against a throwaway tmpfs server (`make test-db`), NEVER the stack database on
# 55432: tests create pi_test_* databases on that server. The root conftest.py refuses ports
# 55432/55499 and database `pi`. Pick a free port with TEST_DB_PORT=<port> on a shared host.
TEST_DB_PORT ?= 55433
PI_DATABASE_URL ?= postgresql+psycopg://pi:pi_test_only@127.0.0.1:$(TEST_DB_PORT)/pi_test
export PI_DATABASE_URL

test:
	uv run pytest --cov --cov-report=term

# UAT scenarios only; filter by milestone with e.g. `make uat M=m1`.
uat:
	uv run pytest tests/uat -m "uat$(if $(M), and $(M))" -rxX

# Regenerate docs/requirements/uat_status.md after adding or implementing UAT cases.
uat-status:
	PYTHONPATH=tests uv run python -m uat.report

# Regenerate the pi_api OpenAPI document and its golden responses after an intended change.
openapi:
	uv run pi-api openapi > docs/contracts/pi-api.openapi.json
	PI_API_REGENERATE=1 uv run pytest packages/pi_api/tests/test_contract.py --no-cov -q

# Everything CI runs. Must pass before any PR is merged.
check: lint types test

# ---------------------------------------------------------------- local stack (blueprint §3.3)
# Reads ./.env when present (copy from .env.example); otherwise compose defaults apply.
COMPOSE := docker compose -f infra/docker-compose.yml $(if $(wildcard .env),--env-file .env)
# One exact firebase-tools version everywhere (test_firebase_tools_pin.py scans all tracked files).
FIREBASE_TOOLS_VERSION ?= 14.27.0
# demo-* ids make the emulators refuse to reach any real Firebase project or credentials.
FIREBASE_PROJECT := demo-productintelligence

up:
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

migrate:
	uv run alembic -c packages/pi_db/alembic.ini upgrade head

# Disposable PostgreSQL 16 + pgvector for DB tests: data in tmpfs (RAM), gone on `make test-db-down`.
test-db:
	docker run -d --rm --name pi-test-db-$(TEST_DB_PORT) --tmpfs /var/lib/postgresql/data \
	  -p 127.0.0.1:$(TEST_DB_PORT):5432 -e POSTGRES_USER=pi -e POSTGRES_PASSWORD=pi_test_only \
	  -e POSTGRES_DB=pi_test pgvector/pgvector:pg16
	for i in $$(seq 60); do docker exec pi-test-db-$(TEST_DB_PORT) pg_isready -q -h 127.0.0.1 -U pi -d pi_test && exit 0; sleep 1; done; exit 1

test-db-down:
	docker rm -f pi-test-db-$(TEST_DB_PORT)

db-shell:
	$(COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# Emulators only (auth, firestore, storage); never deploys. Firestore and Storage emulators need Java 11+.
emulators:
	cd infra && npx -y firebase-tools@$(FIREBASE_TOOLS_VERSION) emulators:start --project $(FIREBASE_PROJECT) --only auth,firestore,storage
