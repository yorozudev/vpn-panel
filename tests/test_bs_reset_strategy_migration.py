"""SQLite migration: сохранение текущего BS usage при переходе на rolling month."""

import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = Path(__file__).parent.parent / "app/db/migrations/versions/b9c0d1e2f3a4_bs_reset_strategy.py"
    spec = importlib.util.spec_from_file_location("bs_reset_strategy_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bs_reset_strategy_migration_preserves_current_usage():
    migration = _load_migration()
    assert migration.down_revision == "a8b9c0d1e2f3"
    engine = sa.create_engine("sqlite://")
    current_month = datetime.utcnow().strftime("%Y-%m")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(
            sa.text(
                "CREATE TABLE node_user_bs_usage "
                "(id INTEGER PRIMARY KEY, user_id INTEGER, monthly_used BIGINT, monthly_period VARCHAR(7))"
            )
        )
        connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
        connection.execute(
            sa.text(
                "INSERT INTO node_user_bs_usage (id, user_id, monthly_used, monthly_period) VALUES "
                "(1, 1, 12345, :current), (2, 1, 777, '2000-01')"
            ),
            {"current": current_month},
        )

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        user_columns = {column["name"]: column for column in sa.inspect(connection).get_columns("users")}
        assert user_columns["bs_reset_strategy"]["nullable"] is False
        assert user_columns["bs_last_reset_at"]["nullable"] is True
        strategy, anchor = connection.execute(sa.text("SELECT bs_reset_strategy, bs_last_reset_at FROM users")).one()
        assert strategy == "month"
        assert anchor is not None
        rows = connection.execute(
            sa.text("SELECT monthly_used, monthly_period FROM node_user_bs_usage ORDER BY id")
        ).all()
        assert rows[0][0] == 12345
        assert rows[0][1] != current_month and len(rows[0][1]) == 19
        assert rows[1] == (777, "2000-01")

        with Operations.context(context):
            migration.downgrade()
        assert "bs_reset_strategy" not in {column["name"] for column in sa.inspect(connection).get_columns("users")}
        periods = connection.execute(
            sa.text("SELECT monthly_period FROM node_user_bs_usage ORDER BY id")
        ).scalars().all()
        assert periods == [current_month, "2000-01"]
        assert connection.execute(sa.text("SELECT monthly_used FROM node_user_bs_usage WHERE id = 1")).scalar() == 12345
