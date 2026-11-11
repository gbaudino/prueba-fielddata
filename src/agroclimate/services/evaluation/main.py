from datetime import datetime
from typing import Any
from typing import cast as typing_cast

from sqlalchemy import (
    CursorResult,
    Date,
    DateTime,
    cast,
    func,
    literal,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Uuid

from agroclimate.db.models import (
    Alert,
    Field,
    Notification,
    OutboxEvent,
    WeatherForecast,
)

NOTIFICATION_CREATED = "notification.created"


async def evaluate_alerts(
    session: AsyncSession,
    *,
    evaluated_at: datetime | None = None,
) -> int:
    """Notify every user of a field about each forecast over a threshold.

    Notifications and their outbox events are written by one statement,
    so they are committed or rolled back together, and the number of
    bind parameters does not grow with the number of notifications.
    """
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
    related_user = func.unnest(Field.related_users).alias("related_user")

    candidates = (
        select(
            cast(func.gen_random_uuid(), Uuid(as_uuid=True)),
            Alert.id,
            related_user.column,
            Alert.field_id,
            Alert.event_type,
            WeatherForecast.forecast_date,
            WeatherForecast.probability,
            Alert.threshold,
        )
        .select_from(Alert)
        .join(Field, Field.id == Alert.field_id)
        .join(
            WeatherForecast,
            (WeatherForecast.field_id == Alert.field_id)
            & (WeatherForecast.event_type == Alert.event_type),
        )
        .join(related_user, true())
        .where(
            Alert.active.is_(True),
            WeatherForecast.forecast_date >= field_local_date,
            WeatherForecast.probability >= Alert.threshold,
        )
    )

    created = (
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
            ],
            candidates,
        )
        .on_conflict_do_nothing(
            constraint="uq_notifications_alert_id_user_id_forecast_date"
        )
        .returning(
            Notification.id,
            Notification.alert_id,
            Notification.user_id,
            Notification.field_id,
            Notification.event_type,
            Notification.forecast_date,
            Notification.probability,
            Notification.threshold,
            Notification.created_at,
        )
        .cte("created")
    )

    payload = func.jsonb_build_object(
        "notification_id",
        created.c.id,
        "alert_id",
        created.c.alert_id,
        "user_id",
        created.c.user_id,
        "field_id",
        created.c.field_id,
        "event_type",
        created.c.event_type,
        "forecast_date",
        created.c.forecast_date,
        "probability",
        created.c.probability,
        "threshold",
        created.c.threshold,
        "created_at",
        created.c.created_at,
    )
    statement = insert(OutboxEvent).from_select(
        ["id", "event_type", "aggregate_type", "aggregate_id", "payload"],
        select(
            cast(func.gen_random_uuid(), Uuid(as_uuid=True)),
            literal(NOTIFICATION_CREATED),
            literal("notification"),
            created.c.id,
            payload,
        ),
    )

    try:
        result = await session.execute(statement)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    # One outbox row is inserted per created notification.
    return typing_cast("CursorResult[Any]", result).rowcount
