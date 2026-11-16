"""Формирование списка активных пользователей ноды из Redis-снимка и БД."""


def build_online_user_list(snapshot: dict, users, devices) -> list[dict]:
    """Сгруппировать активные identities по подписке, не раскрывая HWID/IP."""
    usernames = {int(user.id): user.username for user in users}
    devices_by_identity = {
        (int(device.user_id), int(device.id)): device
        for device in devices
    }
    grouped: dict[int, list[dict]] = {}

    for identity in snapshot.get("identities", []):
        uid = int(identity["uid"])
        device_id = identity.get("device_id")
        device = devices_by_identity.get((uid, device_id)) if device_id is not None else None
        grouped.setdefault(uid, []).append({
            "device_id": device_id,
            "is_legacy": device_id is None,
            "device_model": getattr(device, "device_model", None),
            "device_os": getattr(device, "device_os", None),
            "ver_os": getattr(device, "ver_os", None),
            # Это время последнего успешного наблюдения трафика, а не момент
            # установления TCP-соединения: Xray Stats API его не предоставляет.
            "last_activity_at": snapshot.get("measured_at"),
        })

    result = [
        {
            "user_id": uid,
            "username": usernames.get(uid),
            "devices": sorted(
                user_devices,
                key=lambda item: (item["device_id"] is not None, item["device_id"] or 0),
            ),
        }
        for uid, user_devices in grouped.items()
    ]
    return sorted(
        result,
        key=lambda item: (
            item["username"] is None,
            (item["username"] or "").casefold(),
            item["user_id"],
        ),
    )
