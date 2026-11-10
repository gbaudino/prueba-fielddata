from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.db.models import EventType, Field, Notification, User


async def test_notifications_are_scoped_and_filterable(
    api_client: httpx2.AsyncClient,
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    now = datetime.now(UTC)
    notifications = [
        Notification(
            user_id=sample_users[0].id,
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            forecast_date=date.today() + timedelta(days=1),
            probability=80,
            threshold=60,
            created_at=now,
        ),
        Notification(
            user_id=sample_users[0].id,
            field_id=sample_fields[1].id,
            event_type=EventType.FROST,
            forecast_date=date.today() + timedelta(days=2),
            probability=90,
            threshold=70,
            created_at=now - timedelta(minutes=1),
        ),
        Notification(
            user_id=sample_users[1].id,
            field_id=sample_fields[0].id,
            event_type=EventType.HAIL,
            forecast_date=date.today() + timedelta(days=3),
            probability=95,
            threshold=80,
            created_at=now - timedelta(minutes=2),
        ),
    ]
    notifications[1].read_at = now - timedelta(seconds=30)
    postgres_session.add_all(notifications)
    await postgres_session.flush()

    headers = {"X-User-Id": str(sample_users[0].id)}
    unread = await api_client.get(
        "/api/v1/notifications",
        headers=headers,
        params={"unread": True},
    )
    read = await api_client.get(
        "/api/v1/notifications",
        headers=headers,
        params={"unread": False},
    )
    field_filtered = await api_client.get(
        "/api/v1/notifications",
        headers=headers,
        params={"field_id": str(sample_fields[0].id)},
    )

    assert unread.status_code == 200
    assert [item["id"] for item in unread.json()["items"]] == [
        str(notifications[0].id)
    ]
    assert read.status_code == 200
    assert [item["id"] for item in read.json()["items"]] == [
        str(notifications[1].id)
    ]
    assert field_filtered.status_code == 200
    assert [item["id"] for item in field_filtered.json()["items"]] == [
        str(notifications[0].id)
    ]


async def test_notification_keyset_pagination(
    api_client: httpx2.AsyncClient,
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    now = datetime.now(UTC)
    notifications = [
        Notification(
            user_id=sample_users[0].id,
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            forecast_date=date.today() + timedelta(days=day),
            probability=70 + day,
            threshold=60,
            created_at=now - timedelta(minutes=day),
        )
        for day in (1, 2, 3)
    ]
    postgres_session.add_all(notifications)
    await postgres_session.flush()

    headers = {"X-User-Id": str(sample_users[0].id)}
    first_page = await api_client.get(
        "/api/v1/notifications",
        headers=headers,
        params={"limit": 2},
    )
    cursor = first_page.json()["next_cursor"]
    second_page = await api_client.get(
        "/api/v1/notifications",
        headers=headers,
        params={"limit": 2, "cursor": cursor},
    )

    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 2
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["next_cursor"] is None


async def test_mark_notifications_read_is_bulk_idempotent_and_private(
    api_client: httpx2.AsyncClient,
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    previous_read_at = datetime.now(UTC) - timedelta(days=1)
    notifications = [
        Notification(
            user_id=sample_users[0].id,
            field_id=sample_fields[0].id,
            event_type=EventType.RAIN,
            forecast_date=date.today() + timedelta(days=day),
            probability=75,
            threshold=60,
            read_at=previous_read_at if day == 3 else None,
        )
        for day in (1, 2, 3)
    ]
    foreign_notification = Notification(
        user_id=sample_users[1].id,
        field_id=sample_fields[0].id,
        event_type=EventType.HAIL,
        forecast_date=date.today() + timedelta(days=4),
        probability=90,
        threshold=80,
    )
    postgres_session.add_all([*notifications, foreign_notification])
    await postgres_session.flush()

    owner_headers = {"X-User-Id": str(sample_users[0].id)}
    notification_ids = [
        notifications[0].id,
        notifications[1].id,
        notifications[2].id,
        foreign_notification.id,
        uuid4(),
    ]
    payload = {"notification_ids": [str(item) for item in notification_ids]}

    first_read = await api_client.post(
        "/api/v1/notifications/read",
        headers=owner_headers,
        json=payload,
    )

    assert first_read.status_code == 200
    assert first_read.json()["marked_read"] == 2
    assert set(first_read.json()["notification_ids"]) == {
        str(notifications[0].id),
        str(notifications[1].id),
    }

    await postgres_session.refresh(notifications[0])
    await postgres_session.refresh(notifications[1])
    await postgres_session.refresh(notifications[2])
    await postgres_session.refresh(foreign_notification)
    assert notifications[0].read_at is not None
    assert notifications[1].read_at is not None
    assert notifications[2].read_at == previous_read_at
    assert foreign_notification.read_at is None

    second_read = await api_client.post(
        "/api/v1/notifications/read",
        headers=owner_headers,
        json=payload,
    )
    assert second_read.status_code == 200
    assert second_read.json() == {
        "marked_read": 0,
        "notification_ids": [],
    }


async def test_mark_one_notification_read_with_single_id(
    api_client: httpx2.AsyncClient,
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    notification = Notification(
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date.today() + timedelta(days=1),
        probability=75,
        threshold=60,
    )
    postgres_session.add(notification)
    await postgres_session.flush()

    response = await api_client.post(
        "/api/v1/notifications/read",
        headers={"X-User-Id": str(sample_users[0].id)},
        json={"notification_ids": [str(notification.id)]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "marked_read": 1,
        "notification_ids": [str(notification.id)],
    }


async def test_mark_notifications_read_validates_id_list(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
) -> None:
    headers = {"X-User-Id": str(sample_users[0].id)}
    endpoint = "/api/v1/notifications/read"

    empty_list = await api_client.post(
        endpoint,
        headers=headers,
        json={"notification_ids": []},
    )
    duplicate_ids = uuid4()
    duplicated_list = await api_client.post(
        endpoint,
        headers=headers,
        json={
            "notification_ids": [
                str(duplicate_ids),
                str(duplicate_ids),
            ]
        },
    )
    oversized_list = await api_client.post(
        endpoint,
        headers=headers,
        json={"notification_ids": [str(uuid4()) for _ in range(101)]},
    )

    assert empty_list.status_code == 422
    assert duplicated_list.status_code == 422
    assert oversized_list.status_code == 422


async def test_deleting_alert_preserves_notification_history(
    api_client: httpx2.AsyncClient,
    postgres_session: AsyncSession,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    headers = {"X-User-Id": str(sample_users[0].id)}
    created_alert = await api_client.post(
        "/api/v1/alerts",
        headers=headers,
        json={
            "field_id": str(sample_fields[0].id),
            "event_type": EventType.RAIN.value,
            "threshold": 60,
        },
    )
    assert created_alert.status_code == 201

    notification = Notification(
        alert_id=UUID(created_alert.json()["id"]),
        user_id=sample_users[0].id,
        field_id=sample_fields[0].id,
        event_type=EventType.RAIN,
        forecast_date=date.today() + timedelta(days=1),
        probability=75,
        threshold=60,
    )
    postgres_session.add(notification)
    await postgres_session.flush()

    deleted = await api_client.delete(
        f"/api/v1/alerts/{created_alert.json()['id']}",
        headers=headers,
    )
    assert deleted.status_code == 204

    await postgres_session.refresh(notification)
    assert notification.alert_id is None
    assert notification.probability == 75
    assert notification.threshold == 60
