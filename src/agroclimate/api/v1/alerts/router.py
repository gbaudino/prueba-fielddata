from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from agroclimate.api.dependencies import CurrentUserDep, SessionDep
from agroclimate.api.v1.alerts import service
from agroclimate.api.v1.alerts.schemas import (
    AlertCreate,
    AlertList,
    AlertRead,
    AlertUpdate,
)
from agroclimate.db.models.events import EventType

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post(
    "",
    response_model=AlertRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert(
    payload: AlertCreate,
    session: SessionDep,
    user_id: CurrentUserDep,
) -> AlertRead:
    alert = await service.create_alert(session, user_id, payload)
    return AlertRead.model_validate(alert)


@router.get("", response_model=AlertList)
async def list_alerts(
    session: SessionDep,
    user_id: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    field_id: UUID | None = None,
    event_type: EventType | None = None,
    active: bool | None = None,
) -> AlertList:
    items, next_cursor = await service.list_alerts(
        session,
        user_id,
        limit=limit,
        cursor=cursor,
        field_id=field_id,
        event_type=event_type,
        active=active,
    )
    return AlertList(
        items=[AlertRead.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/{alert_id}", response_model=AlertRead)
async def get_alert(
    alert_id: UUID,
    session: SessionDep,
    user_id: CurrentUserDep,
) -> AlertRead:
    alert = await service.get_alert(session, user_id, alert_id)
    return AlertRead.model_validate(alert)


@router.patch("/{alert_id}", response_model=AlertRead)
async def update_alert(
    alert_id: UUID,
    payload: AlertUpdate,
    session: SessionDep,
    user_id: CurrentUserDep,
) -> AlertRead:
    alert = await service.update_alert(session, user_id, alert_id, payload)
    return AlertRead.model_validate(alert)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: UUID,
    session: SessionDep,
    user_id: CurrentUserDep,
) -> Response:
    await service.delete_alert(session, user_id, alert_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
