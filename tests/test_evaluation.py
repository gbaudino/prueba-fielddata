import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
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
    OutboxEvent,
    User,
    WeatherForecast,
)
from agroclimate.services.evaluation.main import evaluate_alerts

EVALUATED_AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def rain_alert(field: Field, user: User, threshold: int = 60) -> Alert:
    return Alert(
        created_by=user.id,
        field_id=field.id,
        event_type=EventType.RAIN,
        threshold=threshold,
    )


def rain_forecast(field: Field, day: int, probability: int) -> WeatherForecast:
    return WeatherForecast(
        id=uuid4(),
        field_id=field.id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, day),
        probability=probability,
    )


async def all_notifications(session: AsyncSession) -> list[Notification]:
    statement = select(Notification).order_by(
        Notification.forecast_date, Notification.user_id
    )
    return list((await session.scalars(statement)).all())


async def count_outbox(session: AsyncSession) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(OutboxEvent))
        or 0
    )


async def test_notifies_every_field_user_for_each_date_over_threshold(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    field = sample_fields[0]
    alert = rain_alert(field, sample_users[0])
    inactive = Alert(
        created_by=sample_users[0].id,
        field_id=field.id,
        event_type=EventType.HAIL,
        threshold=10,
        active=False,
    )
    postgres_session.add_all(
        [
            alert,
            inactive,
            rain_forecast(field, 9, 99),  # past date: ignored
            rain_forecast(field, 10, 60),  # equal to threshold: notified
            rain_forecast(field, 11, 59),  # below threshold: ignored
            rain_forecast(field, 12, 90),
            WeatherForecast(
                id=uuid4(),
                field_id=field.id,
                event_type=EventType.HAIL,
                forecast_date=date(2026, 11, 10),
                probability=100,
            ),
        ]
    )
    await postgres_session.flush()

    created = await evaluate_alerts(
        postgres_session, evaluated_at=EVALUATED_AT
    )

    notifications = await all_notifications(postgres_session)
    assert created == 4
    assert {
        (item.user_id, item.forecast_date, item.probability)
        for item in notifications
    } == {
        (user.id, date(2026, 11, day), probability)
        for user in sample_users
        for day, probability in ((10, 60), (12, 90))
    }
    assert all(item.alert_id == alert.id for item in notifications)
    assert all(item.threshold == 60 for item in notifications)


async def test_writes_one_outbox_event_per_notification(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    field = sample_fields[0]
    alert = rain_alert(field, sample_users[0])
    postgres_session.add_all([alert, rain_forecast(field, 11, 80)])
    await postgres_session.flush()

    await evaluate_alerts(postgres_session, evaluated_at=EVALUATED_AT)

    notifications = {
        item.id: item for item in await all_notifications(postgres_session)
    }
    events = list((await postgres_session.scalars(select(OutboxEvent))).all())
    assert len(events) == len(notifications) == 2
    for event in events:
        notification = notifications[event.aggregate_id]
        assert event.event_type == "notification.created"
        assert event.aggregate_type == "notification"
        assert event.published_at is None
        assert event.payload["notification_id"] == str(notification.id)
        assert event.payload["alert_id"] == str(alert.id)
        assert event.payload["user_id"] == str(notification.user_id)
        assert event.payload["field_id"] == str(field.id)
        assert event.payload["event_type"] == "rain"
        assert event.payload["forecast_date"] == "2026-11-11"
        assert event.payload["probability"] == 80
        assert event.payload["threshold"] == 60


async def test_uses_current_field_access(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    field = sample_fields[0]
    field.related_users = [sample_users[1].id]
    postgres_session.add_all(
        [rain_alert(field, sample_users[0]), rain_forecast(field, 10, 90)]
    )
    await postgres_session.flush()

    created = await evaluate_alerts(
        postgres_session, evaluated_at=EVALUATED_AT
    )

    notifications = await all_notifications(postgres_session)
    assert created == 1
    assert notifications[0].user_id == sample_users[1].id


async def test_uses_the_local_date_of_the_field(
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
    postgres_session.add_all(
        [
            rain_alert(field, sample_users[0]),
            rain_forecast(field, 9, 90),
            rain_forecast(field, 10, 90),
        ]
    )
    await postgres_session.flush()

    # 23:00 UTC on Nov 9 is already Nov 10 in Kiritimati (UTC+14).
    created = await evaluate_alerts(
        postgres_session,
        evaluated_at=datetime(2026, 11, 9, 23, 0, tzinfo=UTC),
    )

    notifications = await all_notifications(postgres_session)
    assert created == 1
    assert notifications[0].forecast_date == date(2026, 11, 10)


async def test_is_idempotent_and_keeps_the_notification_snapshot(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    field = sample_fields[0]
    field.related_users = [sample_users[0].id]
    alert = rain_alert(field, sample_users[0])
    forecast = rain_forecast(field, 10, 80)
    postgres_session.add_all([alert, forecast])
    await postgres_session.flush()

    first = await evaluate_alerts(postgres_session, evaluated_at=EVALUATED_AT)
    forecast.probability = 95
    alert.threshold = 90
    await postgres_session.flush()
    second = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT + timedelta(hours=1),
    )

    notifications = await all_notifications(postgres_session)
    assert (first, second) == (1, 0)
    assert await count_outbox(postgres_session) == 1
    assert len(notifications) == 1
    assert notifications[0].probability == 80
    assert notifications[0].threshold == 60


async def test_notifies_a_new_date_that_crosses_the_threshold(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    field = sample_fields[0]
    field.related_users = [sample_users[0].id]
    postgres_session.add_all(
        [rain_alert(field, sample_users[0]), rain_forecast(field, 10, 80)]
    )
    await postgres_session.flush()
    await evaluate_alerts(postgres_session, evaluated_at=EVALUATED_AT)

    postgres_session.add(rain_forecast(field, 11, 70))
    await postgres_session.flush()
    created = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT + timedelta(hours=1),
    )

    assert created == 1
    assert [
        item.forecast_date
        for item in await all_notifications(postgres_session)
    ] == [date(2026, 11, 10), date(2026, 11, 11)]


async def test_creates_more_notifications_than_bind_parameters_allow(
    postgres_session: AsyncSession,
    sample_users: list[User],
) -> None:
    # asyncpg accepts at most 32767 bind parameters per statement, so the
    # evaluation must not bind values per created notification.
    field_count = 4_000
    users = [user.id for user in sample_users]
    await postgres_session.execute(
        text(
            """
            WITH new_fields AS (
                INSERT INTO fields
                    (id, name, related_users, latitude, longitude, timezone)
                SELECT gen_random_uuid(), 'Campo', :users, 0, 0, 'UTC'
                FROM generate_series(1, :count)
                RETURNING id
            ), new_alerts AS (
                INSERT INTO alerts (id, field_id, event_type, threshold)
                SELECT gen_random_uuid(), id, 'rain', 60 FROM new_fields
            )
            INSERT INTO weather_forecasts
                (id, field_id, event_type, forecast_date, probability)
            SELECT gen_random_uuid(), id, 'rain', DATE '2026-11-10', 90
            FROM new_fields
            """
        ),
        {"users": users, "count": field_count},
    )

    created = await evaluate_alerts(
        postgres_session, evaluated_at=EVALUATED_AT
    )

    assert created == field_count * len(users)
    assert await count_outbox(postgres_session) == created


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
    session_factory = async_sessionmaker(
        postgres_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    user_events = OutboxEvent.payload["user_id"].astext == str(user.id)

    try:
        async with session_factory() as session:
            session.add(user)
            await session.flush()
            session.add(field)
            await session.flush()
            session.add_all(
                [rain_alert(field, user), rain_forecast(field, 10, 80)]
            )
            await session.commit()

        async def run_evaluation() -> int:
            async with session_factory() as session:
                return await evaluate_alerts(
                    session,
                    evaluated_at=EVALUATED_AT,
                )

        results = await asyncio.gather(run_evaluation(), run_evaluation())

        async with session_factory() as session:
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(user_events)
            )
        assert sorted(results) == [0, 1]
        assert outbox_count == 1
    finally:
        async with postgres_engine.begin() as connection:
            await connection.execute(delete(OutboxEvent).where(user_events))
            await connection.execute(
                delete(Notification).where(Notification.user_id == user.id)
            )
            await connection.execute(
                delete(Alert).where(Alert.field_id == field.id)
            )
            await connection.execute(
                delete(WeatherForecast).where(
                    WeatherForecast.field_id == field.id
                )
            )
            await connection.execute(delete(Field).where(Field.id == field.id))
            await connection.execute(delete(User).where(User.id == user.id))


async def test_rejects_a_naive_timestamp() -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    with pytest.raises(ValueError, match="timezone-aware"):
        await evaluate_alerts(session, evaluated_at=datetime(2026, 11, 10))
