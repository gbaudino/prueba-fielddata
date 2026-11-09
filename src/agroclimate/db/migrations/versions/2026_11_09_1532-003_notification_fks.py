"""Add foreign keys from notifications to upstream entities.

Revision ID: 003_notification_fks
Revises: 002_create_notifications
Create Date: 2026-11-09 15:32:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_notification_fks"
down_revision: str | Sequence[str] | None = "002_create_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        op.f("fk_notifications_user_id_users"),
        "notifications",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_notifications_field_id_fields"),
        "notifications",
        "fields",
        ["field_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_notifications_field_id",
        "notifications",
        ["field_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_field_id", table_name="notifications")
    op.drop_constraint(
        op.f("fk_notifications_field_id_fields"),
        "notifications",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_notifications_user_id_users"),
        "notifications",
        type_="foreignkey",
    )
