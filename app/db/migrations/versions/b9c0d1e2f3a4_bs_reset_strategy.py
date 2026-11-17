"""independent rolling BS reset strategy

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-11-18 01:00:00.000000

Существующий расход текущего календарного месяца сохраняется и переводится в
новый rolling month, начинающийся в момент миграции. Поэтому обновление не
вызывает ни немедленного массового сброса, ни двойного учёта старой строки.
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = datetime.utcnow().replace(microsecond=0)
    legacy_period = now.strftime("%Y-%m")
    rolling_period = now.isoformat(timespec="seconds")

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("bs_reset_strategy", sa.String(length=10), nullable=False, server_default="month")
        )
        batch_op.add_column(sa.Column("bs_last_reset_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("node_user_bs_usage") as batch_op:
        batch_op.alter_column(
            "monthly_period",
            existing_type=sa.String(length=7),
            type_=sa.String(length=32),
            existing_nullable=True,
        )

    users = sa.table("users", sa.column("bs_last_reset_at", sa.DateTime()))
    usage = sa.table("node_user_bs_usage", sa.column("monthly_period", sa.String(length=32)))
    op.execute(users.update().values(bs_last_reset_at=now))
    op.execute(usage.update().where(usage.c.monthly_period == legacy_period).values(monthly_period=rolling_period))


def downgrade() -> None:
    # ISO-маркеры снова становятся календарными месяцами их начала. Расход не
    # удаляется; старые значения YYYY-MM остаются без изменений.
    op.execute(
        "UPDATE node_user_bs_usage SET monthly_period = substr(monthly_period, 1, 7) "
        "WHERE length(monthly_period) > 7"
    )
    with op.batch_alter_table("node_user_bs_usage") as batch_op:
        batch_op.alter_column(
            "monthly_period",
            existing_type=sa.String(length=32),
            type_=sa.String(length=7),
            existing_nullable=True,
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("bs_last_reset_at")
        batch_op.drop_column("bs_reset_strategy")
