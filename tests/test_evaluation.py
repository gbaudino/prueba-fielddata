from datetime import UTC, date, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.db.models import (
    Alert,
    EventType,
    Field,
    Notification,
    User,
    WeatherForecast,
)
from agroclimate.services.evaluation.main import evaluate_alerts

EVALUATED_AT = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)


async def test_evaluation_creates_notification_when_threshold_is_reached(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=75,
    )
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=75,
    )
    postgres_session.add_all([alert, forecast])
    await postgres_session.flush()

    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).where(Notification.alert_id == alert.id)
            )
        ).all()
    )
    assert created_count == 1
    assert len(notifications) == 1
    assert notifications[0].user_id == sample_users[0].id
    assert notifications[0].field_id == sample_fields[0].id
    assert notifications[0].event_type == EventType.RAIN
    assert notifications[0].forecast_date == date(2026, 11, 10)
    assert notifications[0].probability == 75
    assert notifications[0].threshold == 75


async def test_evaluation_notifies_each_user_with_their_own_threshold(
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
    ]
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=80,
    )
    postgres_session.add_all([*alerts, forecast])
    await postgres_session.flush()

    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).order_by(Notification.user_id)
            )
        ).all()
    )
    assert created_count == 1
    assert len(notifications) == 1
    assert notifications[0].user_id == sample_users[0].id
    assert notifications[0].threshold == 60


async def test_evaluation_skips_inactive_alerts_and_unmet_thresholds(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    active_alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=80,
    )
    inactive_alert = Alert(
        user_id=sample_users[1].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=50,
        active=False,
    )
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=75,
    )
    postgres_session.add_all([active_alert, inactive_alert, forecast])
    await postgres_session.flush()

    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )

    assert created_count == 0


async def test_evaluation_skips_users_without_current_field_access(
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


async def test_evaluation_matches_event_type_and_field(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.FROST,
        threshold=20,
    )
    rain_forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=95,
    )
    frost_forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.FROST,
        forecast_date=date(2026, 11, 10),
        probability=20,
    )
    postgres_session.add_all([alert, rain_forecast, frost_forecast])
    await postgres_session.flush()

    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).where(Notification.alert_id == alert.id)
            )
        ).all()
    )
    assert created_count == 1
    assert len(notifications) == 1
    assert notifications[0].event_type == EventType.FROST
    assert notifications[0].probability == 20


async def test_evaluation_respects_field_timezone_and_horizon(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=50,
    )
    forecasts = [
        WeatherForecast(
            id=uuid4(),
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            forecast_date=date(2026, 11, day),
            probability=80,
        )
        for day in (10, 16, 17)
    ]
    postgres_session.add_all([alert, *forecasts])
    await postgres_session.flush()

    created_count = await evaluate_alerts(
        postgres_session,
        horizon_days=7,
        evaluated_at=EVALUATED_AT,
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).where(Notification.alert_id == alert.id)
            )
        ).all()
    )
    assert created_count == 2
    assert {item.forecast_date for item in notifications} == {
        date(2026, 11, 10),
        date(2026, 11, 16),
    }


async def test_evaluation_uses_each_fields_local_calendar_date(
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
    # Persist the referenced external field before inserting the alert.
    # These models intentionally have no ORM relationships, so SQLAlchemy
    # cannot infer this flush order from mapper relationships.
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
        for day in (10, 11)
    ]
    postgres_session.add_all([alert, *forecasts])
    await postgres_session.flush()

    # At 01:00 UTC, Kiritimati is already on November 10.
    created_count = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).where(Notification.alert_id == alert.id)
            )
        ).all()
    )
    assert created_count == 1
    assert [item.forecast_date for item in notifications] == [
        date(2026, 11, 11)
    ]


async def test_evaluation_is_idempotent_and_keeps_notification_snapshot(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=80,
    )
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date(2026, 11, 10),
        probability=70,
    )
    postgres_session.add_all([alert, forecast])
    await postgres_session.flush()

    first_run = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )
    assert first_run == 0

    forecast.probability = 90
    await postgres_session.flush()
    second_run = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )
    assert second_run == 1

    alert.threshold = 95
    forecast.probability = 99
    await postgres_session.flush()
    third_run = await evaluate_alerts(
        postgres_session,
        evaluated_at=EVALUATED_AT,
    )
    assert third_run == 0

    notifications = list(
        (
            await postgres_session.scalars(
                select(Notification).where(Notification.alert_id == alert.id)
            )
        ).all()
    )
    assert len(notifications) == 1
    assert notifications[0].probability == 90
    assert notifications[0].threshold == 80


@pytest.mark.parametrize("horizon_days", [0, -1])
async def test_evaluation_rejects_non_positive_horizons(
    horizon_days: int,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    with pytest.raises(ValueError, match="horizon_days"):
        await evaluate_alerts(session, horizon_days=horizon_days)


async def test_evaluation_rejects_naive_evaluation_timestamp() -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    with pytest.raises(ValueError, match="timezone-aware"):
        await evaluate_alerts(
            session,
            evaluated_at=datetime(2026, 11, 10),
        )
