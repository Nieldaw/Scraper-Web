.PHONY: run test lint format collect-once db-up db-down migrate package

run:
	uvicorn immo_ne_collector.main:app --reload

test:
	pytest -q

lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check --fix src tests

collect-once:
	python -m immo_ne_collector.jobs.daily_collect

db-up:
	docker compose up -d db

db-down:
	docker compose down

migrate:
	alembic upgrade head

package:
	python scripts/build_package.py
