import asyncio
from typing import cast

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from agroclimate import worker
from agroclimate.core.config import AppSettings
from agroclimate.db.settings import DatabaseSettings
from agroclimate.services.evaluation.settings import EvaluationSettings


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeSessionContext:
    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, object())

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSessionFactory:
    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext()


@pytest.fixture
def worker_config() -> tuple[
    AppSettings,
    DatabaseSettings,
    EvaluationSettings,
]:
    return (
        AppSettings(
            app_name="agroclimate-test",
            environment="test",
            log_level="INFO",
        ),
        DatabaseSettings(
            postgres_db="agroclimate_test",
            postgres_user="test",
            postgres_password=SecretStr("test-password"),
            postgres_host="localhost",
            postgres_port=5432,
            postgres_pool_size=1,
            postgres_max_overflow=0,
            postgres_pool_timeout_seconds=1,
            postgres_pool_recycle_seconds=60,
        ),
        EvaluationSettings(
            interval_seconds=0.01,
            timeout_seconds=1,
        ),
    )


def patch_worker(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    engine = FakeEngine()
    session_factory = FakeSessionFactory()

    def create_engine(*args: object, **kwargs: object) -> AsyncEngine:
        return cast(AsyncEngine, engine)

    def create_session_factory(
        _engine: AsyncEngine,
    ) -> async_sessionmaker[AsyncSession]:
        return cast(async_sessionmaker[AsyncSession], session_factory)

    def configure_observability(_settings: AppSettings) -> None:
        return None

    monkeypatch.setattr(
        worker, "configure_observability", configure_observability
    )
    monkeypatch.setattr(worker, "create_engine", create_engine)
    monkeypatch.setattr(
        worker, "create_session_factory", create_session_factory
    )
    return engine


async def test_worker_once_runs_one_cycle_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
    worker_config: tuple[
        AppSettings,
        DatabaseSettings,
        EvaluationSettings,
    ],
) -> None:
    engine = patch_worker(monkeypatch)
    app_settings, database_settings, evaluation_settings = worker_config
    calls = 0

    async def evaluate(_session: AsyncSession) -> int:
        nonlocal calls
        calls += 1
        return 2

    monkeypatch.setattr(worker, "evaluate_alerts", evaluate)
    await worker.run_worker(
        once=True,
        stop_event=asyncio.Event(),
        app_settings=app_settings,
        database_settings=database_settings,
        evaluation_settings=evaluation_settings,
    )

    assert calls == 1
    assert engine.disposed is True


async def test_worker_continues_after_a_failed_cycle(
    monkeypatch: pytest.MonkeyPatch,
    worker_config: tuple[
        AppSettings,
        DatabaseSettings,
        EvaluationSettings,
    ],
) -> None:
    engine = patch_worker(monkeypatch)
    app_settings, database_settings, evaluation_settings = worker_config
    stop_event = asyncio.Event()
    calls = 0

    async def evaluate(_session: AsyncSession) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        stop_event.set()
        return 1

    monkeypatch.setattr(worker, "evaluate_alerts", evaluate)
    await worker.run_worker(
        stop_event=stop_event,
        app_settings=app_settings,
        database_settings=database_settings,
        evaluation_settings=evaluation_settings,
    )

    assert calls == 2
    assert engine.disposed is True


async def test_worker_once_propagates_timeout_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
    worker_config: tuple[
        AppSettings,
        DatabaseSettings,
        EvaluationSettings,
    ],
) -> None:
    engine = patch_worker(monkeypatch)
    app_settings, database_settings, evaluation_settings = worker_config
    evaluation_settings = evaluation_settings.model_copy(
        update={"timeout_seconds": 0.01}
    )

    async def evaluate(_session: AsyncSession) -> int:
        await asyncio.sleep(0.1)
        return 0

    monkeypatch.setattr(worker, "evaluate_alerts", evaluate)

    with pytest.raises(TimeoutError):
        await worker.run_worker(
            once=True,
            stop_event=asyncio.Event(),
            app_settings=app_settings,
            database_settings=database_settings,
            evaluation_settings=evaluation_settings,
        )

    assert engine.disposed is True
