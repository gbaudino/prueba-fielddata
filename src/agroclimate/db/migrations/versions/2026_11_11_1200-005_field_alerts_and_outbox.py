"""share alerts per field and add the notification outbox

Alerts stop belonging to a single user: one alert per (field, event)
is shared by every user of the field. Existing per-user alerts are
merged into the oldest one, which keeps its threshold, and their
notifications are re-pointed to it.

Revision ID: 005_field_alerts_and_outbox
Revises: 004_alerts_list_idx
Create Date: 2026-11-11 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_field_alerts_and_outbox"
down_revision: str | Sequence[str] | None = "004_alerts_list_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALERT_UNIQUE = "uq_alerts_field_id_event_type"
OLD_ALERT_UNIQUE = "uq_alerts_user_id_field_id_event_type"
NOTIFICATION_UNIQUE = "uq_notifications_alert_id_user_id_forecast_date"
OLD_NOTIFICATION_UNIQUE = "uq_notifications_alert_id_forecast_date"

# Rank alerts of the same (field, event) from oldest to newest.
RANKED_ALERTS = """
    SELECT
        id,
        first_value(id) OVER w AS keep_id,
        row_number() OVER w AS position
    FROM alerts
    WINDOW w AS (
        PARTITION BY field_id, event_type ORDER BY created_at, id
    )
"""


def upgrade() -> None:
    # First, so notifications of merged alerts can share a forecast date.
    op.drop_constraint(
        OLD_NOTIFICATION_UNIQUE, "notifications", type_="unique"
    )
    op.create_unique_constraint(
        NOTIFICATION_UNIQUE,
        "notifications",
        ["alert_id", "user_id", "forecast_date"],
    )

    op.add_column("alerts", sa.Column("created_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_alerts_created_by_users"),
        "alerts",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("UPDATE alerts SET created_by = user_id")
    op.execute(
        f"""
        WITH ranked AS ({RANKED_ALERTS})
        UPDATE notifications AS n
        SET alert_id = ranked.keep_id
        FROM ranked
        WHERE n.alert_id = ranked.id AND ranked.position > 1
        """
    )
    op.execute(
        f"""
        WITH ranked AS ({RANKED_ALERTS})
        DELETE FROM alerts AS a
        USING ranked
        WHERE a.id = ranked.id AND ranked.position > 1
        """
    )
    op.drop_index("ix_alerts_user_created_id", table_name="alerts")
    op.drop_constraint(OLD_ALERT_UNIQUE, "alerts", type_="unique")
    op.drop_constraint("fk_alerts_user_id_users", "alerts", type_="foreignkey")
    op.drop_column("alerts", "user_id")
    op.create_unique_constraint(
        ALERT_UNIQUE, "alerts", ["field_id", "event_type"]
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_events_unpublished_created_id",
        "outbox_events",
        ["created_at", "id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_events_unpublished_created_id",
        table_name="outbox_events",
    )
    op.drop_table("outbox_events")

    op.add_column("alerts", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE alerts AS a
        SET user_id = coalesce(a.created_by, f.related_users[1])
        FROM fields AS f
        WHERE f.id = a.field_id
        """
    )
    op.execute("DELETE FROM alerts WHERE user_id IS NULL")
    op.alter_column("alerts", "user_id", nullable=False)
    op.drop_constraint(ALERT_UNIQUE, "alerts", type_="unique")
    op.drop_constraint(
        op.f("fk_alerts_created_by_users"), "alerts", type_="foreignkey"
    )
    op.drop_column("alerts", "created_by")
    op.create_foreign_key(
        "fk_alerts_user_id_users",
        "alerts",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        OLD_ALERT_UNIQUE, "alerts", ["user_id", "field_id", "event_type"]
    )
    op.create_index(
        "ix_alerts_user_created_id",
        "alerts",
        ["user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )

    # The old schema kept one notification per (alert, forecast date).
    op.drop_constraint(NOTIFICATION_UNIQUE, "notifications", type_="unique")
    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY alert_id, forecast_date
                ORDER BY created_at, id
            ) AS position
            FROM notifications
            WHERE alert_id IS NOT NULL
        )
        DELETE FROM notifications AS n
        USING ranked
        WHERE n.id = ranked.id AND ranked.position > 1
        """
    )
    op.create_unique_constraint(
        OLD_NOTIFICATION_UNIQUE,
        "notifications",
        ["alert_id", "forecast_date"],
    )
