from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.db.models import EventType, Field, User, WeatherForecast
from agroclimate.services.evaluation.main import evaluate_alerts


async def test_alert_flow_generates_a_queryable_notification(
    api_client: httpx2.AsyncClient,
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    user = sample_users[0]
    field = sample_fields[0]
    headers = {"X-User-Id": str(user.id)}

    created = await api_client.post(
        "/v1/alerts",
        headers=headers,
        json={
            "field_id": str(field.id),
            "event_type": EventType.RAIN.value,
            "threshold": 60,
        },
    )
    assert created.status_code == 201

    evaluated_at = datetime.now(UTC)
    local_date = evaluated_at.astimezone(ZoneInfo(field.timezone)).date()
    forecast = WeatherForecast(
        id=uuid4(),
        field_id=field.id,
        event_type=EventType.RAIN,
        forecast_date=local_date + timedelta(days=1),
        probability=85,
    )
    postgres_session.add(forecast)
    await postgres_session.flush()

    created_notifications = await evaluate_alerts(
        postgres_session,
        evaluated_at=evaluated_at,
    )
    assert created_notifications == 1

    response = await api_client.get(
        "/v1/notifications",
        headers=headers,
        params={"unread": True},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["field_id"] == str(field.id)
    assert items[0]["event_type"] == EventType.RAIN.value
    assert items[0]["probability"] == 85
    assert items[0]["threshold"] == 60
