"""Идентификаторы per-device VLESS, TTL и подсчёт realtime online.

Email остаётся совместимым с учётом Marzban: префикс ``<uid>.`` по-прежнему
ведёт к владельцу подписки. Маркер ``d<device_id>`` отличает устройство от
legacy identity ``<uid>.<username>``. Временный previous-email содержит тот же
маркер, поэтому grace-credential не становится отдельным устройством в online.
"""

from __future__ import annotations

from datetime import datetime, timedelta

DEVICE_VLESS_UUID_TTL = timedelta(hours=48)
DEVICE_VLESS_UUID_ROTATE_BEFORE = timedelta(hours=6)
DEVICE_VLESS_UUID_GRACE = timedelta(minutes=30)


def device_email(user_id: int, device_id: int, username: str) -> str:
    return f"{user_id}.d{device_id}.{username}"


def previous_device_email(user_id: int, device_id: int, username: str) -> str:
    return f"{user_id}.d{device_id}.previous.{username}"


def active_device_credentials(device, now: datetime) -> list[tuple[str, bool]]:
    """Вернуть (uuid, is_previous), отсекая истёкшие и revoked credentials.

    NULL expiry у текущего UUID обслуживает старые строки, созданные тестами или
    внешними модулями до миграции. Штатная миграция проставляет им 48 часов.
    """
    if device.status != "active":
        return []
    credentials = []
    if device.vless_uuid and (
        device.vless_uuid_expires_at is None or device.vless_uuid_expires_at > now
    ):
        credentials.append((device.vless_uuid, False))
    if (
        device.previous_vless_uuid
        and device.previous_vless_uuid_expires_at is not None
        and device.previous_vless_uuid_expires_at > now
    ):
        credentials.append((device.previous_vless_uuid, True))
    return credentials


def parse_xray_identity(email: str) -> tuple[str, int | None]:
    """Вернуть (uid, device_id); device_id=None для legacy identity."""
    uid, separator, tail = email.partition(".")
    if not separator:
        return uid, None
    marker, separator, _ = tail.partition(".")
    if separator and marker.startswith("d") and marker[1:].isdigit():
        return uid, int(marker[1:])
    return uid, None


def online_counts(params: list[dict]) -> dict[str, int]:
    """Пользователи — уникальные uid; устройства — уникальные device identity.

    Активная legacy identity считается одним устройством до её миграции. Это
    сохраняет прежний нижний ориентир и не приписывает ей выдуманный HWID.
    """
    users: set[str] = set()
    devices: set[tuple[str, int | None]] = set()
    legacy_users: set[str] = set()
    for param in params:
        uid = str(param["uid"])
        device_id = param.get("device_id")
        users.add(uid)
        devices.add((uid, device_id))
        if device_id is None:
            legacy_users.add(uid)
    return {
        "online_users": len(users),
        "online_devices": len(devices),
        "legacy_online_users": len(legacy_users),
    }
