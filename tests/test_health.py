import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_when_database_is_available(
    client: TestClient,
    db_session: AsyncMock,
) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    db_session.execute.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [
        OSError("Temporary failure in name resolution"),
        OperationalError(
            "SELECT 1",
            {},
            OSError("Connection refused"),
        ),
    ],
    ids=["network-error", "sqlalchemy-error"],
)
def test_readiness_when_database_is_unavailable(
    client: TestClient,
    db_session: AsyncMock,
    error: Exception,
) -> None:
    db_session.execute.side_effect = error

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable",
    }

    assert "Connection refused" not in response.text
    assert "Temporary failure" not in response.text
    db_session.execute.assert_awaited_once()


def test_readiness_when_database_hangs(
    client: TestClient,
    db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hang(*_: object, **__: object) -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr(
        "agroclimate.api.health.READINESS_TIMEOUT_SECONDS",
        0.05,
    )
    db_session.execute.side_effect = hang

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
