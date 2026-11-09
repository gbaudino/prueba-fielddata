from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agroclimate.api.health import router as health_router
from agroclimate.api.v1.router import router as api_router
from agroclimate.core.config import AppSettings, get_app_settings
from agroclimate.core.observability import (
    configure_observability,
    instrument_fastapi,
)
from agroclimate.db.session import create_engine, create_session_factory
from agroclimate.db.settings import (
    DatabaseSettings,
    get_database_settings,
)


def create_app(
    settings: AppSettings | None = None,
    database_settings: DatabaseSettings | None = None,
) -> FastAPI:
    settings = settings or get_app_settings()
    database_settings = database_settings or get_database_settings()
    configure_observability(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(
            database_settings.database_url,
            pool_size=database_settings.postgres_pool_size,
            max_overflow=database_settings.postgres_max_overflow,
            pool_timeout=database_settings.postgres_pool_timeout_seconds,
            pool_recycle=database_settings.postgres_pool_recycle_seconds,
        )
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    instrument_fastapi(app)

    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")

    return app
