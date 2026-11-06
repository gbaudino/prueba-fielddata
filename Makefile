.PHONY: sync check fix test coverage build start down restart \
		migrate-up migrate-down migrate-create

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

test:
	uv run pytest $(ARGS)

coverage:
	uv run pytest --cov=agroclimate --cov-report=term-missing $(ARGS)

build:
	docker compose build

start: build
	docker compose up -d

down:
	docker compose down

restart: build
	docker compose up -d --force-recreate --remove-orphans

migrate-up:
	docker compose exec -T api alembic upgrade head

migrate-down:
	docker compose exec -T api alembic downgrade -1

migrate-create:
	@test -n "$(NAME)" || (echo "Usage: make migrate-create NAME=initial_schema" && exit 1)
	docker compose exec -T --user "$$(id -u):$$(id -g)" api alembic revision --autogenerate -m "$(NAME)"
