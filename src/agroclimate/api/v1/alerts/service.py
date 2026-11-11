from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import (
    Select,
    delete,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.api.v1.alerts.schemas import AlertCreate, AlertUpdate
from agroclimate.api.v1.pagination import decode_cursor, encode_cursor
from agroclimate.db.models import Alert, EventType, Field


def _accessible_fields(user_id: UUID) -> Select[UUID]:
    return select(Field.id).where(Field.related_users.contains([user_id]))


def _alert_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Alert not found",
    )


async def create_alert(
    session: AsyncSession,
    user_id: UUID,
    payload: AlertCreate,
) -> Alert:
    has_access = await session.scalar(
        _accessible_fields(user_id)
        .where(Field.id == payload.field_id)
        .exists()
        .select()
    )
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Field not found or not accessible",
        )

    statement = (
        insert(Alert)
        .values(
            created_by=user_id,
            field_id=payload.field_id,
            event_type=payload.event_type,
            threshold=payload.threshold,
        )
        .on_conflict_do_nothing(constraint="uq_alerts_field_id_event_type")
        .returning(Alert)
    )
    alert = await session.scalar(statement)
    if alert is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An alert already exists for this field and event",
        )

    await session.commit()
    return alert


async def list_alerts(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int,
    cursor: str | None,
    field_id: UUID | None,
    event_type: EventType | None,
    active: bool | None,
) -> tuple[list[Alert], str | None]:
    statement = select(Alert).where(
        Alert.field_id.in_(_accessible_fields(user_id))
    )

    if field_id is not None:
        statement = statement.where(Alert.field_id == field_id)
    if event_type is not None:
        statement = statement.where(Alert.event_type == event_type)
    if active is not None:
        statement = statement.where(Alert.active.is_(active))
    if cursor is not None:
        decoded_cursor = decode_cursor(cursor)
        statement = statement.where(
            tuple_(Alert.created_at, Alert.id)
            < tuple_(decoded_cursor.created_at, decoded_cursor.item_id)
        )

    statement = statement.order_by(
        Alert.created_at.desc(), Alert.id.desc()
    ).limit(limit + 1)
    alerts = list((await session.scalars(statement)).all())
    has_more = len(alerts) > limit
    page = alerts[:limit]
    next_cursor = (
        encode_cursor(page[-1].created_at, page[-1].id)
        if has_more and page
        else None
    )
    return page, next_cursor


async def get_alert(
    session: AsyncSession,
    user_id: UUID,
    alert_id: UUID,
) -> Alert:
    alert = await session.scalar(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.field_id.in_(_accessible_fields(user_id)),
        )
    )
    if alert is None:
        raise _alert_not_found()
    return alert


async def update_alert(
    session: AsyncSession,
    user_id: UUID,
    alert_id: UUID,
    payload: AlertUpdate,
) -> Alert:
    statement = (
        update(Alert)
        .where(
            Alert.id == alert_id,
            Alert.field_id.in_(_accessible_fields(user_id)),
        )
        .values(**payload.model_dump(exclude_unset=True))
        .returning(Alert)
    )
    alert = await session.scalar(statement)
    if alert is None:
        await session.rollback()
        raise _alert_not_found()

    await session.commit()
    return alert


async def delete_alert(
    session: AsyncSession,
    user_id: UUID,
    alert_id: UUID,
) -> None:
    statement = (
        delete(Alert)
        .where(
            Alert.id == alert_id,
            Alert.field_id.in_(_accessible_fields(user_id)),
        )
        .returning(Alert.id)
    )
    if await session.scalar(statement) is None:
        await session.rollback()
        raise _alert_not_found()
    await session.commit()
