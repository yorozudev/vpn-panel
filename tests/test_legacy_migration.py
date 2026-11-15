from datetime import datetime, timedelta
from types import SimpleNamespace

from app.db.crud import UNKNOWN_DEVICE_HWID
from app.xray.legacy_migration import legacy_migration_status

NOW = datetime(2026, 11, 16, 12, 0, 0)
OLD = NOW - timedelta(days=8)
RECENT = NOW - timedelta(days=2)


def user(**overrides):
    values = {
        "legacy_vless_enabled": True,
        "legacy_vless_last_activity_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def device(device_id=1, **overrides):
    values = {
        "id": device_id,
        "hwid": f"hwid-{device_id}",
        "status": "active",
        "vless_uuid": f"00000000-0000-0000-0000-{device_id:012d}",
        "vless_config_delivered_at": OLD,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def status(dbuser, devices):
    return legacy_migration_status(dbuser, devices, now=NOW, grace_seconds=7 * 24 * 3600)


def test_ready_only_after_all_known_devices_received_configs_and_grace():
    assert status(user(), [device(1), device(2)]) == (True, "ready")
    assert status(user(), [device(1, vless_config_delivered_at=RECENT), device(2)]) == (
        False,
        "config_grace_period",
    )


def test_unknown_or_incomplete_device_blocks_automatic_disable():
    assert status(user(), [device(1), device(2, hwid=UNKNOWN_DEVICE_HWID)]) == (
        False,
        "unknown_device",
    )
    assert status(user(), [device(1, vless_uuid=None)]) == (False, "credential_pending")
    assert status(user(), [device(1, vless_config_delivered_at=None)]) == (False, "config_pending")
    assert status(user(), []) == (False, "no_devices")


def test_revoked_unknown_does_not_block_ready_known_devices():
    unknown = device(2, hwid=UNKNOWN_DEVICE_HWID, status="revoked", vless_uuid=None)
    assert status(user(), [device(1), unknown]) == (True, "ready")


def test_recent_legacy_activity_is_independent_safety_condition():
    assert status(user(legacy_vless_last_activity_at=RECENT), [device()]) == (False, "legacy_active")
    assert status(user(legacy_vless_last_activity_at=OLD), [device()]) == (True, "ready")


def test_disabled_user_is_not_disabled_twice():
    assert status(user(legacy_vless_enabled=False), [device()]) == (False, "already_disabled")
