from typing import cast

from sqlalchemy import CheckConstraint, Enum, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.schema import ColumnDefault
from sqlalchemy.types import Uuid

from agroclimate.db.base import Base
from agroclimate.db.models import (
    Alert,
    EventType,
    Field,
    Notification,
    User,
    WeatherForecast,
)


def table_for(model: type[Base]) -> Table:
    """Narrow the declarative __table__ typing to SQLAlchemy Table."""
    return cast(Table, model.__table__)


def test_all_domain_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "fields",
        "weather_forecasts",
        "alerts",
        "notifications",
    }


def test_upstream_tables_are_marked_as_external() -> None:
    for model in (User, Field, WeatherForecast):
        assert table_for(model).info["is_external"] is True


def test_all_primary_keys_use_native_uuid_types() -> None:
    for model in (User, Field, WeatherForecast, Alert, Notification):
        id_type = table_for(model).c.id.type
        assert isinstance(id_type, Uuid)
        assert id_type.as_uuid is True


def test_service_owned_ids_use_uuidv4_defaults() -> None:
    for model in (Alert, Notification):
        default = table_for(model).c.id.default
        assert isinstance(default, ColumnDefault)
        generated_id = default.arg(None)
        assert generated_id.version == 4


def test_field_related_users_is_a_uuid_array() -> None:
    related_users_type = table_for(Field).c.related_users.type

    assert isinstance(related_users_type, ARRAY)
    assert isinstance(related_users_type.item_type, Uuid)


def test_alerts_are_unique_per_user_field_and_event() -> None:
    unique_constraint = next(
        constraint
        for constraint in table_for(Alert).constraints
        if isinstance(constraint, UniqueConstraint)
    )

    assert tuple(column.name for column in unique_constraint.columns) == (
        "user_id",
        "field_id",
        "event_type",
    )


def test_probability_and_threshold_ranges_are_valid() -> None:
    checks = {
        table.name: {
            str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        for table in (
            table_for(WeatherForecast),
            table_for(Alert),
            table_for(Notification),
        )
    }

    assert "probability BETWEEN 1 AND 100" in checks["weather_forecasts"]
    assert "threshold BETWEEN 1 AND 100" in checks["alerts"]
    assert "probability BETWEEN 1 AND 100" in checks["notifications"]
    assert "threshold BETWEEN 1 AND 100" in checks["notifications"]


def test_event_type_is_a_string_enum_with_expected_values() -> None:
    assert [event.value for event in EventType] == [
        "frost",
        "rain",
        "hail",
        "strong_wind",
        "heat",
    ]

    event_type = table_for(Alert).c.event_type.type
    assert isinstance(event_type, Enum)
    assert event_type.native_enum is False
    assert event_type.create_constraint is True


def test_notifications_reference_existing_user_and_field() -> None:
    user_foreign_key = next(
        iter(table_for(Notification).c.user_id.foreign_keys)
    )
    field_foreign_key = next(
        iter(table_for(Notification).c.field_id.foreign_keys)
    )

    assert user_foreign_key.target_fullname == "users.id"
    assert user_foreign_key.ondelete == "RESTRICT"
    assert field_foreign_key.target_fullname == "fields.id"
    assert field_foreign_key.ondelete == "RESTRICT"
    assert table_for(Notification).c.alert_id.foreign_keys
