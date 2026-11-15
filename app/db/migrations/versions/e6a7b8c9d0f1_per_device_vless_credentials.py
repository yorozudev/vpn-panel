"""add per-device VLESS credentials

Revision ID: e6a7b8c9d0f1
Revises: f3c8a91e2b47
Create Date: 2026-11-16 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e6a7b8c9d0f1"
down_revision = "f3c8a91e2b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_devices") as batch_op:
        batch_op.add_column(sa.Column("vless_uuid", sa.String(length=36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_devices") as batch_op:
        batch_op.drop_column("vless_uuid")
