"""add alert owner pagination index

Revision ID: 004_alerts_list_idx
Revises: 003_notification_fks
Create Date: 2026-11-09 15:33:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_alerts_list_idx"
down_revision: str | Sequence[str] | None = "003_notification_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_alerts_user_created_id",
        "alerts",
        ["user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_user_created_id", table_name="alerts")
