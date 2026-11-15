import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from app import logger, scheduler
from app.db import GetDB, crud
from app.models.node import NodeStatus
from app.services.node_realtime import set_node_system
from config import JOB_NODE_REALTIME_INTERVAL, NODE_EXPORTER_PORT, NODE_EXPORTER_TIMEOUT, REALTIME_METRICS_CONCURRENCY

_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([0-9eE+.-]+)")
_LABEL_RE = re.compile(r'(\w+)="((?:\\.|[^"])*)"')
_IGNORED_INTERFACE_PREFIXES = ("lo", "docker", "veth", "br-", "virbr", "tun", "wg", "tailscale", "zt")
_executor = ThreadPoolExecutor(max_workers=REALTIME_METRICS_CONCURRENCY, thread_name_prefix="node-realtime")
_previous: dict[int, dict] = {}


def _labels(raw: str | None) -> dict[str, str]:
    return dict(_LABEL_RE.findall(raw or ""))


def _exporter_url(address: str) -> str:
    host = f"[{address}]" if ":" in address and not address.startswith("[") else address
    return f"http://{host}:{NODE_EXPORTER_PORT}/metrics"


def _ignored_interface(name: str) -> bool:
    return name.startswith(_IGNORED_INTERFACE_PREFIXES)


def collect_node(node_id: int, address: str) -> dict:
    response = requests.get(_exporter_url(address), timeout=NODE_EXPORTER_TIMEOUT)
    response.raise_for_status()

    cpu: dict[tuple[str, str], float] = {}
    network: dict[str, dict[str, float]] = {}
    memory_total = None
    memory_available = None

    for line in response.text.splitlines():
        match = _METRIC_RE.match(line)
        if not match:
            continue
        name, raw_labels, raw_value = match.groups()
        labels = _labels(raw_labels)
        value = float(raw_value)

        if name == "node_cpu_seconds_total":
            cpu[(labels.get("cpu", ""), labels.get("mode", ""))] = value
        elif name == "node_memory_MemTotal_bytes":
            memory_total = value
        elif name == "node_memory_MemAvailable_bytes":
            memory_available = value
        elif name in ("node_network_receive_bytes_total", "node_network_transmit_bytes_total"):
            interface = labels.get("device", "")
            if not interface or _ignored_interface(interface):
                continue
            direction = "rx" if name == "node_network_receive_bytes_total" else "tx"
            network.setdefault(interface, {})[direction] = value

    now = time.monotonic()
    sample = {
        "timestamp": now,
        "cpu_total": sum(cpu.values()),
        "cpu_idle": sum(value for (cpu_id, mode), value in cpu.items() if mode == "idle"),
        "rx": sum(values.get("rx", 0) for values in network.values()),
        "tx": sum(values.get("tx", 0) for values in network.values()),
    }
    previous = _previous.get(node_id)
    _previous[node_id] = sample

    cpu_percent = None
    download_rate = None
    upload_rate = None
    if previous:
        elapsed = sample["timestamp"] - previous["timestamp"]
        cpu_total_delta = sample["cpu_total"] - previous["cpu_total"]
        cpu_idle_delta = sample["cpu_idle"] - previous["cpu_idle"]
        if cpu_total_delta > 0 and cpu_idle_delta >= 0:
            cpu_percent = max(0.0, min(100.0, 100 * (1 - cpu_idle_delta / cpu_total_delta)))
        if elapsed > 0:
            rx_delta = sample["rx"] - previous["rx"]
            tx_delta = sample["tx"] - previous["tx"]
            if rx_delta >= 0:
                download_rate = rx_delta / elapsed
            if tx_delta >= 0:
                upload_rate = tx_delta / elapsed

    memory_percent = None
    if memory_total and memory_available is not None:
        memory_percent = max(0.0, min(100.0, 100 * (1 - memory_available / memory_total)))

    return {
        "metrics_available": True,
        "cpu_percent": round(cpu_percent, 1) if cpu_percent is not None else None,
        "memory_percent": round(memory_percent, 1) if memory_percent is not None else None,
        "download_bytes_per_second": round(download_rate) if download_rate is not None else None,
        "upload_bytes_per_second": round(upload_rate) if upload_rate is not None else None,
    }


def collect_node_safe(node_id: int, address: str) -> dict:
    try:
        return collect_node(node_id, address)
    except Exception as exc:
        logger.warning("[realtime] node %s exporter failed: %s", node_id, exc)
        return {
            "metrics_available": False,
            "cpu_percent": None,
            "memory_percent": None,
            "download_bytes_per_second": None,
            "upload_bytes_per_second": None,
        }


def collect_nodes_realtime():
    with GetDB() as db:
        nodes = crud.get_nodes(db)
        targets = [(node.id, node.address) for node in nodes if node.status == NodeStatus.connected]
        inactive = [node.id for node in nodes if node.status != NodeStatus.connected]

    for node_id in inactive:
        _previous.pop(node_id, None)
        set_node_system(node_id, {"metrics_available": False})

    futures = {node_id: _executor.submit(collect_node_safe, node_id, address) for node_id, address in targets}
    for node_id, future in futures.items():
        set_node_system(node_id, future.result())


scheduler.add_job(
    collect_nodes_realtime,
    "interval",
    seconds=JOB_NODE_REALTIME_INTERVAL,
    coalesce=True,
    max_instances=1,
)
