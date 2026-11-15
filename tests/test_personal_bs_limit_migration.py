import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = Path(__file__).parent.parent / "app/db/migrations/versions/a8b9c0d1e2f3_personal_bs_monthly_limit.py"
    spec = importlib.util.spec_from_file_location("personal_bs_limit_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_personal_bs_limit_migration_upgrade_and_downgrade():
    migration = _load_migration()
    assert migration.down_revision == "f7b8c9d0e1a2"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("users")}
        assert columns["bs_monthly_limit"]["nullable"] is True
        assert isinstance(columns["bs_monthly_limit"]["type"], sa.BigInteger)
        with Operations.context(context):
            migration.downgrade()
        assert "bs_monthly_limit" not in {column["name"] for column in sa.inspect(connection).get_columns("users")}
