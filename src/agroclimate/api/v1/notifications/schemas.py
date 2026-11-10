from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agroclimate.db.models.events import EventType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_id: UUID | None
    field_id: UUID
    event_type: EventType
    forecast_date: date
    probability: int
    threshold: int
    created_at: datetime
    read_at: datetime | None


class NotificationList(BaseModel):
    items: list[NotificationRead]
    next_cursor: str | None


class NotificationMarkReadRequest(BaseModel):
    notification_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("notification_ids")
    @classmethod
    def notification_ids_must_be_unique(
        cls, notification_ids: list[UUID]
    ) -> list[UUID]:
        if len(notification_ids) != len(set(notification_ids)):
            raise ValueError("notification_ids must not contain duplicates")
        return notification_ids


class NotificationMarkReadResponse(BaseModel):
    marked_read: int
    notification_ids: list[UUID]
