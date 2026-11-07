from collections.abc import AsyncIterator, Iterator
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.api.dependencies import get_session
from agroclimate.core.config import Settings
from agroclimate.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_name="agroclimate-test",
        environment="test",
        log_level="INFO",
        database_url=SecretStr("postgresql+asyncpg://u:p@localhost/db"),
    )


@pytest.fixture
def db_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def client(settings: Settings, db_session: AsyncMock) -> Iterator[TestClient]:
    app = create_app(settings)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, db_session)

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client
