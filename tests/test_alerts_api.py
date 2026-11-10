from uuid import UUID

import httpx2
import pytest

from agroclimate.db.models import EventType, Field, User


@pytest.mark.parametrize("missing_header", [True, False])
async def test_create_alert_requires_a_valid_user_header(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
    sample_fields: list[Field],
    missing_header: bool,
) -> None:
    headers = (
        {} if missing_header else {"X-User-Id": "not-a-uuid"}
    )
    response = await api_client.post(
        "/api/v1/alerts",
        headers=headers,
        json={
            "field_id": str(sample_fields[0].id),
            "event_type": "rain",
            "threshold": 60,
        },
    )

    assert response.status_code == (401 if missing_header else 422)


async def test_create_alert_and_reject_duplicate(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    headers = {"X-User-Id": str(sample_users[0].id)}
    payload = {
        "field_id": str(sample_fields[0].id),
        "event_type": EventType.RAIN.value,
        "threshold": 60,
    }

    created = await api_client.post(
        "/api/v1/alerts", headers=headers, json=payload
    )
    duplicate = await api_client.post(
        "/api/v1/alerts", headers=headers, json=payload
    )

    assert created.status_code == 201
    assert created.json()["threshold"] == 60
    assert created.json()["active"] is True
    assert duplicate.status_code == 409


async def test_create_alert_requires_field_access(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    response = await api_client.post(
        "/api/v1/alerts",
        headers={"X-User-Id": str(sample_users[0].id)},
        json={
            "field_id": str(sample_fields[1].id),
            "event_type": "rain",
            "threshold": 60,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Field not found"


async def test_alert_crud_and_owner_isolation(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    owner_headers = {"X-User-Id": str(sample_users[0].id)}
    other_headers = {"X-User-Id": str(sample_users[1].id)}
    created = await api_client.post(
        "/api/v1/alerts",
        headers=owner_headers,
        json={
            "field_id": str(sample_fields[0].id),
            "event_type": "hail",
            "threshold": 40,
        },
    )
    assert created.status_code == 201
    alert_id = created.json()["id"]

    updated = await api_client.patch(
        f"/api/v1/alerts/{alert_id}",
        headers=owner_headers,
        json={"threshold": 85, "active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["threshold"] == 85
    assert updated.json()["active"] is False

    fetched = await api_client.get(
        f"/api/v1/alerts/{alert_id}", headers=owner_headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == alert_id

    other_get = await api_client.get(
        f"/api/v1/alerts/{alert_id}", headers=other_headers
    )
    other_patch = await api_client.patch(
        f"/api/v1/alerts/{alert_id}",
        headers=other_headers,
        json={"threshold": 90},
    )
    other_delete = await api_client.delete(
        f"/api/v1/alerts/{alert_id}", headers=other_headers
    )
    assert other_get.status_code == 404
    assert other_patch.status_code == 404
    assert other_delete.status_code == 404

    deleted = await api_client.delete(
        f"/api/v1/alerts/{alert_id}", headers=owner_headers
    )
    assert deleted.status_code == 204


async def test_alert_list_uses_keyset_pagination_and_user_scope(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    headers = {"X-User-Id": str(sample_users[0].id)}
    for field_id, event_type in (
        (sample_fields[0].id, "rain"),
        (sample_fields[0].id, "frost"),
        (sample_fields[0].id, "hail"),
    ):
        response = await api_client.post(
            "/api/v1/alerts",
            headers=headers,
            json={
                "field_id": str(field_id),
                "event_type": event_type,
                "threshold": 50,
            },
        )
        assert response.status_code == 201

    first_page = await api_client.get(
        "/api/v1/alerts?limit=2", headers=headers
    )
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 2
    cursor = first_page.json()["next_cursor"]
    assert cursor

    second_page = await api_client.get(
        "/api/v1/alerts",
        headers=headers,
        params={"limit": 2, "cursor": cursor},
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["next_cursor"] is None

    other_user_page = await api_client.get(
        "/api/v1/alerts",
        headers={"X-User-Id": str(sample_users[1].id)},
    )
    assert other_user_page.status_code == 200
    assert other_user_page.json()["items"] == []


async def test_alert_validation_and_invalid_cursor(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    headers = {"X-User-Id": str(sample_users[0].id)}
    invalid_threshold = await api_client.post(
        "/api/v1/alerts",
        headers=headers,
        json={
            "field_id": str(sample_fields[0].id),
            "event_type": "rain",
            "threshold": 0,
        },
    )
    invalid_event = await api_client.post(
        "/api/v1/alerts",
        headers=headers,
        json={
            "field_id": str(sample_fields[0].id),
            "event_type": "snow",
            "threshold": 50,
        },
    )
    empty_patch = await api_client.patch(
        f"/api/v1/alerts/{UUID(int=1)}",
        headers=headers,
        json={},
    )
    invalid_cursor = await api_client.get(
        "/api/v1/alerts",
        headers=headers,
        params={"cursor": "not-a-cursor"},
    )

    assert invalid_threshold.status_code == 422
    assert invalid_event.status_code == 422
    assert empty_patch.status_code == 422
    assert invalid_cursor.status_code == 422


async def test_alert_list_filters(
    api_client: httpx2.AsyncClient,
    sample_users: list[User],
    sample_fields: list[Field],
) -> None:
    headers = {"X-User-Id": str(sample_users[0].id)}
    alert_ids: dict[str, str] = {}

    for event_type in ("rain", "frost", "hail"):
        response = await api_client.post(
            "/api/v1/alerts",
            headers=headers,
            json={
                "field_id": str(sample_fields[0].id),
                "event_type": event_type,
                "threshold": 50,
            },
        )
        assert response.status_code == 201
        alert_ids[event_type] = response.json()["id"]

    deactivated = await api_client.patch(
        f"/api/v1/alerts/{alert_ids['frost']}",
        headers=headers,
        json={"active": False},
    )
    assert deactivated.status_code == 200

    inactive = await api_client.get(
        "/api/v1/alerts",
        headers=headers,
        params={"active": False},
    )
    by_event = await api_client.get(
        "/api/v1/alerts",
        headers=headers,
        params={"event_type": "hail"},
    )
    by_field = await api_client.get(
        "/api/v1/alerts",
        headers=headers,
        params={"field_id": str(sample_fields[0].id)},
    )

    assert [item["id"] for item in inactive.json()["items"]] == [
        alert_ids["frost"]
    ]
    assert [item["id"] for item in by_event.json()["items"]] == [
        alert_ids["hail"]
    ]
    assert len(by_field.json()["items"]) == 3
