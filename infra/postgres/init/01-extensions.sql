-- Runs once, on first start of an empty volume. Migrations also create the extension, so
-- this only makes `make db-shell` usable before the first `alembic upgrade`.
CREATE EXTENSION IF NOT EXISTS vector;
