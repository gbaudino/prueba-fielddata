import logging
import sys
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint
from structlog.stdlib import ProcessorFormatter
from structlog.typing import Processor

from agroclimate.core.config import AppSettings

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
LOGGERS_TO_IGNORE: tuple[str, ...] = ()

logger = structlog.get_logger(__name__)
logging.getLogger("uvicorn.access").disabled = True


def configure_observability(settings: AppSettings) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    console_renderer = structlog.dev.ConsoleRenderer(
        colors=True,
        pad_event_to=0,
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.add_log_level,
            console_renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        ProcessorFormatter(
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                *shared_processors,
            ],
            processors=[
                ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True, pad_event_to=0),
            ],
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.log_level)

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    for name in LOGGERS_TO_IGNORE:
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)


def instrument_fastapi(app: FastAPI) -> None:
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
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            return response
        except Exception:
            logger.exception(
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            raise
        finally:
            structlog.contextvars.clear_contextvars()
