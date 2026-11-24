"""48-hour per-device VLESS credentials with rotation grace

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-11-25 00:00:00.000000

Существующие UUID не отзываются при обновлении: они получают новый срок
окончания через 48 часов от миграции. Значения previous изначально пусты.
"""

from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_devices") as batch_op:
        batch_op.add_column(sa.Column("vless_uuid_expires_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("previous_vless_uuid", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("previous_vless_uuid_expires_at", sa.DateTime(), nullable=True))

    devices = sa.table(
        "user_devices",
        sa.column("vless_uuid", sa.String(length=36)),
        sa.column("vless_uuid_expires_at", sa.DateTime()),
    )
    expires_at = datetime.utcnow().replace(microsecond=0) + timedelta(hours=48)
    op.execute(devices.update().where(devices.c.vless_uuid.isnot(None)).values(vless_uuid_expires_at=expires_at))


def downgrade() -> None:
    # Текущий UUID сохраняется и снова становится постоянным; временный previous
    # удаляется вместе с колонкой, поэтому downgrade не оставляет второй credential.
    with op.batch_alter_table("user_devices") as batch_op:
        batch_op.drop_column("previous_vless_uuid_expires_at")
        batch_op.drop_column("previous_vless_uuid")
        batch_op.drop_column("vless_uuid_expires_at")
