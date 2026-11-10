from datetime import datetime

from sqlalchemy import Date, DateTime, cast, func, literal, select
from sqlalchemy.dialects.postgresql import array, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Uuid

from agroclimate.db.models import Alert, Field, Notification, WeatherForecast


async def evaluate_alerts(
    session: AsyncSession,
    *,
    evaluated_at: datetime | None = None,
) -> int:
    """Create one notification per matching alert and forecast date."""
    if evaluated_at is not None and evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    reference_time = (
        literal(evaluated_at, type_=DateTime(timezone=True))
        if evaluated_at is not None
        else func.statement_timestamp()
    )
    field_local_date = cast(
        func.timezone(Field.timezone, reference_time),
        Date,
    )

    source = (
        select(
            cast(func.gen_random_uuid(), Uuid(as_uuid=True)),
            Alert.id,
            Alert.user_id,
            Alert.field_id,
            Alert.event_type,
            WeatherForecast.forecast_date,
            WeatherForecast.probability,
            Alert.threshold,
            reference_time,
        )
        .select_from(Alert)
        .join(Field, Field.id == Alert.field_id)
        .join(
            WeatherForecast,
            (WeatherForecast.field_id == Alert.field_id)
            & (WeatherForecast.event_type == Alert.event_type),
        )
        .where(
            Alert.active.is_(True),
            Field.related_users.contains(array([Alert.user_id])),
            WeatherForecast.probability >= Alert.threshold,
            WeatherForecast.forecast_date >= field_local_date,
        )
    )

    statement = (
        insert(Notification)
        .from_select(
            [
                "id",
                "alert_id",
                "user_id",
                "field_id",
                "event_type",
                "forecast_date",
                "probability",
                "threshold",
                "created_at",
            ],
            source,
        )
        .on_conflict_do_nothing(
            constraint="uq_notifications_alert_id_forecast_date"
        )
        .returning(Notification.id)
    )

    try:
        result = await session.execute(statement)
        created_count = len(result.scalars().all())
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return created_count
