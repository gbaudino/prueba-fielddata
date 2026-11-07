# AGENTS.md

## Project overview

Agroclimate is a technical challenge for FieldData: a weather alert system for agricultural fields.

Users configure alerts for their fields based on weather event types and probability thresholds. A background process periodically evaluates stored weather forecasts and generates notifications when configured thresholds are exceeded.

The existing weather ingestion process is outside the scope of this challenge. Weather forecast data must be mocked.

WhatsApp integration is explicitly out of scope. The implementation should focus on the REST API, background evaluation and notification generation.

## Technology stack

- Python 3.14
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x (async)
- Alembic
- Pydantic Settings
- Docker and Docker Compose
- uv
- Pytest
- Ruff
- Mypy
- pre-commit
- Conventional Commits

## Engineering principles

Production readiness is a primary requirement.

Prioritize:

- Correctness and data integrity.
- Reliability and predictable behavior.
- Maintainability and readability.
- Explicit error handling.
- Type safety.
- Testability.
- Security and safe handling of sensitive information.
- Observability.
- Reproducible builds and deployments.

Prefer simple, explicit and maintainable solutions over unnecessary abstractions.

Do not sacrifice correctness or reliability for implementation speed.

Avoid overengineering. Every abstraction, dependency and architectural decision should have a clear justification.

## Project structure and conventions

- Follow the existing `src/agroclimate` package structure.
- Keep the existing separation of API, core configuration and database concerns.
- Log with structlog using structured key-value events (`logger.info("alert_sent", alert_id=...)`), never f-strings or `print`. Never log secrets or personal data. Logging is configured only in `core/observability.py`.
- Do no work at import time (reading settings, creating engines, opening connections). Build the application with `create_app()`.
- Introduce new modules and directories only when they are needed.
- Use Python 3.14 and modern, idiomatic Python.
- Follow PEP 8 and the Ruff configuration in `pyproject.toml`.
- Use type annotations consistently.
- Prefer `Annotated` for FastAPI dependencies.
- Keep HTTP concerns separate from business logic.
- Separate request/response schemas from persistence models.
- Do not introduce repository, service or factory abstractions without a concrete reason.
- Keep modules focused and responsibilities explicit.
- Avoid unnecessary comments and docstrings that merely repeat what the code already expresses.

## Dependencies and configuration

- Use uv for dependency management.
- Never use pip or manually modify the dependency lockfile.
- Keep `uv.lock` committed and synchronized with `pyproject.toml`.
- Declare runtime and development dependencies in their appropriate dependency groups.
- Avoid introducing dependencies unless there is a clear technical justification.
- Do not add, remove or upgrade dependencies without explicit user approval.

Configuration rules:

- Use Pydantic Settings for application configuration.
- Obtain environment-specific configuration from environment variables.
- Keep `.env.example` updated whenever configuration requirements change.
- Never hardcode credentials, secrets, database URLs or environment-specific settings.
- Never commit `.env` files or actual credentials.
- Use secret-safe types where appropriate.
- Do not introduce an environment variable for every implementation detail. Only externally configurable values belong in application settings.

## API development

- Use FastAPI and its dependency injection system.
- Keep endpoints focused on HTTP concerns.
- Put business rules in appropriate application modules.
- Use Pydantic schemas for request validation and response serialization.
- Return appropriate HTTP status codes.
- Handle expected errors explicitly.
- Do not expose internal exceptions, stack traces or sensitive information in API responses.
- Keep API documentation accurate.
- Follow the existing health check conventions:
  - `/health/live`: application liveness.
  - `/health/ready`: readiness of critical dependencies.

## Database and persistence

PostgreSQL is the source of truth.

- Use SQLAlchemy 2.x APIs.
- Use asynchronous database access through `AsyncSession`.
- Create the engine and the session factory in the application lifespan (`create_app`) and obtain sessions through the `get_session` dependency.
- Use one independent `AsyncSession` per request or background task.
- Never share an `AsyncSession` between concurrent tasks.
- Define transaction boundaries explicitly.
- Handle rollbacks correctly when transactions fail.
- Use PostgreSQL constraints to enforce important data invariants.
- Consider indexes, foreign keys, uniqueness, nullability and deletion behavior explicitly.
- Avoid unnecessary database queries and N+1 problems.

### Migrations

- Use Alembic for all schema changes.
- Keep migrations under `src/agroclimate/db/migrations`.
- Never use `Base.metadata.create_all()` to manage the application schema.
- Every persistent schema change must have a corresponding migration.
- Review autogenerated migrations before accepting them.
- Ensure migrations are deterministic and reproducible.
- Consider both upgrade and downgrade behavior.
- Never silently modify an existing migration that may already have been applied in a shared environment.

### Concurrency and data integrity

- Prefer database-enforced guarantees over process-local locks.
- Consider transaction isolation, concurrent writes and race conditions.
- Design operations to behave correctly under retries.
- Use database constraints to enforce important data invariants.
- Consider transaction boundaries and concurrency when implementing operations that require them.

## Testing

Testing is part of implementation, not an optional final step.

- Add or update tests whenever application behavior changes.
- Use Pytest.
- Keep unit tests independent of external infrastructure whenever possible.
- Use integration tests with a real PostgreSQL instance to validate database behavior.
- Use mocks for external dependencies where appropriate.
- Do not use mocks as a substitute for testing actual database constraints, transactions or concurrency.
- Test success cases, failures and boundary conditions.
- Keep test fixtures reusable and appropriately scoped.
- Build the application in tests with `create_app()` and explicit settings. Tests must not depend on a local `.env` file.
- Do not weaken existing assertions or disable checks merely to make tests pass.

Run the relevant quality checks after making changes.

## Code quality

Follow the tools and configuration already defined by the project.

- Ruff format for formatting.
- Ruff check for linting.
- Mypy for static type checking.
- Pytest for automated tests.
- pre-commit for Git hooks.
- Commitizen for Conventional Commit message validation.

Do not disable linting or type-checking rules without a clear justification and user approval.

Do not introduce alternative formatting, linting or type-checking tools without a concrete reason.

## Docker and local development

Docker Compose is the standard way to run the application locally.

- Do not suggest running the API directly on the host with Uvicorn.
- Use the existing Dockerfile and Compose configuration.
- Keep development-only settings, such as automatic reload, out of the production image defaults.
- Keep the production image free of development dependencies.
- Run the application as a non-root user.
- Keep secrets outside Docker images.
- Use health checks and service dependencies appropriately.
- Run database migrations as an explicit operation, not automatically on every API startup.
- Avoid unnecessary containers and infrastructure.

Use the existing Makefile commands rather than introducing alternative task runners.

## Documentation

- Keep the README accurate and focused on actual project functionality.
- Update `.env.example` when configuration changes.
- Document meaningful architectural decisions.
- Do not document planned functionality as if it were already implemented.
- Clearly distinguish implemented behavior, assumptions and limitations.


## Agent permissions and workflow

The user retains full control of the repository and all Git operations.

### Allowed operations

Without additional approval, agents may:

- Inspect and read repository files.
- Inspect Git status, logs and diffs.
- Analyze the existing architecture and propose changes.
- Modify source files within the scope of the requested task.
- Add or update tests.
- Run non-destructive quality checks and tests.
- Run Docker Compose operations that do not delete persistent data.
- Execute tests against isolated test databases.
- Suggest dependencies, tools and architectural changes without installing or applying them.

### Explicit approval required

NEVER perform any of the following without explicit user approval:

- Stage files using `git add` or create Git commits.
- Push changes to remote repositories.
- Create, modify or merge pull requests.
- Create, switch or delete branches.
- Amend commits or rewrite Git history.
- Rebase, reset, cherry-pick or perform other history-modifying operations.
- Discard or overwrite user changes.
- Run destructive Git commands such as `git clean` or `git reset --hard`.
- Delete Docker volumes, databases or persistent data.
- Run migrations against persistent, shared or non-test environments.
- Install additional tools, skills, plugins or external integrations.
- Add, remove or upgrade project dependencies.

The user's silence must never be interpreted as authorization.

### Working approach

- Inspect relevant existing code before making changes.
- Follow established project conventions instead of introducing alternative patterns.
- Make the smallest reasonable change that correctly solves the problem.
- Do not modify unrelated files or perform broad cleanups during focused tasks.
- Do not silently change established architectural decisions.
- Do not invent business requirements or domain behavior.
- Clearly distinguish confirmed requirements from assumptions.
- Ask for clarification when a missing business decision materially affects the implementation.
- Explain significant architectural trade-offs.
- Preserve existing user changes.

### Review and delivery

After making changes:

1. Summarize what was implemented.
2. List the files created, modified or removed.
3. Explain relevant implementation decisions and trade-offs.
4. Report which checks and tests were actually executed.
5. Report their results honestly.
6. Identify outstanding issues, assumptions and unverified behavior.
7. Present the changes for user review.

Never stage, commit, push or publish changes automatically.

The user must review and explicitly approve changes before they are committed or shared.

Never claim tests, builds or validations passed unless they were actually executed.
