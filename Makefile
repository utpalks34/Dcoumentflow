.PHONY: up down test lint eval-dev eval-ci eval-test migrate seed-demo report

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run ruff check .
	uv run mypy
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

# TR-ENV-03 targets below are wired as each phase adds the capability they
# depend on (docs/05_Phase_Plan.md). They fail loudly rather than pretend
# to run something that doesn't exist yet.

eval-dev:
	@echo "eval-dev: live DEV eval, uses API budget — not wired yet (Phase 1/2, docs/05_Phase_Plan.md)"; exit 1

eval-ci:
	@echo "eval-ci: replay-only DEV-subset eval — not wired yet (Phase 1, P1-T7)"; exit 1

eval-test:
	@echo "eval-test is GUARDED: TEST splits, never run without an explicit ask — not wired yet"; exit 1

migrate:
	@echo "migrate: Alembic migrations — not wired yet (later phase)"; exit 1

seed-demo:
	@echo "seed-demo: not wired yet (later phase)"; exit 1

report:
	@echo "report: not wired yet (later phase)"; exit 1
