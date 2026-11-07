from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agroclimate.api.health import router as health_router
from agroclimate.api.v1.router import router as api_router
from agroclimate.core.config import Settings, get_settings
from agroclimate.core.observability import (
    configure_observability,
    instrument_fastapi,
)
from agroclimate.db.session import create_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_observability(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url.get_secret_value())
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
