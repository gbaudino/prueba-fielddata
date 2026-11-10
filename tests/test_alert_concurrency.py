import asyncio
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from agroclimate.api.v1.alerts.schemas import AlertCreate
from agroclimate.api.v1.alerts.service import create_alert
from agroclimate.db.models import Alert, EventType, Field, User


async def test_concurrent_alert_creates_keep_the_unique_constraint(
    postgres_engine: AsyncEngine,
) -> None:
    user = User(id=uuid4(), name="Alert Concurrency User")
    field = Field(
        id=uuid4(),
        name="Alert Concurrency Field",
        related_users=[user.id],
        latitude=-31.4,
        longitude=-64.2,
        timezone="America/Argentina/Cordoba",
    )
    session_factory = async_sessionmaker(
        postgres_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            session.add(user)
            await session.flush()
            session.add(field)
            await session.commit()

        async def create() -> int:
            payload = AlertCreate(
                field_id=field.id,
                event_type=EventType.RAIN,
                threshold=60,
            )
            async with session_factory() as session:
                try:
                    await create_alert(session, user.id, payload)
                except HTTPException as exc:
                    return exc.status_code
                return 201

        results = await asyncio.gather(create(), create())

        async with session_factory() as session:
            alert_count = await session.scalar(
                select(func.count())
                .select_from(Alert)
                .where(Alert.user_id == user.id)
            )

        assert sorted(results) == [201, 409]
        assert alert_count == 1
    finally:
        async with postgres_engine.begin() as connection:
            await connection.execute(
                delete(Alert).where(Alert.user_id == user.id)
            )
            await connection.execute(delete(Field).where(Field.id == field.id))
            await connection.execute(delete(User).where(User.id == user.id))
