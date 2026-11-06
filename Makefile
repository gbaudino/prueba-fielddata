.PHONY: sync check fix test coverage build start down restart \
        migrate-up migrate-down migrate-create

# Dependencies
sync:
	uv sync --locked

# Code quality
check:
	uv run ruff format --check
	uv run ruff check
	uv run mypy src tests

fix:
	uv run ruff format
	uv run ruff check --fix

# Tests
test:
	uv run pytest $(ARGS)

coverage:
	uv run pytest --cov=agroclimate --cov-report=term-missing $(ARGS)

# Docker
build:
	docker compose build

start:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose up -d --build --force-recreate --remove-orphans

migrate-up:
	docker compose exec -T api alembic upgrade head

migrate-down:
	docker compose exec -T api alembic downgrade -1

migrate-create:
	@test -n "$(NAME)" || (echo "Usage: make migrate-create NAME=initial_schema" && exit 1)
	docker compose exec -T --user "$$(id -u):$$(id -g)" api alembic revision --autogenerate -m "$(NAME)"