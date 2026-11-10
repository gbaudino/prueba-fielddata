import argparse
import asyncio
import signal
from collections.abc import Sequence
from time import perf_counter

import structlog

from agroclimate.core.config import AppSettings, get_app_settings
from agroclimate.core.observability import configure_observability
from agroclimate.db.session import create_engine, create_session_factory
from agroclimate.db.settings import (
    DatabaseSettings,
    get_database_settings,
)
from agroclimate.services.evaluation.main import evaluate_alerts
from agroclimate.services.evaluation.settings import (
    EvaluationSettings,
    get_evaluation_settings,
)

logger = structlog.get_logger(__name__)


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError, RuntimeError:
            logger.warning(
                "worker_signal_handler_unavailable",
                signal=signum.name,
            )


async def run_worker(
    *,
    once: bool = False,
    stop_event: asyncio.Event | None = None,
    app_settings: AppSettings | None = None,
    database_settings: DatabaseSettings | None = None,
    evaluation_settings: EvaluationSettings | None = None,
) -> None:
    app_settings = app_settings or get_app_settings()
    database_settings = database_settings or get_database_settings()
    evaluation_settings = evaluation_settings or get_evaluation_settings()
    configure_observability(app_settings)

    engine = create_engine(
        database_settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=database_settings.postgres_pool_timeout_seconds,
        pool_recycle=database_settings.postgres_pool_recycle_seconds,
    )
    session_factory = create_session_factory(engine)

    if stop_event is None:
        stop_event = asyncio.Event()
        _install_signal_handlers(stop_event)

    logger.info(
        "evaluation_worker_started",
        once=once,
        interval_seconds=evaluation_settings.interval_seconds,
        timeout_seconds=evaluation_settings.timeout_seconds,
    )

    try:
        while not stop_event.is_set():
            started_at = perf_counter()
            try:
                async with asyncio.timeout(
                    evaluation_settings.timeout_seconds
                ):
                    async with session_factory() as session:
                        created_count = await evaluate_alerts(session)

                logger.info(
                    "evaluation_cycle_completed",
                    created_notifications=created_count,
                    duration_ms=round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                )
            except TimeoutError:
                logger.warning(
                    "evaluation_cycle_timed_out",
                    timeout_seconds=evaluation_settings.timeout_seconds,
                    duration_ms=round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                )
                if once:
                    raise
            except Exception:
                logger.exception("evaluation_cycle_failed")
                if once:
                    raise

            if once or stop_event.is_set():
                break

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=evaluation_settings.interval_seconds,
                )
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("evaluation_worker_stopped")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Periodically evaluate active weather alerts."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one evaluation cycle and exit.",
    )
    args = parser.parse_args(argv)

    asyncio.run(run_worker(once=args.once))


if __name__ == "__main__":
    main()
