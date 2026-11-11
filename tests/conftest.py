from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import date, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from agroclimate.api.dependencies import get_session
from agroclimate.core.config import AppSettings, get_app_settings
from agroclimate.db.models import EventType, Field, User, WeatherForecast
from agroclimate.db.settings import DatabaseSettings, get_database_settings
from agroclimate.main import create_app

TEST_DATABASE_NAME = "agroclimate_test"


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(
        app_name="agroclimate-test",
        environment="test",
        log_level="INFO",
    )


@pytest.fixture(scope="session")
def test_database_settings() -> DatabaseSettings:
    environment = get_app_settings().environment
    if environment not in {"local", "test"}:
        pytest.fail(
            "Refusing to run destructive integration tests outside "
            "ENVIRONMENT=local or ENVIRONMENT=test"
        )

    base_settings = get_database_settings()
    host = base_settings.postgres_host.strip("[]").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail(
            "Refusing to run destructive integration tests against a "
            "non-local PostgreSQL host. Set POSTGRES_HOST to localhost "
            "and use a dedicated local PostgreSQL instance."
        )

    if base_settings.postgres_db == TEST_DATABASE_NAME:
        pytest.fail(
            "POSTGRES_DB cannot be the test database. "
            "Use a separate development database in .env."
        )

    return base_settings.model_copy(update={"postgres_db": TEST_DATABASE_NAME})


@pytest.fixture
def database_settings(
    test_database_settings: DatabaseSettings,
) -> DatabaseSettings:
    return test_database_settings


@pytest.fixture
def db_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def client(
    settings: AppSettings,
    database_settings: DatabaseSettings,
    db_session: AsyncMock,
) -> Iterator[TestClient]:
    app = create_app(settings, database_settings)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, db_session)

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def api_client(
    settings: AppSettings,
    database_settings: DatabaseSettings,
    postgres_session: AsyncSession,
) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(settings, database_settings)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield postgres_session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx2.ASGITransport(app=app)

    try:
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def test_database_url(
    test_database_settings: DatabaseSettings,
) -> Iterator[str]:
    base_settings = get_database_settings()
    database_url = test_database_settings.database_url
    database_url_string = database_url.render_as_string(hide_password=False)

    async def ensure_database_exists() -> None:
        admin_engine = create_async_engine(
            base_settings.database_url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
            poolclass=NullPool,
        )
        try:
            async with admin_engine.connect() as connection:
                exists = await connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": TEST_DATABASE_NAME},
                )
                if not exists:
                    identifier = connection.dialect.identifier_preparer.quote(
                        TEST_DATABASE_NAME
                    )
                    await connection.exec_driver_sql(
                        f"CREATE DATABASE {identifier}"
                    )
        finally:
            await admin_engine.dispose()

    engine = create_async_engine(database_url, poolclass=NullPool)
    database_ready = False
    schema_prepared = False
    migration_applied = False
    migration_config = Config("alembic.ini")
    migration_config.attributes["database_url"] = database_url

    def create_table(sync_connection: Connection, table: Table) -> None:
        table.create(sync_connection)

    async def reset_test_schema() -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text("DROP SCHEMA IF EXISTS public CASCADE")
            )
            await connection.execute(text("CREATE SCHEMA public"))

    async def create_external_tables() -> None:
        async with engine.begin() as connection:
            external_tables = (
                cast(Table, User.__table__),
                cast(Table, Field.__table__),
                cast(Table, WeatherForecast.__table__),
            )
            for table in external_tables:
                await connection.run_sync(create_table, table)

    try:
        try:
            asyncio.run(ensure_database_exists())
            database_ready = True
            asyncio.run(reset_test_schema())
            schema_prepared = True
            asyncio.run(create_external_tables())
        except SQLAlchemyError as exc:
            pytest.fail(
                "Could not prepare PostgreSQL integration tests. "
                "Make sure Docker is running, .env has valid POSTGRES_* "
                "settings, and POSTGRES_USER can create databases. "
                f"Details: {exc}"
            )

        command.upgrade(migration_config, "head")
        migration_applied = True
        yield database_url_string
    finally:
        try:
            if database_ready and migration_applied:
                command.downgrade(migration_config, "base")
        finally:
            try:
                if database_ready and schema_prepared:
                    asyncio.run(reset_test_schema())
            finally:
                asyncio.run(engine.dispose())


@pytest_asyncio.fixture
async def postgres_engine(
    test_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def postgres_session(
    test_database_url: str,
) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session_factory = async_sessionmaker(
                bind=connection,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with session_factory() as session:
                try:
                    yield session
                finally:
                    await session.rollback()
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def sample_users(
    postgres_session: AsyncSession,
) -> list[User]:
    users = [
        User(
            id=uuid4(),
            name="Ana Pérez",
            email="ana@example.test",
            phone_number="+5493515550001",
        ),
        User(
            id=uuid4(),
            name="Bruno Gómez",
            email="bruno@example.test",
            phone_number="+5493515550002",
        ),
    ]
    postgres_session.add_all(users)
    await postgres_session.flush()
    return users


@pytest_asyncio.fixture
async def sample_fields(
    postgres_session: AsyncSession,
    sample_users: list[User],
) -> list[Field]:
    fields = [
        Field(
            id=uuid4(),
            name="Campo Norte",
            related_users=[sample_users[0].id, sample_users[1].id],
            latitude=-31.4167,
            longitude=-64.1833,
            timezone="America/Argentina/Cordoba",
        ),
        Field(
            id=uuid4(),
            name="Campo Sur",
            related_users=[sample_users[1].id],
            latitude=-32.0,
            longitude=-64.0,
            timezone="America/Argentina/Cordoba",
        ),
    ]
    postgres_session.add_all(fields)
    await postgres_session.flush()
    return fields


@pytest_asyncio.fixture
async def sample_forecasts(
    postgres_session: AsyncSession,
    sample_fields: list[Field],
) -> list[WeatherForecast]:
    tomorrow = date.today() + timedelta(days=1)
    forecasts = [
        WeatherForecast(
            id=uuid4(),
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            forecast_date=tomorrow,
            probability=75,
        ),
        WeatherForecast(
            id=uuid4(),
            field_id=sample_fields[0].id,
            event_type=EventType.FROST,
            forecast_date=tomorrow,
            probability=20,
        ),
        WeatherForecast(
            id=uuid4(),
            field_id=sample_fields[1].id,
            event_type=EventType.RAIN,
            forecast_date=tomorrow,
            probability=55,
        ),
    ]
    postgres_session.add_all(forecasts)
    await postgres_session.flush()
    return forecasts
