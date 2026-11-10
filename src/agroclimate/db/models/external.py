from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from agroclimate.db.base import Base
from agroclimate.db.models.events import EventType, event_type_column


class User(Base):
    __tablename__ = "users"
    __table_args__ = ({"info": {"is_external": True}},)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone_number: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Field(Base):
    __tablename__ = "fields"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint(
            "longitude BETWEEN -180 AND 180", name="longitude_range"
        ),
        Index(
            "ix_fields_related_users",
            "related_users",
            postgresql_using="gin",
        ),
        {"info": {"is_external": True}},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    related_users: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'::uuid[]"),
    )
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WeatherForecast(Base):
    __tablename__ = "weather_forecasts"
    __table_args__ = (
        UniqueConstraint("field_id", "event_type", "forecast_date"),
        CheckConstraint(
            "probability BETWEEN 0 AND 100", name="probability_range"
        ),
        {"info": {"is_external": True}},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    field_id: Mapped[UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE")
    )
    event_type: Mapped[EventType] = event_type_column()
    forecast_date: Mapped[date] = mapped_column(Date)
    probability: Mapped[int] = mapped_column(SmallInteger)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
