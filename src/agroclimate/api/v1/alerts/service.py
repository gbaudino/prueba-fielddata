from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import (
    SmallInteger,
    String,
    delete,
    func,
    literal,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Uuid

from agroclimate.api.v1.alerts.schemas import AlertCreate, AlertUpdate
from agroclimate.api.v1.pagination import decode_cursor, encode_cursor
from agroclimate.db.models import Alert, EventType, Field, User


async def create_alert(
    session: AsyncSession,
    user_id: UUID,
    payload: AlertCreate,
) -> Alert:
    user_exists = select(User.id).where(User.id == user_id).exists()
    source = select(
        literal(uuid4(), type_=Uuid(as_uuid=True)),
        literal(user_id, type_=Uuid(as_uuid=True)),
        Field.id,
        literal(payload.event_type.value, type_=String(32)),
        literal(payload.threshold, type_=SmallInteger()),
    ).where(
        Field.id == payload.field_id,
        Field.related_users.contains([user_id]),
        user_exists,
    )
    statement = (
        insert(Alert)
        .from_select(
            [
                "id",
                "user_id",
                "field_id",
                "event_type",
                "threshold",
            ],
            source,
        )
        .on_conflict_do_nothing(
            constraint="uq_alerts_user_id_field_id_event_type"
        )
        .returning(Alert)
    )
    result = await session.execute(statement)
    alert = result.scalar_one_or_none()

    if alert is None:
        accessible_field = await session.scalar(
            select(Field.id).where(
                Field.id == payload.field_id,
                Field.related_users.contains([user_id]),
                user_exists,
            )
        )
        await session.rollback()
        if accessible_field is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Field not found",
            )
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
    statement = select(Alert).where(Alert.user_id == user_id)

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
            Alert.user_id == user_id,
        )
    )
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    return alert


async def update_alert(
    session: AsyncSession,
    user_id: UUID,
    alert_id: UUID,
    payload: AlertUpdate,
) -> Alert:
    values = payload.model_dump(exclude_unset=True)
    statement = (
        update(Alert)
        .where(Alert.id == alert_id, Alert.user_id == user_id)
        .values(**values, updated_at=func.now())
        .returning(Alert)
    )
    result = await session.execute(statement)
    alert = result.scalar_one_or_none()
    if alert is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    await session.commit()
    return alert


async def delete_alert(
    session: AsyncSession,
    user_id: UUID,
    alert_id: UUID,
) -> None:
    statement = (
        delete(Alert)
        .where(Alert.id == alert_id, Alert.user_id == user_id)
        .returning(Alert.id)
    )
    deleted_id = await session.scalar(statement)
    if deleted_id is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    await session.commit()
