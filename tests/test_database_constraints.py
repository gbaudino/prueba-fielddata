from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.db.models import (
    Alert,
    EventType,
    Field,
    Notification,
    User,
    WeatherForecast,
)


@pytest.mark.parametrize("record_type", ["user", "field"])
async def test_notifications_restrict_deleting_referenced_external_records(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
    record_type: str,
) -> None:
    notification = Notification(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date.today(),
        probability=75,
        threshold=60,
    )
    postgres_session.add(notification)
    await postgres_session.flush()

    referenced_record = (
        sample_users[0] if record_type == "user" else sample_fields[0]
    )
    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            await postgres_session.delete(referenced_record)
            await postgres_session.flush()


async def test_notification_is_unique_per_alert_and_forecast_date(
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
    postgres_session.add(alert)
    await postgres_session.flush()

    first = Notification(
        alert_id=alert.id,
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date.today(),
        probability=75,
        threshold=60,
    )
    duplicate = Notification(
        alert_id=alert.id,
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date.today(),
        probability=80,
        threshold=60,
    )
    postgres_session.add(first)
    await postgres_session.flush()

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(duplicate)
            await postgres_session.flush()


@pytest.mark.parametrize("probability", [-1, 101])
async def test_forecast_probability_must_be_between_zero_and_one_hundred(
    postgres_session: AsyncSession,
    sample_fields: list[Field],
    probability: int,
) -> None:
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date.today() + timedelta(days=1),
        probability=probability,
    )

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(forecast)
            await postgres_session.flush()


@pytest.mark.parametrize("threshold", [0, 101])
async def test_alert_threshold_must_be_between_one_and_one_hundred(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
    threshold: int,
) -> None:
    alert = Alert(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        threshold=threshold,
    )

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(alert)
            await postgres_session.flush()
