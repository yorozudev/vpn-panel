"""safe per-user legacy VLESS migration

Revision ID: f7b8c9d0e1a2
Revises: e6a7b8c9d0f1
Create Date: 2026-11-16 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f7b8c9d0e1a2"
down_revision = "e6a7b8c9d0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("legacy_vless_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )
        batch_op.add_column(sa.Column("legacy_vless_last_activity_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("legacy_vless_disabled_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("user_devices") as batch_op:
        batch_op.add_column(sa.Column("vless_config_delivered_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_devices") as batch_op:
        batch_op.drop_column("vless_config_delivered_at")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("legacy_vless_disabled_at")
        batch_op.drop_column("legacy_vless_last_activity_at")
        batch_op.drop_column("legacy_vless_enabled")
