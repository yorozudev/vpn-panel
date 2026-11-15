"""Постоянные access-log streams Entry и каталог маршрутов Entry→Exit."""

from collections import deque

from app import logger, xray
from app.db import GetDB
from app.db.models import CascadeRoute
from app.services.node_realtime import record_route_observations
from app.xray.cascade_config import cascade_outbound_tag
from config import REALTIME_ROUTE_LOG_BUFFER

# Контексты специально живут между тиками: закрытие get_logs() после каждого
# опроса разрывало бы WebSocket и теряло access-строки между подключениями.
_streams: dict[int, tuple[object, deque]] = {}


def _route_catalog() -> list[dict]:
    with GetDB() as db:
        rows = db.query(CascadeRoute).all()
        return [
            {
                "entry_node_id": row.entry_node_id,
                "exit_node_id": row.exit_node_id,
                "entry_inbound_tag": row.entry_inbound_tag,
                "outbound_tag": cascade_outbound_tag(row.exit_node_id, row.cascade_inbound_tag),
            }
            for row in rows
        ]


def _drain_entry(entry_node_id: int) -> None:
    node = xray.nodes.get(entry_node_id)
    if node is None or not node.connected or not node.started:
        return
    stream = _streams.get(entry_node_id)
    if stream is None:
        context = node.get_logs(maxlen=REALTIME_ROUTE_LOG_BUFFER)
        buffer = context.__enter__()
        _streams[entry_node_id] = (context, buffer)
        stream = _streams[entry_node_id]
    buffer = stream[1]
    lines = []
    while buffer:
        lines.extend(str(buffer.popleft()).splitlines())
    record_route_observations(entry_node_id, lines)


def collect_entry_routes() -> list[dict]:
    """Обновить Redis observations и вернуть актуальный каталог маршрутов."""
    routes = _route_catalog()
    for entry_node_id in {route["entry_node_id"] for route in routes}:
        try:
            _drain_entry(entry_node_id)
        except Exception as exc:
            logger.warning("[realtime] Entry %s access stream failed: %s", entry_node_id, exc)
    return routes
