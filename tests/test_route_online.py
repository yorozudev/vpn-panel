from app.xray.cascade_config import cascade_config, cascade_outbound_tag
from app.xray.route_online import build_routed_online, build_routed_online_counts, parse_access_route


def param(uid, device_id=None, value=100):
    return {"uid": str(uid), "device_id": device_id, "value": value}


def route(entry, exit_, inbound, cascade="VLESS_EXIT"):
    return {
        "entry_node_id": entry,
        "exit_node_id": exit_,
        "entry_inbound_tag": inbound,
        "outbound_tag": cascade_outbound_tag(exit_, cascade),
    }


def observation(item, exit_, inbound, cascade="VLESS_EXIT"):
    return {
        (1, (str(item["uid"]), item["device_id"])): {
            "inbound_tag": inbound,
            "outbound_tag": cascade_outbound_tag(exit_, cascade),
        }
    }


def test_parse_access_log_supports_device_and_legacy_without_exposing_destination():
    device_line = (
        "2026/11/16 12:00:00 from 203.0.113.1:1234 accepted tcp:example.com:443 "
        "[ENTRY_A >> CASCADE_OUT_2_VLESS_EXIT] email: 42.d101.device_user"
    )
    legacy_line = "from 198.51.100.2:443 accepted udp:8.8.8.8:53 [ENTRY_B -> CASCADE_OUT_3_X] email: 7.user"
    assert parse_access_route(device_line) == {
        "uid": "42",
        "device_id": 101,
        "inbound_tag": "ENTRY_A",
        "outbound_tag": "CASCADE_OUT_2_VLESS_EXIT",
    }
    assert parse_access_route(legacy_line)["device_id"] is None
    assert parse_access_route("2026/11/16 rejected [ENTRY >> DIRECT] email: 42.user") is None


def test_two_entry_inbounds_route_devices_to_different_exits():
    first = param(42, 101)
    second = param(42, 102)
    params = {1: [first, second], 2: [], 3: []}
    routes = [route(1, 2, "ENTRY_A"), route(1, 3, "ENTRY_B")]
    observations = {**observation(first, 2, "ENTRY_A"), **observation(second, 3, "ENTRY_B")}

    result = build_routed_online_counts(params, set(), routes, observations)

    assert result[1]["online_users"] == 1
    assert result[1]["online_devices"] == 2
    assert result[2]["online_devices"] == 1
    assert result[3]["online_devices"] == 1
    assert result[1]["unattributed_devices"] == 0


def test_balancer_uses_actual_outbound_tag_not_only_inbound():
    first = param(42, 101)
    second = param(43, 201)
    params = {1: [first, second], 2: [], 3: []}
    routes = [route(1, 2, "ENTRY"), route(1, 3, "ENTRY")]
    observations = {**observation(first, 2, "ENTRY"), **observation(second, 3, "ENTRY")}

    result = build_routed_online_counts(params, set(), routes, observations)

    assert result[2]["online_users"] == 1
    assert result[3]["online_users"] == 1


def test_existing_observation_keeps_long_lived_connection_without_new_access_line():
    active = param(42, 101)
    result = build_routed_online_counts(
        {1: [active], 2: []},
        set(),
        [route(1, 2, "ENTRY")],
        observation(active, 2, "ENTRY"),
    )
    assert result[2]["online_devices"] == 1


def test_missing_route_is_visible_as_unattributed_not_false_zero():
    active = param(42, 101)
    result = build_routed_online_counts({1: [active], 2: []}, set(), [route(1, 2, "ENTRY")], {})
    assert result[1]["unattributed_users"] == 1
    assert result[1]["unattributed_devices"] == 1
    assert result[2]["online_devices"] == 0


def test_direct_and_cascade_identity_on_mixed_exit_is_deduplicated():
    active = param(42, 101)
    result = build_routed_online_counts(
        {1: [active], 2: [active]},
        set(),
        [route(1, 2, "ENTRY")],
        observation(active, 2, "ENTRY"),
    )
    assert result[2]["online_users"] == 1
    assert result[2]["online_devices"] == 1


def test_non_cascade_inbound_on_mixed_entry_is_not_unattributed():
    active = param(42, 101)
    observations = {
        (1, ("42", 101)): {"inbound_tag": "DIRECT_IN", "outbound_tag": "DIRECT"}
    }
    result = build_routed_online_counts({1: [active]}, set(), [route(1, 2, "ENTRY")], observations)
    assert result[1]["unattributed_devices"] == 0


def test_failed_local_collection_remains_unknown():
    result = build_routed_online_counts({2: []}, {2}, [], {})
    assert result[2] is None


def test_online_details_expose_deduplicated_identities_for_entry_and_exit():
    first = param(42, 101)
    second = param(42, 102)
    result = build_routed_online(
        {1: [first, second], 2: [first]},
        set(),
        [route(1, 2, "ENTRY")],
        {**observation(first, 2, "ENTRY"), **observation(second, 2, "ENTRY")},
    )

    assert result[1]["identities"] == [
        {"uid": "42", "device_id": 101},
        {"uid": "42", "device_id": 102},
    ]
    assert result[2]["identities"] == result[1]["identities"]
    assert "identities" not in build_routed_online_counts(
        {1: [first], 2: []},
        set(),
        [route(1, 2, "ENTRY")],
        observation(first, 2, "ENTRY"),
    )[1]


def test_entry_config_enables_access_log_only_on_entry():
    base = {
        "log": {"loglevel": "none"},
        "inbounds": [],
        "outbounds": [],
        "routing": {"rules": []},
    }
    entry_route = {
        "entry_inbound_tag": "ENTRY",
        "exit_node_id": 2,
        "cascade_inbound_tag": "VLESS_EXIT",
        "address": "192.0.2.2",
        "port": 443,
        "uuid": "00000000-0000-0000-0000-000000000000",
        "sni": "example.com",
        "public_key": "public",
        "short_id": "short",
    }
    entry = cascade_config(base, role="entry", entry_routes=[entry_route])
    direct = cascade_config(base, role="direct")
    assert entry["log"] == {"loglevel": "info", "access": "", "error": ""}
    assert direct["log"] == {"loglevel": "none"}
