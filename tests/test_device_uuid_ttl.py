"""48-часовой per-device UUID: ротация, grace, cleanup и SQLite migration."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base
from app.db.crud import ensure_user_device_vless_uuid
from app.db.models import Proxy, User, UserDevice
from app.models.proxy import ProxyTypes
from app.xray.device_credentials import (
    DEVICE_VLESS_UUID_GRACE,
    DEVICE_VLESS_UUID_TTL,
    active_device_credentials,
    parse_xray_identity,
    previous_device_email,
)

NOW = datetime(2026, 11, 25, 12, 0, 0)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id=42, username="ttl_user", created_at=NOW, device_limit=3))
        session.commit()
        yield session


def _device(db: Session) -> UserDevice:
    device = UserDevice(user_id=42, hwid="ttl-hwid", status="active")
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def test_new_uuid_expires_after_exactly_48_hours_and_does_not_slide(db):
    device = _device(db)
    credential, change = ensure_user_device_vless_uuid(db, device, NOW)

    assert change == "created"
    assert device.vless_uuid == credential
    assert device.vless_uuid_expires_at == NOW + DEVICE_VLESS_UUID_TTL

    unchanged, change = ensure_user_device_vless_uuid(db, device, NOW + timedelta(hours=41))
    assert (unchanged, change) == (credential, "unchanged")
    assert device.vless_uuid_expires_at == NOW + DEVICE_VLESS_UUID_TTL
    assert device.previous_vless_uuid is None


def test_rotation_six_hours_before_expiry_keeps_old_for_at_most_30_minutes(db):
    device = _device(db)
    original, _ = ensure_user_device_vless_uuid(db, device, NOW)
    rotated_at = NOW + timedelta(hours=42)

    current, change = ensure_user_device_vless_uuid(db, device, rotated_at)

    assert change == "rotated"
    assert current != original
    assert device.previous_vless_uuid == original
    assert device.previous_vless_uuid_expires_at == rotated_at + DEVICE_VLESS_UUID_GRACE
    assert device.vless_uuid_expires_at == rotated_at + DEVICE_VLESS_UUID_TTL
    assert active_device_credentials(device, rotated_at) == [(current, False), (original, True)]

    # Повторный refresh не меняет UUID заново и не продлевает grace.
    repeated, change = ensure_user_device_vless_uuid(db, device, rotated_at + timedelta(minutes=1))
    assert (repeated, change) == (current, "unchanged")
    assert device.previous_vless_uuid == original
    assert device.previous_vless_uuid_expires_at == rotated_at + DEVICE_VLESS_UUID_GRACE


def test_expired_uuid_rotation_does_not_revive_it_for_grace(db):
    device = _device(db)
    original, _ = ensure_user_device_vless_uuid(db, device, NOW)
    after_expiry = NOW + timedelta(hours=48, seconds=1)

    current, change = ensure_user_device_vless_uuid(db, device, after_expiry)

    assert change == "rotated"
    assert current != original
    assert device.previous_vless_uuid is None
    assert device.previous_vless_uuid_expires_at is None
    assert active_device_credentials(device, after_expiry) == [(current, False)]


def test_previous_email_preserves_device_identity_for_stats_and_online():
    email = previous_device_email(42, 101, "ttl_user")
    assert email == "42.d101.previous.ttl_user"
    assert parse_xray_identity(email) == ("42", 101)


def test_cleanup_revokes_only_expired_current_and_previous(db, monkeypatch):
    from app.jobs import expire_device_credentials as cleanup_job

    current_expired = _device(db)
    current_expired.vless_uuid = str(uuid4())
    current_expired.vless_uuid_expires_at = NOW - timedelta(seconds=1)
    current_expired.previous_vless_uuid = str(uuid4())
    current_expired.previous_vless_uuid_expires_at = NOW + timedelta(minutes=10)

    previous_expired = UserDevice(
        user_id=42,
        hwid="previous-expired",
        status="active",
        vless_uuid=str(uuid4()),
        vless_uuid_expires_at=NOW + timedelta(hours=10),
        previous_vless_uuid=str(uuid4()),
        previous_vless_uuid_expires_at=NOW - timedelta(seconds=1),
    )
    db.add(previous_expired)
    db.commit()
    db.refresh(previous_expired)
    valid_current = previous_expired.vless_uuid

    remove = Mock()
    monkeypatch.setattr(cleanup_job, "GetDB", lambda: nullcontext(db))
    monkeypatch.setattr(
        cleanup_job.xray,
        "operations",
        types.SimpleNamespace(remove_device_credential=remove),
        raising=False,
    )

    cleanup_job.expire_device_credentials(NOW)
    db.refresh(current_expired)
    db.refresh(previous_expired)

    assert current_expired.vless_uuid is None
    assert current_expired.previous_vless_uuid is not None
    assert previous_expired.vless_uuid == valid_current
    assert previous_expired.previous_vless_uuid is None
    assert [(call.kwargs["previous"], call.args[1].id) for call in remove.call_args_list] == [
        (False, current_expired.id),
        (True, previous_expired.id),
    ]


def test_startup_config_restores_current_and_grace_but_not_expired(db, monkeypatch):
    import app.xray.config as config_module
    from app.xray.config import XRayConfig

    now = datetime.utcnow()
    current = str(uuid4())
    previous = str(uuid4())
    expired = str(uuid4())
    device = _device(db)
    device.vless_uuid = current
    device.vless_uuid_expires_at = now + timedelta(hours=1)
    device.previous_vless_uuid = previous
    device.previous_vless_uuid_expires_at = now + timedelta(minutes=10)
    db.add(
        UserDevice(
            user_id=42,
            hwid="expired",
            status="active",
            vless_uuid=expired,
            vless_uuid_expires_at=now - timedelta(seconds=1),
        )
    )
    db.add(Proxy(user_id=42, type=ProxyTypes.VLESS, settings={"id": str(uuid4()), "flow": ""}))
    db.commit()
    monkeypatch.setattr(config_module, "GetDB", lambda: nullcontext(db))
    config = XRayConfig(
        {
            "inbounds": [
                {
                    "tag": "VLESS_TCP_REALITY",
                    "protocol": "vless",
                    "listen": "127.0.0.1",
                    "port": 443,
                    "settings": {"clients": [], "decryption": "none"},
                    "streamSettings": {"network": "tcp", "security": "none"},
                }
            ],
            "outbounds": [{"protocol": "freedom", "tag": "direct"}],
        }
    )

    clients = config.include_db_users().get_inbound("VLESS_TCP_REALITY")["settings"]["clients"]
    by_email = {client["email"]: client for client in clients}
    current_email = next(email for email in by_email if email.endswith(".ttl_user") and ".previous." not in email and email.startswith("42.d"))
    previous_email = previous_device_email(42, device.id, "ttl_user")

    assert by_email[current_email]["id"] == current
    assert by_email[previous_email]["id"] == previous
    assert parse_xray_identity(current_email) == parse_xray_identity(previous_email) == ("42", device.id)
    assert expired not in {client["id"] for client in clients}


def test_device_uuid_ttl_migration_preserves_current_uuid():
    path = Path(__file__).parent.parent / "app/db/migrations/versions/c0d1e2f3a4b5_device_vless_uuid_ttl.py"
    spec = importlib.util.spec_from_file_location("device_vless_uuid_ttl_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "b9c0d1e2f3a4"

    engine = sa.create_engine("sqlite://")
    credential = str(uuid4())
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE user_devices (id INTEGER PRIMARY KEY, vless_uuid VARCHAR(36))"))
        connection.execute(sa.text("INSERT INTO user_devices (id, vless_uuid) VALUES (1, :uuid)"), {"uuid": credential})
        connection.execute(sa.text("INSERT INTO user_devices (id, vless_uuid) VALUES (2, NULL)"))
        context = MigrationContext.configure(connection)

        with Operations.context(context):
            migration.upgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("user_devices")}
        assert {
            "vless_uuid_expires_at",
            "previous_vless_uuid",
            "previous_vless_uuid_expires_at",
        } <= columns
        rows = connection.execute(
            sa.text("SELECT vless_uuid, vless_uuid_expires_at FROM user_devices ORDER BY id")
        ).all()
        assert rows[0][0] == credential
        assert rows[0][1] is not None
        assert rows[1] == (None, None)

        with Operations.context(context):
            migration.downgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("user_devices")}
        assert "vless_uuid_expires_at" not in columns
        assert connection.execute(sa.text("SELECT vless_uuid FROM user_devices WHERE id = 1")).scalar() == credential
