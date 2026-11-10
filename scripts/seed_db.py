from __future__ import annotations

import asyncio
import random
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import Table, func, insert, select
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.core.config import get_app_settings
from agroclimate.db.models import EventType, Field, User, WeatherForecast
from agroclimate.db.session import create_engine, create_session_factory
from agroclimate.db.settings import get_database_settings

USER_COUNT = 200
FIELD_COUNT = 500
FORECAST_DAYS = 30
RANDOM_SEED = 42
INSERT_BATCH_SIZE = 5_000
DEMO_TIMEZONE = "America/Argentina/Cordoba"
logger = structlog.get_logger(__name__)


def chunks[T](items: Iterable[T], size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def create_external_tables(connection: Connection) -> None:
    """Create only the local stand-ins for Agrobot-owned tables."""
    for table in (User.__table__, Field.__table__, WeatherForecast.__table__):
        table.create(connection, checkfirst=True)


def build_users() -> list[dict[str, Any]]:
    return [
        {
            "id": uuid4(),
            "name": f"Usuario Demo {index + 1:04d}",
            "email": f"usuario{index + 1:04d}@example.test",
            "phone_number": f"+549351{index + 1:07d}",
        }
        for index in range(USER_COUNT)
    ]


def build_fields(
    user_ids: Sequence[UUID], rng: random.Random
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for index in range(FIELD_COUNT):
        related_user_count = rng.randint(1, min(4, len(user_ids)))
        related_users = rng.sample(list(user_ids), related_user_count)
        fields.append(
            {
                "id": uuid4(),
                "name": f"Campo Demo {index + 1:04d}",
                "related_users": related_users,
                "latitude": -35.0 + (index % 130) * 0.1,
                "longitude": -68.0 + (index % 140) * 0.1,
                "timezone": DEMO_TIMEZONE,
            }
        )
    return fields


def build_forecasts(
    fields: Sequence[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    today = datetime.now(ZoneInfo(DEMO_TIMEZONE)).date()
    rng = random.Random(RANDOM_SEED)
    events = list(EventType)

    for field_index, field in enumerate(fields):
        for day_offset in range(1, FORECAST_DAYS + 1):
            forecast_date = today + timedelta(days=day_offset)
            for event_index, event_type in enumerate(events):
                probability = rng.randint(1, 100)

                peak_day = (event_index + 1) * 2
                if (
                    day_offset == peak_day
                    and field_index % (event_index + 3) == 0
                ):
                    probability = min(100, 85 + event_index * 3)

                yield {
                    "id": uuid4(),
                    "field_id": field["id"],
                    "event_type": event_type,
                    "forecast_date": forecast_date,
                    "probability": probability,
                }


async def count_rows(session: AsyncSession, table: Table) -> int:
    result = await session.scalar(select(func.count()).select_from(table))
    return int(result or 0)


async def seed_database() -> tuple[int, int, int]:
    app_settings = get_app_settings()
    if app_settings.environment != "local":
        raise RuntimeError("Demo data can only be loaded in local environment")

    settings = get_database_settings()
    database_url = settings.database_url
    if make_url(database_url).host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "Demo data can only be loaded into local PostgreSQL"
        )

    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(create_external_tables)

        async with session_factory() as session, session.begin():
            existing_counts = (
                await count_rows(session, User.__table__),
                await count_rows(session, Field.__table__),
                await count_rows(session, WeatherForecast.__table__),
            )
            if any(existing_counts):
                logger.info(
                    "demo_data_already_present",
                    users=existing_counts[0],
                    fields=existing_counts[1],
                    weather_forecasts=existing_counts[2],
                )
                return existing_counts

            rng = random.Random(RANDOM_SEED)
            users = build_users()
            fields = build_fields([user["id"] for user in users], rng)

            await session.execute(insert(User.__table__), users)
            await session.execute(insert(Field.__table__), fields)

            forecast_rows = build_forecasts(fields)
            forecast_count = 0
            for batch in chunks(forecast_rows, INSERT_BATCH_SIZE):
                await session.execute(insert(WeatherForecast.__table__), batch)
                forecast_count += len(batch)

        return USER_COUNT, FIELD_COUNT, forecast_count
    finally:
        await engine.dispose()


async def main() -> None:
    counts = await seed_database()
    logger.info(
        "demo_data_ready",
        users=counts[0],
        fields=counts[1],
        weather_forecasts=counts[2],
    )


if __name__ == "__main__":
    asyncio.run(main())
