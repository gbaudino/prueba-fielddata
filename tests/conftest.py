from collections.abc import AsyncIterator, Iterator
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.db.session import get_session
from agroclimate.main import app


@pytest.fixture
def db_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def client(
    db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, db_session)

    monkeypatch.setitem(
        app.dependency_overrides,
        get_session,
        override_get_session,
    )

    with TestClient(app) as test_client:
        yield test_client
