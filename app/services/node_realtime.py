import json
import logging
from datetime import UTC, datetime

from redis import Redis
from redis.exceptions import RedisError

from config import REALTIME_ONLINE_TTL, REALTIME_REDIS_URL, REALTIME_ROUTE_TTL, REALTIME_SYSTEM_TTL

logger = logging.getLogger("uvicorn.error")

_redis = Redis.from_url(
    REALTIME_REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def _online_key(node_id: int) -> str:
    return f"node_users_online:{node_id}"


def _system_key(node_id: int) -> str:
    return f"node_system_stats:{node_id}"


def _route_key(entry_node_id: int, identity: tuple[str, int | None]) -> str:
    uid, device_id = identity
    return f"entry_route:{entry_node_id}:{uid}:{'legacy' if device_id is None else device_id}"


def record_route_observations(entry_node_id: int, lines: list[str]) -> None:
    """Сохранить только identity и теги, без IP/destination из access log."""
    from app.xray.route_online import parse_access_route

    observations = [parse_access_route(line) for line in lines]
    observations = [item for item in observations if item is not None]
    if not observations:
        return
    try:
        with _redis.pipeline() as pipe:
            for item in observations:
                identity = (item["uid"], item["device_id"])
                pipe.set(
                    _route_key(entry_node_id, identity),
                    json.dumps({
                        "inbound_tag": item["inbound_tag"],
                        "outbound_tag": item["outbound_tag"],
                    }),
                    ex=REALTIME_ROUTE_TTL,
                )
            pipe.execute()
    except RedisError as exc:
        logger.warning("[realtime] failed to write Entry routes: %s", exc)


def get_route_observations(entry_node_id: int, identities: set[tuple[str, int | None]]) -> dict:
    """Прочитать и продлить маршруты активных identities (long-lived connections)."""
    if not identities:
        return {}
    keys = {identity: _route_key(entry_node_id, identity) for identity in identities}
    try:
        with _redis.pipeline() as pipe:
            for key in keys.values():
                pipe.get(key)
                pipe.expire(key, REALTIME_ROUTE_TTL)
            rows = pipe.execute()
    except RedisError as exc:
        logger.warning("[realtime] failed to read Entry routes: %s", exc)
        return {}
    result = {}
    for index, (identity, key) in enumerate(keys.items()):
        raw = rows[index * 2]
        if raw:
            result[(entry_node_id, identity)] = json.loads(raw)
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat()


def set_nodes_online(values: dict[int, dict | None]) -> None:
    """None означает ошибку сбора, нулевые счётчики — успешный пустой ответ."""
    if not values:
        return
    try:
        with _redis.pipeline() as pipe:
            for node_id, counts in values.items():
                payload = counts if counts is not None else {
                    "online_users": None,
                    "online_devices": None,
                    "legacy_online_users": None,
                    "unattributed_users": None,
                    "unattributed_devices": None,
                }
                pipe.set(
                    _online_key(node_id),
                    json.dumps({**payload, "measured_at": _now()}),
                    ex=REALTIME_ONLINE_TTL,
                )
            pipe.execute()
    except RedisError as exc:
        logger.warning("[realtime] failed to write online stats: %s", exc)


def set_node_system(node_id: int, payload: dict) -> None:
    try:
        data = {**payload, "measured_at": _now()}
        _redis.set(_system_key(node_id), json.dumps(data), ex=REALTIME_SYSTEM_TTL)
    except RedisError as exc:
        logger.warning("[realtime] failed to write system stats for node %s: %s", node_id, exc)


def get_nodes_realtime(node_ids: list[int]) -> list[dict]:
    if not node_ids:
        return []

    empty = {
        "online_users": None,
        "online_devices": None,
        "legacy_online_users": None,
        "unattributed_users": None,
        "unattributed_devices": None,
        "cpu_percent": None,
        "memory_percent": None,
        "download_bytes_per_second": None,
        "upload_bytes_per_second": None,
        "measured_at": None,
        "metrics_available": False,
    }
    result = {node_id: {"node_id": node_id, **empty} for node_id in node_ids}

    try:
        with _redis.pipeline() as pipe:
            for node_id in node_ids:
                pipe.get(_online_key(node_id))
                pipe.get(_system_key(node_id))
            rows = pipe.execute()
    except RedisError as exc:
        logger.warning("[realtime] failed to read stats: %s", exc)
        return list(result.values())

    for index, node_id in enumerate(node_ids):
        online_raw, system_raw = rows[index * 2 : index * 2 + 2]
        if online_raw:
            online = json.loads(online_raw)
            for field in (
                "online_users",
                "online_devices",
                "legacy_online_users",
                "unattributed_users",
                "unattributed_devices",
                "measured_at",
            ):
                result[node_id][field] = online.get(field)
        if system_raw:
            system = json.loads(system_raw)
            for field in (
                "cpu_percent",
                "memory_percent",
                "download_bytes_per_second",
                "upload_bytes_per_second",
                "measured_at",
                "metrics_available",
            ):
                result[node_id][field] = system.get(field)

    return list(result.values())
