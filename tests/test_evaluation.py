import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from agroclimate.db.models import (
    Alert,
    EventType,
    Field,
    Notification,
    User,
    WeatherForecast,
)
from agroclimate.services.evaluation.main import evaluate_alerts

EVALUATED_AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


async def test_evaluation_creates_one_notification_per_matching_day(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alerts = [
        Alert(
            user_id=sample_users[0].id,
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            threshold=60,
        ),
        Alert(
            user_id=sample_users[1].id,
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            threshold=90,
        ),
        Alert(
            user_id=sample_users[0].id,
            field_id=sample_fields[0].id,
            event_type=EventType.HAIL,
            threshold=60,
            active=False,
        ),
    ]
    forecasts = [
        WeatherForecast(
            id=uuid4(),
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            forecast_date=date(2026, 11, day),
            probability=80,
        )
        for day in (10, 11, 12, 13)
    ]
    forecasts.append(
        WeatherForecast(
            id=uuid4(),
            field_id=sample_fields[0].id,
            event_type=EventType.HAIL,
            forecast_date=date(2026, 11, 10),
            probability=100,
        )
    )
    postgres_session.add_all([*alerts, *forecasts])
    await postgres_session.flush()

    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).order_by(Notification.forecast_date)
            )
        ).all()
    )
    assert created_count == 4
    assert [item.forecast_date for item in notifications] == [
        date(2026, 11, 10),
        date(2026, 11, 11),
        date(2026, 11, 12),
        date(2026, 11, 13),
    ]
    assert all(item.user_id == sample_users[0].id for item in notifications)
    assert all(
        item.probability == 80 and item.threshold == 60
        for item in notifications
    )


async def test_evaluation_checks_current_field_access(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=60,
    )
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=90,
    )
    sample_fields[0].related_users = [sample_users[1].id]
    postgres_session.add_all([alert, forecast])
    await postgres_session.flush()

    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )

    assert created_count == 0


async def test_evaluation_uses_local_field_date_and_all_future_forecasts(
    postgres_session: AsyncSession,
    sample_users: list[User],
) -> None:
    field = Field(
        id=uuid4(),
        name="Campo en Kiritimati",
        related_users=[sample_users[0].id],
        latitude=-3.1,
        longitude=-171.8,
        timezone="Pacific/Kiritimati",
    )
    postgres_session.add(field)
    await postgres_session.flush()

    alert = Alert(
        user_id=sample_users[0].id,
        field_id=field.id,
        event_type=EventType.RAIN,
        threshold=50,
    )
    forecasts = [
        WeatherForecast(
            id=uuid4(),
            field_id=field.id,
            event_type=EventType.RAIN,
            forecast_date=date(2026, 11, day),
            probability=80,
        )
        for day in (9, 10, 11, 12)
    ]
    postgres_session.add_all([alert, *forecasts])
    await postgres_session.flush()

    # At 01:00 UTC, Kiritimati's local date is already November 10.
    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=datetime(2026, 11, 10, 1, 0, tzinfo=UTC),
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).where(Notification.alert_id == alert.id)
            )
        ).all()
    )
    assert created_count == 3
    assert {item.forecast_date for item in notifications} == {
        date(2026, 11, 10),
        date(2026, 11, 11),
        date(2026, 11, 12),
    }


async def test_evaluation_is_idempotent_and_preserves_notification_snapshot(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=60,
    )
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=80,
    )
    postgres_session.add_all([alert, forecast])
    await postgres_session.flush()

    first_run = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )
    forecast.probability = 95
    alert.threshold = 90
    await postgres_session.flush()
    second_run = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT + timedelta(hours=1),
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).where(Notification.alert_id == alert.id)
            )
        ).all()
    )
    assert (first_run, second_run) == (1, 0)
    assert len(notifications) == 1
    assert notifications[0].probability == 80
    assert notifications[0].threshold == 60


async def test_concurrent_evaluations_do_not_create_duplicates(
    postgres_engine: AsyncEngine,
) -> None:
    user = User(id=uuid4(), name="Concurrency User")
    field = Field(
        id=uuid4(),
        name="Concurrency Field",
        related_users=[user.id],
        latitude=-31.4,
        longitude=-64.2,
        timezone="America/Argentina/Cordoba",
    )
    alert = Alert(
        user_id=user.id,
        field_id=field.id,
        event_type=EventType.RAIN,
        threshold=60,
    )
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=field.id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=80,
    )
    session_factory = async_sessionmaker(
        postgres_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            session.add(user)
            await session.flush()
            session.add(field)
            await session.flush()
            session.add_all([alert, forecast])
            await session.commit()

        async def run_evaluation() -> int:
            async with session_factory() as session:
                return await evaluate_alerts(
                    session,
                    evaluated_at=EVALUATED_AT,
                )

        results = await asyncio.gather(
            run_evaluation(),
            run_evaluation(),
        )

        assert sorted(results) == [0, 1]

        async with session_factory() as session:
            notifications = list(
                (
                    await session.scalars(
                        select(Notification).where(
                            Notification.alert_id == alert.id
                        )
                    )
                ).all()
            )
        assert len(notifications) == 1
    finally:
        async with postgres_engine.begin() as connection:
            await connection.execute(
                delete(Notification).where(Notification.user_id == user.id)
            )
            await connection.execute(delete(Alert).where(Alert.id == alert.id))
            await connection.execute(
                delete(WeatherForecast).where(
                    WeatherForecast.field_id == field.id
                )
            )
            await connection.execute(delete(Field).where(Field.id == field.id))
            await connection.execute(delete(User).where(User.id == user.id))


async def test_evaluation_rejects_naive_timestamp() -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    with pytest.raises(ValueError, match="timezone-aware"):
        await evaluate_alerts(
            session,
            evaluated_at=datetime(2026, 11, 10),
        )
