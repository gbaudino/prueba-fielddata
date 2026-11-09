"""create notifications table

Revision ID: 002_create_notifications
Revises: 001_create_alerts
Create Date: 2026-11-09 15:31:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_create_notifications"
down_revision: str | Sequence[str] | None = "001_create_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EVENT_TYPES = ("frost", "rain", "hail", "strong_wind", "heat")


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                *EVENT_TYPES,
                name="event_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("probability", sa.SmallInteger(), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "probability BETWEEN 1 AND 100",
            name=op.f("ck_notifications_probability_range"),
        ),
        sa.CheckConstraint(
            "threshold BETWEEN 1 AND 100",
            name=op.f("ck_notifications_threshold_range"),
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name=op.f("fk_notifications_alert_id_alerts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "alert_id",
            "forecast_date",
            name=op.f("uq_notifications_alert_id_forecast_date"),
        ),
    )
    op.create_index(
        "ix_notifications_user_created_id",
        "notifications",
        ["user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_unread_created_id",
        "notifications",
        ["user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_user_unread_created_id",
        table_name="notifications",
    )
    op.drop_index(
        "ix_notifications_user_created_id",
        table_name="notifications",
    )
    op.drop_table("notifications")
