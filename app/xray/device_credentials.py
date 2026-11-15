"""Идентификаторы per-device VLESS и подсчёт realtime online.

Email остаётся совместимым с учётом Marzban: префикс ``<uid>.`` по-прежнему
ведёт к владельцу подписки. Маркер ``d<device_id>`` отличает устройство от
legacy identity ``<uid>.<username>``.
"""

from __future__ import annotations


def device_email(user_id: int, device_id: int, username: str) -> str:
    return f"{user_id}.d{device_id}.{username}"


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
