from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from agroclimate.api.dependencies import CurrentUserIdDep, SessionDep
from agroclimate.api.v1.notifications import service
from agroclimate.api.v1.notifications.schemas import (
    NotificationList,
    NotificationMarkReadRequest,
    NotificationMarkReadResponse,
    NotificationRead,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
async def list_notifications(
    session: SessionDep,
    user_id: CurrentUserIdDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    unread: bool | None = None,
    field_id: UUID | None = None,
) -> NotificationList:
    items, next_cursor = await service.list_notifications(
        session,
        user_id,
        limit=limit,
        cursor=cursor,
        unread=unread,
        field_id=field_id,
    )
    return NotificationList(
        items=[NotificationRead.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )


@router.post("/read", response_model=NotificationMarkReadResponse)
async def mark_notifications_read(
    payload: NotificationMarkReadRequest,
    session: SessionDep,
    user_id: CurrentUserIdDep,
) -> NotificationMarkReadResponse:
    marked_ids = await service.mark_notifications_read(
        session,
        user_id,
        payload.notification_ids,
    )
    return NotificationMarkReadResponse(
        marked_read=len(marked_ids),
        notification_ids=marked_ids,
    )
