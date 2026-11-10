from uuid import UUID

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from agroclimate.api.v1.pagination import decode_cursor, encode_cursor
from agroclimate.db.models import Notification


async def list_notifications(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int,
    cursor: str | None,
    unread: bool | None,
    field_id: UUID | None,
) -> tuple[list[Notification], str | None]:
    statement = select(Notification).where(Notification.user_id == user_id)

    if unread is True:
        statement = statement.where(Notification.read_at.is_(None))
    elif unread is False:
        statement = statement.where(Notification.read_at.is_not(None))
    if field_id is not None:
        statement = statement.where(Notification.field_id == field_id)
    if cursor is not None:
        decoded_cursor = decode_cursor(cursor)
        statement = statement.where(
            tuple_(Notification.created_at, Notification.id)
            < tuple_(decoded_cursor.created_at, decoded_cursor.item_id)
        )

    statement = statement.order_by(
        Notification.created_at.desc(), Notification.id.desc()
    ).limit(limit + 1)
    notifications = list((await session.scalars(statement)).all())
    has_more = len(notifications) > limit
    page = notifications[:limit]
    next_cursor = (
        encode_cursor(page[-1].created_at, page[-1].id)
        if has_more and page
        else None
    )
    return page, next_cursor


async def mark_notifications_read(
    session: AsyncSession,
    user_id: UUID,
    notification_ids: list[UUID],
) -> list[UUID]:
    statement = (
        update(Notification)
        .where(
            Notification.id.in_(notification_ids),
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=func.now())
        .returning(Notification.id)
    )
    result = await session.scalars(statement)
    marked_ids = list(result.all())
    await session.commit()
    return marked_ids
