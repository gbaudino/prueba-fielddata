from datetime import date, timedelta
from uuid import UUID, uuid4

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


def rain_notification(
    *,
    user_id: UUID,
    field_id: UUID,
    alert_id: UUID | None = None,
    forecast_date: date | None = None,
    probability: int = 75,
) -> Notification:
    return Notification(
        alert_id=alert_id,
        user_id=user_id,
        field_id=field_id,
        event_type=EventType.RAIN,
        forecast_date=forecast_date or date.today(),
        probability=probability,
        threshold=60,
    )


async def add_rain_alert(
    session: AsyncSession, user: User, field: Field
) -> Alert:
    alert = Alert(
        created_by=user.id,
        field_id=field.id,
        event_type=EventType.RAIN,
        threshold=60,
    )
    session.add(alert)
    await session.flush()
    return alert


@pytest.mark.parametrize("record_type", ["user", "field"])
async def test_notifications_restrict_deleting_referenced_external_records(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
    record_type: str,
) -> None:
    postgres_session.add(
        rain_notification(
            user_id=sample_users[0].id,
            field_id=sample_fields[0].id,
        )
    )
    await postgres_session.flush()

    referenced_record = (
        sample_users[0] if record_type == "user" else sample_fields[0]
    )
    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            await postgres_session.delete(referenced_record)
            await postgres_session.flush()


async def test_notification_is_unique_per_alert_user_and_forecast_date(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = await add_rain_alert(
        postgres_session, sample_users[0], sample_fields[0]
    )
    postgres_session.add(
        rain_notification(
            alert_id=alert.id,
            user_id=sample_users[0].id,
            field_id=sample_fields[0].id,
        )
    )
    await postgres_session.flush()

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(
                rain_notification(
                    alert_id=alert.id,
                    user_id=sample_users[0].id,
                    field_id=sample_fields[0].id,
                    probability=90,
                )
            )
            await postgres_session.flush()


async def test_notification_can_repeat_for_another_user_or_date(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    alert = await add_rain_alert(
        postgres_session, sample_users[0], sample_fields[0]
    )
    postgres_session.add_all(
        [
            rain_notification(
                alert_id=alert.id,
                user_id=sample_users[0].id,
                field_id=sample_fields[0].id,
            ),
            rain_notification(
                alert_id=alert.id,
                user_id=sample_users[1].id,
                field_id=sample_fields[0].id,
            ),
            rain_notification(
                alert_id=alert.id,
                user_id=sample_users[0].id,
                field_id=sample_fields[0].id,
                forecast_date=date.today() + timedelta(days=1),
            ),
        ]
    )
    await postgres_session.flush()


@pytest.mark.parametrize("probability", [0, 101])
async def test_notification_probability_must_be_between_one_and_one_hundred(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
    probability: int,
) -> None:
    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(
                rain_notification(
                    user_id=sample_users[0].id,
                    field_id=sample_fields[0].id,
                    probability=probability,
                )
            )
            await postgres_session.flush()


async def test_alert_is_unique_per_field_and_event(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    await add_rain_alert(postgres_session, sample_users[0], sample_fields[0])

    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            await add_rain_alert(
                postgres_session, sample_users[1], sample_fields[0]
            )


@pytest.mark.parametrize("threshold", [0, 101])
async def test_alert_threshold_must_be_between_one_and_one_hundred(
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
    threshold: int,
) -> None:
    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(
                Alert(
                    created_by=sample_users[0].id,
                    field_id=sample_fields[0].id,
                    event_type=EventType.RAIN,
                    threshold=threshold,
                )
            )
            await postgres_session.flush()


@pytest.mark.parametrize("probability", [-1, 101])
async def test_forecast_probability_must_be_between_zero_and_one_hundred(
    postgres_session: AsyncSession,
    sample_fields: list[Field],
    probability: int,
) -> None:
    with pytest.raises(IntegrityError):
        async with postgres_session.begin_nested():
            postgres_session.add(
                WeatherForecast(
                    id=uuid4(),
                    field_id=sample_fields[0].id,
                    event_type=EventType.RAIN,
                    forecast_date=date.today() + timedelta(days=1),
                    probability=probability,
                )
            )
            await postgres_session.flush()
