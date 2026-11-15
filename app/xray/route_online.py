"""Access-route parsing и дедуплицированный online для каскадных Exit."""

from __future__ import annotations

import re
from collections import defaultdict

from app.xray.device_credentials import parse_xray_identity

Identity = tuple[str, int | None]

_ACCESS_EMAIL_RE = re.compile(r"\bemail:\s*(?P<email>[^\s]+)")
_ACCESS_ROUTE_RE = re.compile(
    r"\[(?P<inbound>[^\]\s]+)\s*(?:>>|->)\s*(?P<outbound>[^\]\s]+)\]"
)


def identity_of(param: dict) -> Identity:
    return str(param["uid"]), param.get("device_id")


def parse_access_route(line: str) -> dict | None:
    """Разобрать стандартный text access log Xray.

    Пример суффикса: ``[ENTRY >> CASCADE_OUT_2_VLESS] email: 42.d101.user``.
    IP, destination и прочее содержимое строки наружу не возвращаются.
    """
    if " accepted " not in f" {line} ":
        return None
    email_match = _ACCESS_EMAIL_RE.search(line)
    route_match = _ACCESS_ROUTE_RE.search(line)
    if not email_match or not route_match:
        return None
    uid, device_id = parse_xray_identity(email_match.group("email"))
    if not uid.isdigit():
        return None
    return {
        "uid": uid,
        "device_id": device_id,
        "inbound_tag": route_match.group("inbound"),
        "outbound_tag": route_match.group("outbound"),
    }


def _counts(identities: set[Identity], unattributed: set[Identity]) -> dict[str, int]:
    return {
        "online_users": len({uid for uid, _ in identities}),
        "online_devices": len(identities),
        "legacy_online_users": len({uid for uid, device_id in identities if device_id is None}),
        "unattributed_users": len({uid for uid, _ in unattributed}),
        "unattributed_devices": len(unattributed),
    }


def build_routed_online_counts(
    api_params: dict[int, list[dict]],
    failed_nodes: set[int],
    entry_routes: list[dict],
    observations: dict[tuple[int, Identity], dict],
) -> dict[int, dict | None]:
    """Объединить локальные identities Entry/Direct/Exit с маршрутами Entry→Exit.

    Долгоживущее соединение не требует новой access-строки: Redis observation
    продлевается, пока identity присутствует в текущем stats snapshot.
    """
    local: dict[int, set[Identity]] = {
        node_id: {identity_of(param) for param in params} for node_id, params in api_params.items()
    }
    routed: dict[int, set[Identity]] = defaultdict(set)
    unattributed: dict[int, set[Identity]] = defaultdict(set)
    cascade_inbounds = {
        (route["entry_node_id"], route["entry_inbound_tag"]) for route in entry_routes
    }
    route_map = {
        (route["entry_node_id"], route["entry_inbound_tag"], route["outbound_tag"]): route["exit_node_id"]
        for route in entry_routes
    }
    entry_ids = {route["entry_node_id"] for route in entry_routes}

    for entry_id in entry_ids:
        if entry_id in failed_nodes:
            continue
        for identity in local.get(entry_id, set()):
            observation = observations.get((entry_id, identity))
            if observation:
                exit_id = route_map.get(
                    (entry_id, observation["inbound_tag"], observation["outbound_tag"])
                )
                if exit_id is not None:
                    routed[exit_id].add(identity)
                    continue
                if (entry_id, observation["inbound_tag"]) not in cascade_inbounds:
                    # Смешанная Entry: обычный direct inbound не является потерянным
                    # каскадным маршрутом.
                    continue
            unattributed[entry_id].add(identity)

    result: dict[int, dict | None] = {}
    for node_id in set(local) | set(routed) | entry_ids:
        if node_id in failed_nodes and not routed.get(node_id):
            result[node_id] = None
            continue
        identities = local.get(node_id, set()) | routed.get(node_id, set())
        result[node_id] = _counts(identities, unattributed.get(node_id, set()))
    return result
