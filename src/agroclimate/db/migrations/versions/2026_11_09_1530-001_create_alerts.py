"""create alerts table

Revision ID: 001_create_alerts
Revises:
Create Date: 2026-11-09 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_create_alerts"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EVENT_TYPES = ("frost", "rain", "hail", "strong_wind", "heat")


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "threshold BETWEEN 1 AND 100",
            name=op.f("ck_alerts_threshold_range"),
        ),
        sa.ForeignKeyConstraint(
            ["field_id"],
            ["fields.id"],
            name=op.f("fk_alerts_field_id_fields"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_alerts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint(
            "user_id",
            "field_id",
            "event_type",
            name=op.f("uq_alerts_user_id_field_id_event_type"),
        ),
    )
    op.create_index(
        "ix_alerts_active_field_event_type",
        "alerts",
        ["field_id", "event_type"],
        unique=False,
        postgresql_where=sa.text("active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_active_field_event_type", table_name="alerts")
    op.drop_table("alerts")
