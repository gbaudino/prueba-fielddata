.PHONY: sync check fix test coverage build start stop restart db-init test-db \
		migrate-up migrate-down migrate-create worker-once

sync:
	uv sync --locked
	uv run pre-commit install

check:
	uv run ruff format --check
	uv run ruff check
	uv run mypy src tests

fix:
	uv run ruff format
	uv run ruff check --fix

test: test-db
	uv run pytest $(ARGS)

coverage: test-db
	uv run pytest --cov --cov-report=term-missing $(ARGS)

test-db:
	docker compose up -d --wait db

build:
	docker compose build

start: build migrate-up
	docker compose up -d api worker

stop:
	docker compose down

restart: build
	docker compose up -d --force-recreate --remove-orphans api worker

db-init:
	docker compose up -d --wait db
	uv run python -m scripts.seed_db

migrate-up: db-init
	docker compose run --rm --no-deps api alembic upgrade head

migrate-down:
	docker compose run --rm --no-deps api alembic downgrade -1

migrate-create:
	@test -n "$(NAME)" || (echo "Usage: make migrate-create NAME=initial_schema" && exit 1)
	docker compose exec -T --user "$$(id -u):$$(id -g)" api alembic revision --autogenerate -m "$(NAME)"
	uv run ruff format src/agroclimate/db/migrations/versions
	uv run ruff check --fix src/agroclimate/db/migrations/versions

worker-once: build migrate-up
	docker compose run --rm --no-deps worker python -m agroclimate.worker --once
