from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from agroclimate.db.base import Base
from agroclimate.db.models.events import EventType, event_type_column


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("field_id", "event_type"),
        CheckConstraint("threshold BETWEEN 1 AND 100", name="threshold_range"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    field_id: Mapped[UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE")
    )
    event_type: Mapped[EventType] = event_type_column()
    threshold: Mapped[int] = mapped_column(SmallInteger)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
