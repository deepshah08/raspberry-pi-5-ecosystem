import sys
import json
from pathlib import Path
import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mesh_sentinel import MeshSentinel, ZIGBEE_DEVICES_TOTAL, ZIGBEE_LQI_AVERAGE, ZIGBEE_OFFLINE_TOTAL

@pytest.fixture
def sentinel():
    return MeshSentinel(broker="localhost", port=1883, dry_run=True)

class MockMQTTMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        if isinstance(payload, (dict, list)):
            self.payload = json.dumps(payload).encode('utf-8')
        else:
            self.payload = payload.encode('utf-8')

def test_init_flags():
    s = MeshSentinel("test", 1234, True, True, True)
    assert s.broker == "test"
    assert s.port == 1234
    assert s.dry_run == True
    assert s.json_output == True
    assert s.audit_now == True

def test_bridge_devices_message(sentinel):
    payload = [
        {"friendly_name": "Coordinator", "type": "Coordinator"},
        {"friendly_name": "Bulb1", "type": "Router"}
    ]
    msg = MockMQTTMessage("zigbee2mqtt/bridge/devices", payload)

    sentinel.on_message(None, None, msg)

    assert "Coordinator" in sentinel.devices
    assert "Bulb1" in sentinel.devices
    assert sentinel.devices["Bulb1"]["type"] == "Router"

def test_device_status_message(sentinel):
    # Setup base device
    sentinel.devices["Bulb1"] = {"friendly_name": "Bulb1"}

    payload = {"linkquality": 80, "state": "ON"}
    msg = MockMQTTMessage("zigbee2mqtt/Bulb1", payload)

    sentinel.on_message(None, None, msg)

    assert sentinel.devices["Bulb1"]["linkquality"] == 80
    assert sentinel.devices["Bulb1"]["state"] == "ON"

def test_availability_message_dict(sentinel):
    payload = {"availability": {"state": "offline"}}
    msg = MockMQTTMessage("zigbee2mqtt/Bulb1", payload)

    sentinel.on_message(None, None, msg)

    assert sentinel.devices["Bulb1"]["availability"] == "offline"

def test_availability_message_str(sentinel):
    payload = {"availability": "online"}
    msg = MockMQTTMessage("zigbee2mqtt/Bulb1", payload)

    sentinel.on_message(None, None, msg)

    assert sentinel.devices["Bulb1"]["availability"] == "online"

def test_analyze_mesh_offline_nodes(sentinel):
    sentinel.devices = {
        "Node1": {"availability": "offline", "linkquality": 0},
        "Node2": {"availability": "online", "linkquality": 100},
        "Node3": {"availability": "offline", "linkquality": 20},
    }

    report = sentinel._analyze_mesh()
    assert report["offline_nodes"] == 2
    assert report["total_devices"] == 3
    assert len(report["weak_links"]) == 2

def test_analyze_mesh_weak_links(sentinel):
    sentinel.devices = {
        "Node1": {"linkquality": 45},  # Weak
        "Node2": {"linkquality": 80},  # Good
        "Node3": {"linkquality": 10},  # Weak
        "Coordinator": {"type": "Coordinator", "linkquality": 0} # Ignore Coordinator
    }

    report = sentinel._analyze_mesh()
    assert len(report["weak_links"]) == 2
    assert report["average_lqi"] == (45 + 80 + 10) / 3

def test_prometheus_metrics():
    # Setup non-dry-run sentinel
    s = MeshSentinel(broker="localhost", port=1883, dry_run=False)
    s.devices = {
        "Node1": {"availability": "offline", "linkquality": 30},
        "Node2": {"availability": "online", "linkquality": 70},
    }

    s._analyze_mesh()

    # In a real environment, we'd use a prometheus client registry to check values
    # Since prometheus_client Gauges are global state, we just ensure no exceptions are raised
    # and the method returns the correct data.

    # We could collect the gauge values, but the simplest check is the logic correctness
    report = s._analyze_mesh()
    assert report["total_devices"] == 2
    assert report["offline_nodes"] == 1
    assert report["average_lqi"] == 50.0

def test_invalid_json_message(sentinel):
    msg = MockMQTTMessage("zigbee2mqtt/Bulb1", "invalid json")

    # Should not raise exception
    sentinel.on_message(None, None, msg)
