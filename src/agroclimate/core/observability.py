import logging
import sys
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint
from structlog.typing import Processor

from agroclimate.core.config import Settings

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
logger = structlog.get_logger(__name__)


def configure_observability(settings: Settings) -> None:
    """Configure structured logging for the application and standard library."""
    renderer: Processor
    exception_processors: list[Processor]
    if settings.environment in ("local", "test"):
        renderer = structlog.dev.ConsoleRenderer()
        exception_processors = []
    else:
        renderer = structlog.processors.JSONRenderer()
        exception_processors = [structlog.processors.dict_tracebacks]

    common_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[
            *common_processors,
            structlog.processors.add_log_level,
            *exception_processors,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                *common_processors,
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *exception_processors,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def instrument_fastapi(app: FastAPI) -> None:
    """Log each HTTP request and correlate application logs with its request ID."""

    @app.middleware("http")
    async def log_http_request(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", "").strip()
        if not request_id or len(request_id) > 128:
            request_id = str(uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started_at = perf_counter()

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http_request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            return response
        except Exception:
            logger.exception(
                "http_request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            raise
        finally:
            structlog.contextvars.clear_contextvars()
