from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from agroclimate.db.base import Base
from agroclimate.db.models.events import EventType, event_type_column


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "probability BETWEEN 1 AND 100", name="probability_range"
        ),
        CheckConstraint("threshold BETWEEN 1 AND 100", name="threshold_range"),
        UniqueConstraint("alert_id", "user_id", "forecast_date"),
        Index("ix_notifications_field_id", "field_id"),
        Index(
            "ix_notifications_user_created_id",
            "user_id",
            desc("created_at"),
            desc("id"),
        ),
        Index(
            "ix_notifications_user_unread_created_id",
            "user_id",
            desc("created_at"),
            desc("id"),
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    alert_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    field_id: Mapped[UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="RESTRICT")
    )
    event_type: Mapped[EventType] = event_type_column()
    forecast_date: Mapped[date] = mapped_column(Date)
    probability: Mapped[int] = mapped_column(SmallInteger)
    threshold: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
