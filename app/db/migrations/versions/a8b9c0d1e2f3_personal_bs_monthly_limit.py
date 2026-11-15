"""personal monthly BS limit override

Revision ID: a8b9c0d1e2f3
Revises: f7b8c9d0e1a2
Create Date: 2026-11-16 02:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "f7b8c9d0e1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("bs_monthly_limit", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("bs_monthly_limit")
