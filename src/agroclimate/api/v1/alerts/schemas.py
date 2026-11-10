from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agroclimate.db.models.events import EventType


class AlertCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: UUID
    event_type: EventType
    threshold: int = Field(ge=1, le=100)


class AlertUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: int | None = Field(default=None, ge=1, le=100)
    active: bool | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> "AlertUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "threshold" in self.model_fields_set and self.threshold is None:
            raise ValueError("threshold cannot be null")
        if "active" in self.model_fields_set and self.active is None:
            raise ValueError("active cannot be null")
        return self


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    field_id: UUID
    event_type: EventType
    threshold: int
    active: bool
    created_at: datetime
    updated_at: datetime


class AlertList(BaseModel):
    items: list[AlertRead]
    next_cursor: str | None
