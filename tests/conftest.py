from __future__ import annotations

import asyncio
import os
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
from pydantic import SecretStr
from sqlalchemy import Table, inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from agroclimate.api.dependencies import get_session
from agroclimate.core.config import AppSettings
from agroclimate.db.models import EventType, Field, User, WeatherForecast
from agroclimate.db.settings import DatabaseSettings, get_database_settings
from agroclimate.main import create_app


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(
        app_name="agroclimate-test",
        environment="test",
        log_level="INFO",
    )


@pytest.fixture
def database_settings() -> DatabaseSettings:
    return DatabaseSettings(
        postgres_db="agroclimate_test",
        postgres_user="test",
        postgres_password=SecretStr("test-password"),
        postgres_host="localhost",
        postgres_port=5432,
    )


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
    """Exercise the ASGI app with the real PostgreSQL test session."""
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
def test_database_url() -> Iterator[str]:
    """Prepare a disposable PostgreSQL database for integration tests."""
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set TEST_DATABASE_URL to run PostgreSQL integration tests"
        )

    parsed_url = make_url(database_url)
    if not parsed_url.database or "test" not in parsed_url.database.lower():
        pytest.fail(
            "TEST_DATABASE_URL must point to a database with 'test' "
            "in its name"
        )

    environment_keys = (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    )
    previous_environment = {
        key: os.environ.get(key) for key in environment_keys
    }
    os.environ.update(
        {
            "POSTGRES_DB": parsed_url.database or "",
            "POSTGRES_USER": parsed_url.username or "",
            "POSTGRES_PASSWORD": parsed_url.password or "",
            "POSTGRES_HOST": parsed_url.host or "localhost",
            "POSTGRES_PORT": str(parsed_url.port or 5432),
        }
    )
    get_database_settings.cache_clear()

    engine = create_async_engine(database_url, poolclass=NullPool)

    def create_table(sync_connection: Connection, table: Table) -> None:
        table.create(sync_connection)

    def drop_table(sync_connection: Connection, table: Table) -> None:
        table.drop(sync_connection, checkfirst=True)

    async def create_external_tables() -> None:
        async with engine.begin() as connection:
            existing_tables = await connection.run_sync(
                lambda sync_connection: inspect(
                    sync_connection
                ).get_table_names()
            )
            if existing_tables:
                raise RuntimeError(
                    "TEST_DATABASE_URL must point to an empty database; "
                    f"found tables: {', '.join(existing_tables)}"
                )
            external_tables = (
                cast(Table, User.__table__),
                cast(Table, Field.__table__),
                cast(Table, WeatherForecast.__table__),
            )
            for table in external_tables:
                await connection.run_sync(create_table, table)

    async def drop_test_tables() -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text("DROP TABLE IF EXISTS notifications CASCADE")
            )
            await connection.execute(
                text("DROP TABLE IF EXISTS alerts CASCADE")
            )
            external_tables = (
                cast(Table, WeatherForecast.__table__),
                cast(Table, Field.__table__),
                cast(Table, User.__table__),
            )
            for table in external_tables:
                await connection.run_sync(drop_table, table)
            await connection.execute(
                text("DROP TABLE IF EXISTS alembic_version")
            )

    external_schema_created = False
    migration_applied = False
    alembic_config = Config("alembic.ini")
    try:
        asyncio.run(create_external_tables())
        external_schema_created = True
        command.upgrade(alembic_config, "head")
        migration_applied = True
        yield database_url
    finally:
        try:
            if migration_applied:
                command.downgrade(alembic_config, "base")
        finally:
            try:
                if external_schema_created:
                    asyncio.run(drop_test_tables())
            finally:
                asyncio.run(engine.dispose())
                for key, value in previous_environment.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                get_database_settings.cache_clear()


@pytest_asyncio.fixture
async def postgres_session(
    test_database_url: str,
) -> AsyncIterator[AsyncSession]:
    """Wrap each integration test in a rollback-only transaction."""
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
