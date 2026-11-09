from enum import StrEnum

from sqlalchemy import Enum
from sqlalchemy.orm import MappedColumn, mapped_column


class EventType(StrEnum):
    FROST = "frost"
    RAIN = "rain"
    HAIL = "hail"
    STRONG_WIND = "strong_wind"
    HEAT = "heat"


def event_type_column() -> MappedColumn[EventType]:
    return mapped_column(
        Enum(
            EventType,
            name="event_type",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda members: [
                member.value for member in members
            ],
        )
    )
