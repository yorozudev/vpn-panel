"""Проверка готовности подписки к отключению общего VLESS UUID."""

from __future__ import annotations

from datetime import datetime, timedelta


def legacy_migration_status(dbuser, devices, *, now: datetime, grace_seconds: int) -> tuple[bool, str]:
    """Вернуть (готовность, причина) без обращений к Xray и без изменений БД.

    Отсутствие трафика само по себе не означает миграцию. Обязательны отдельный
    UUID и сформированный per-device конфиг у каждого активного известного HWID.
    """
    if not getattr(dbuser, "legacy_vless_enabled", True):
        return False, "already_disabled"

    active = [device for device in devices if getattr(device, "status", "active") != "revoked"]
    from app.db.crud import UNKNOWN_DEVICE_HWID

    if any(device.hwid == UNKNOWN_DEVICE_HWID for device in active):
        return False, "unknown_device"

    known = [device for device in active if device.hwid != UNKNOWN_DEVICE_HWID]
    if not known:
        return False, "no_devices"
    if any(not device.vless_uuid for device in known):
        return False, "credential_pending"
    if any(device.vless_config_delivered_at is None for device in known):
        return False, "config_pending"

    threshold = now - timedelta(seconds=max(0, grace_seconds))
    newest_config = max(device.vless_config_delivered_at for device in known)
    if newest_config > threshold:
        return False, "config_grace_period"

    last_legacy = getattr(dbuser, "legacy_vless_last_activity_at", None)
    if last_legacy is not None and last_legacy > threshold:
        return False, "legacy_active"
    return True, "ready"
