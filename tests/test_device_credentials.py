"""Per-device VLESS: совместимость identity, лимит и realtime online."""

from __future__ import annotations

import sys
import types
from contextlib import nullcontext
from datetime import datetime
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base
from app.db.crud import (
    UNKNOWN_DEVICE_HWID,
    count_user_devices,
    get_user_device_by_hwid,
    revoke_user_device,
)
from app.db.models import Proxy, User, UserDevice
from app.models.proxy import ProxyTypes, VLESSSettings
from app.subscription.user_info import resolve_device_limit_subscription_state
from app.xray.device_credentials import (
    device_email,
    online_counts,
    parse_xray_identity,
)


class FakeSubUser:
    def __init__(self, legacy_id):
        self.proxies = {"vless": VLESSSettings(id=legacy_id)}
        self.inbounds = {"vless": ["VLESS_TCP_REALITY"]}

    def model_copy(self, update=None):
        other = FakeSubUser(uuid4())
        if update:
            other.proxies = update.get("proxies", other.proxies)
            other.inbounds = update.get("inbounds", other.inbounds)
        return other


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id=42, username="device_user", created_at=datetime.utcnow(), device_limit=3))
        session.commit()
        yield session


@pytest.fixture
def add_device(monkeypatch):
    operation = Mock()
    xray_module = sys.modules["app.xray"]
    monkeypatch.setattr(xray_module, "operations", types.SimpleNamespace(add_device=operation), raising=False)
    return operation


def resolve(db, add_device, hwid, *, hard=True):
    dbuser = db.query(User).filter(User.id == 42).one()
    legacy_id = uuid4()
    user = FakeSubUser(legacy_id)
    result_user, limited, limited_hard, unsupported = resolve_device_limit_subscription_state(
        user,
        db,
        dbuser,
        False,
        False,
        {"sub_device_limit_hard_mode": hard},
        user_agent="Happ/1.0",
        x_hwid=hwid,
        x_device_os="Android",
        x_ver_os="15",
        x_device_model="Pixel",
    )
    return result_user, legacy_id, limited, limited_hard, unsupported


def test_identity_is_unambiguous_and_legacy_compatible():
    assert device_email(42, 101, "123_numeric_name") == "42.d101.123_numeric_name"
    assert parse_xray_identity("42.d101.123_numeric_name") == ("42", 101)
    assert parse_xray_identity("42.123") == ("42", None)
    assert parse_xray_identity("42.username") == ("42", None)


def test_xray_stats_keep_device_identity_and_aggregate_directions():
    from app.jobs.record_usages import get_users_stats

    class API:
        def get_users_stats(self, reset, timeout):
            assert reset is True
            return [
                types.SimpleNamespace(name="42.d101.device_user", value=10),
                types.SimpleNamespace(name="42.d101.device_user", value=20),
                types.SimpleNamespace(name="42.d102.device_user", value=30),
                types.SimpleNamespace(name="43.other_user", value=40),
            ]

    assert get_users_stats(API()) == [
        {"uid": "42", "device_id": 101, "value": 30},
        {"uid": "42", "device_id": 102, "value": 30},
        {"uid": "43", "device_id": None, "value": 40},
    ]


def test_legacy_activity_ignores_per_device_only_traffic(db, monkeypatch):
    from app.jobs import record_usages

    monkeypatch.setattr(record_usages, "GetDB", lambda: nullcontext(db))
    record_usages.record_legacy_activity({1: [{"uid": "42", "device_id": 101, "value": 100}]})
    dbuser = db.query(User).filter(User.id == 42).one()
    assert dbuser.legacy_vless_last_activity_at is None

    record_usages.record_legacy_activity(
        {
            1: [
                {"uid": "42", "device_id": 101, "value": 100},
                {"uid": "42", "device_id": None, "value": 50},
            ]
        }
    )
    db.refresh(dbuser)
    assert dbuser.legacy_vless_last_activity_at is not None


def test_online_counts_users_devices_and_legacy_separately():
    params = [
        {"uid": "42", "device_id": 101, "value": 10},
        {"uid": "42", "device_id": 102, "value": 20},
        {"uid": "42", "device_id": 103, "value": 30},
        {"uid": "43", "device_id": None, "value": 40},
    ]
    assert online_counts(params) == {
        "online_users": 2,
        "online_devices": 4,
        "legacy_online_users": 1,
    }


def test_three_devices_get_stable_distinct_uuids_and_pass_limit(db, add_device):
    results = [resolve(db, add_device, f"hwid-{index}") for index in range(3)]
    device_ids = [result[0].proxies["vless"].id for result in results]
    assert len(set(device_ids)) == 3
    assert all(device_id != result[1] for device_id, result in zip(device_ids, results))
    assert add_device.call_count == 3
    assert count_user_devices(db, db.query(User).filter(User.id == 42).one()) == 3

    # Повторное обновление той же подписки не меняет UUID, не добавляет клиента
    # и не сдвигает первую выдачу, от которой считается migration grace period.
    dbuser = db.query(User).filter(User.id == 42).one()
    first_delivery = get_user_device_by_hwid(db, dbuser, "hwid-0").vless_config_delivered_at
    assert first_delivery is not None
    again = resolve(db, add_device, "hwid-0")
    assert again[0].proxies["vless"].id == device_ids[0]
    assert get_user_device_by_hwid(db, dbuser, "hwid-0").vless_config_delivered_at == first_delivery
    assert add_device.call_count == 3
    assert all(result[2:] == (False, False, False) for result in [*results, again])


def test_new_device_over_hard_limit_gets_no_credential(db, add_device):
    for index in range(3):
        resolve(db, add_device, f"hwid-{index}")
    user, _, limited, limited_hard, unsupported = resolve(db, add_device, "hwid-new")
    dbuser = db.query(User).filter(User.id == 42).one()
    assert (limited, limited_hard, unsupported) == (True, True, False)
    assert user.proxies == {}
    assert get_user_device_by_hwid(db, dbuser, "hwid-new") is None
    assert add_device.call_count == 3


def test_revoke_frees_slot_and_preserves_other_credentials(db, add_device):
    results = [resolve(db, add_device, f"hwid-{index}") for index in range(3)]
    original_ids = [result[0].proxies["vless"].id for result in results]
    dbuser = db.query(User).filter(User.id == 42).one()
    revoked = get_user_device_by_hwid(db, dbuser, "hwid-0")
    revoke_user_device(db, revoked)
    assert count_user_devices(db, dbuser) == 2

    new_user, _, limited, limited_hard, _ = resolve(db, add_device, "hwid-new")
    assert (limited, limited_hard) == (False, False)
    assert new_user.proxies["vless"].id not in original_ids
    assert get_user_device_by_hwid(db, dbuser, "hwid-1").vless_uuid == str(original_ids[1])
    assert get_user_device_by_hwid(db, dbuser, "hwid-2").vless_uuid == str(original_ids[2])


def test_returning_revoked_hwid_reuses_its_credential(db, add_device):
    first = resolve(db, add_device, "hwid-0")
    original = first[0].proxies["vless"].id
    dbuser = db.query(User).filter(User.id == 42).one()
    revoke_user_device(db, get_user_device_by_hwid(db, dbuser, "hwid-0"))
    returned = resolve(db, add_device, "hwid-0")
    assert returned[0].proxies["vless"].id == original
    assert UUID(get_user_device_by_hwid(db, dbuser, "hwid-0").vless_uuid) == original


def test_unknown_device_keeps_legacy_behavior(db, add_device):
    user, legacy_id, limited, limited_hard, unsupported = resolve(db, add_device, None)
    dbuser = db.query(User).filter(User.id == 42).one()
    unknown = get_user_device_by_hwid(db, dbuser, UNKNOWN_DEVICE_HWID)
    assert (limited, limited_hard, unsupported) == (False, False, False)
    assert user.proxies["vless"].id == legacy_id
    assert unknown.vless_uuid is None
    add_device.assert_not_called()


def test_no_hwid_gets_empty_subscription_after_legacy_disable(db, add_device):
    dbuser = db.query(User).filter(User.id == 42).one()
    dbuser.legacy_vless_enabled = False
    db.commit()
    user, _, limited, limited_hard, unsupported = resolve(db, add_device, None)
    assert (limited, limited_hard, unsupported) == (False, False, True)
    assert user.proxies == {}
    add_device.assert_not_called()


def test_startup_config_restores_active_devices_and_skips_revoked(db, monkeypatch):
    import app.xray.config as config_module
    from app.xray.config import XRayConfig

    legacy_id = uuid4()
    active_id = uuid4()
    revoked_id = uuid4()
    db.add(Proxy(user_id=42, type=ProxyTypes.VLESS, settings={"id": str(legacy_id), "flow": ""}))
    db.add_all(
        [
            UserDevice(user_id=42, hwid="active", status="active", vless_uuid=str(active_id)),
            UserDevice(user_id=42, hwid="revoked", status="revoked", vless_uuid=str(revoked_id)),
        ]
    )
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
    assert by_email["42.device_user"]["id"] == str(legacy_id)
    active_devices = [client for email, client in by_email.items() if parse_xray_identity(email)[1] is not None]
    active_device = get_user_device_by_hwid(db, db.query(User).filter(User.id == 42).one(), "active")
    assert len(active_devices) == 1
    assert active_devices[0]["email"] == device_email(42, active_device.id, "device_user")
    assert active_devices[0]["id"] == str(active_id)
    assert str(revoked_id) not in {client["id"] for client in clients}

    # Per-user disable убирает только legacy; device identity переживает restart.
    dbuser = db.query(User).filter(User.id == 42).one()
    dbuser.legacy_vless_enabled = False
    db.commit()
    migrated_clients = config.include_db_users().get_inbound("VLESS_TCP_REALITY")["settings"]["clients"]
    assert "42.device_user" not in {client["email"] for client in migrated_clients}
    assert active_device.id in {
        parse_xray_identity(client["email"])[1] for client in migrated_clients
    }


def test_migration_job_disables_ready_user_and_removes_only_legacy(db, monkeypatch):
    from datetime import timedelta

    from app.jobs import migrate_legacy_credentials as migration_job

    db.add(
        UserDevice(
            user_id=42,
            hwid="ready",
            status="active",
            vless_uuid=str(uuid4()),
            vless_config_delivered_at=datetime.utcnow() - timedelta(days=8),
        )
    )
    db.commit()
    remove_legacy = Mock()
    monkeypatch.setattr(
        migration_job.xray,
        "operations",
        types.SimpleNamespace(remove_legacy_vless=remove_legacy),
        raising=False,
    )
    monkeypatch.setattr(migration_job, "GetDB", lambda: nullcontext(db))

    migration_job.migrate_legacy_credentials()

    dbuser = db.query(User).filter(User.id == 42).one()
    assert dbuser.legacy_vless_enabled is False
    assert dbuser.legacy_vless_disabled_at is not None
    remove_legacy.assert_called_once()


def test_live_xray_add_and_revoke_use_device_identity(db, monkeypatch):
    from app.xray import operations

    credential = uuid4()
    db.add(Proxy(user_id=42, type=ProxyTypes.VLESS, settings={"id": str(uuid4()), "flow": ""}))
    device = UserDevice(user_id=42, hwid="live", status="active", vless_uuid=str(credential))
    db.add(device)
    db.commit()
    db.refresh(device)
    dbuser = db.query(User).filter(User.id == 42).one()
    config = types.SimpleNamespace(
        inbounds_by_tag={"VLESS_TCP_REALITY": {"network": "tcp", "tls": "reality"}},
        inbounds_by_protocol={"vless": [{"tag": "VLESS_TCP_REALITY"}]},
    )
    monkeypatch.setattr(operations.xray, "config", config, raising=False)
    monkeypatch.setattr(operations.xray, "api", object(), raising=False)
    monkeypatch.setattr(operations.xray, "nodes", {}, raising=False)
    monkeypatch.setattr(operations, "_get_ready_nodes", lambda: [])
    add = Mock()
    remove = Mock()
    monkeypatch.setattr(operations, "_add_user_to_inbound", add)
    monkeypatch.setattr(operations, "_remove_user_from_inbound", remove)

    operations.add_device(dbuser, device)
    account = add.call_args.args[2]
    assert account.email == device_email(42, device.id, "device_user")
    assert str(account.id) == str(credential)

    operations.remove_device(dbuser, device)
    assert remove.call_args.args[2] == device_email(42, device.id, "device_user")
