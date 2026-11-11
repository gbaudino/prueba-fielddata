.PHONY: sync check test coverage build db schema migrate seed start stop reset demo worker-once fix

sync:
	uv sync --locked
	uv run pre-commit install

check:
	uv run ruff format --check
	uv run ruff check
	uv run mypy src tests scripts

fix:
	uv run ruff format
	uv run ruff check --fix

test: db
	ENVIRONMENT=test uv run pytest $(ARGS)

coverage: db
	ENVIRONMENT=test uv run pytest --cov --cov-report=term-missing $(ARGS)

build:
	docker compose build

db:
	docker compose up -d --wait db

schema: db
	uv run python -m scripts.create_external_tables

migrate: schema
	docker compose run --rm --no-deps api alembic upgrade head

seed: schema
	uv run python -m scripts.seed_db

start: build migrate
	docker compose up -d api worker

stop:
	docker compose down

reset:
	docker compose down -v

demo: seed
	uv run python -m scripts.demo

worker-once:
	docker compose run --rm --no-deps worker python -m agroclimate.worker --once
