import json
from types import SimpleNamespace

from app.services import node_realtime
from app.services.node_online_users import build_online_user_list


def test_online_user_list_groups_devices_and_supports_legacy_and_unknown_users():
    snapshot = {
        "measured_at": "2026-11-16T12:00:00+00:00",
        "identities": [
            {"uid": "42", "device_id": 101},
            {"uid": "42", "device_id": 102},
            {"uid": "7", "device_id": None},
            {"uid": "99", "device_id": None},
        ],
    }
    users = [
        SimpleNamespace(id=42, username="device_user"),
        SimpleNamespace(id=7, username="legacy_user"),
    ]
    devices = [
        SimpleNamespace(
            id=101,
            user_id=42,
            device_model="Phone",
            device_os="Android",
            ver_os="16",
            hwid="must-not-be-returned",
        )
    ]

    result = build_online_user_list(snapshot, users, devices)

    assert [item["username"] for item in result] == ["device_user", "legacy_user", None]
    assert len(result[0]["devices"]) == 2
    assert result[0]["devices"][0] == {
        "device_id": 101,
        "is_legacy": False,
        "device_model": "Phone",
        "device_os": "Android",
        "ver_os": "16",
        "last_activity_at": "2026-11-16T12:00:00+00:00",
    }
    assert result[0]["devices"][1]["device_id"] == 102
    assert result[1]["devices"][0]["is_legacy"] is True
    assert result[2]["user_id"] == 99
    assert "hwid" not in json.dumps(result).lower()


class FakePipeline:
    def __init__(self, storage):
        self.storage = storage

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def set(self, key, value, ex=None):
        self.storage[key] = value

    def execute(self):
        return []


class FakeRedis:
    def __init__(self):
        self.storage = {}

    def pipeline(self):
        return FakePipeline(self.storage)

    def get(self, key):
        return self.storage.get(key)


def test_redis_snapshot_stores_only_ids_and_marks_failed_collection_unavailable(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(node_realtime, "_redis", redis)
    monkeypatch.setattr(node_realtime, "_now", lambda: "2026-11-16T12:00:00+00:00")

    node_realtime.set_nodes_online({
        2: {
            "online_users": 1,
            "online_devices": 1,
            "legacy_online_users": 0,
            "unattributed_users": 0,
            "unattributed_devices": 0,
            "identities": [{"uid": "42", "device_id": 101}],
        },
        3: None,
    })

    assert node_realtime.get_node_online_identities(2) == {
        "available": True,
        "identities": [{"uid": "42", "device_id": 101}],
        "measured_at": "2026-11-16T12:00:00+00:00",
    }
    assert node_realtime.get_node_online_identities(3)["available"] is False
    assert node_realtime.get_node_online_identities(4)["available"] is False
    stored = redis.storage["node_users_online_details:2"]
    assert "username" not in stored
    assert "hwid" not in stored.lower()
