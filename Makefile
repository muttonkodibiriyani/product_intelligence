.PHONY: install lint format types test check

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
