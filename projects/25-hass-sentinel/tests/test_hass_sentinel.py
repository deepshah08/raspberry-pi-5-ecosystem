import sys
from pathlib import Path
import json
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hass_sentinel import HassSentinel

@pytest.fixture
def sentinel():
    return HassSentinel(
        hass_url="http://test-hass:8123",
        token="test_token"
    )

def test_sentinel_initialization():
    sentinel = HassSentinel(
        hass_url="http://test-hass:8123/",
        token="test_token",
        dry_run=True,
        json_output=True
    )
    assert sentinel.hass_url == "http://test-hass:8123"
    assert sentinel.token == "test_token"
    assert sentinel.dry_run is True
    assert sentinel.json_output is True
    assert sentinel.headers["Authorization"] == "Bearer test_token"

@patch("hass_sentinel.requests.get")
def test_get_states_success(mock_get, sentinel):
    mock_response = MagicMock()
    mock_response.json.return_value = [{"entity_id": "sensor.test", "state": "100"}]
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    states = sentinel.get_states()
    assert states == [{"entity_id": "sensor.test", "state": "100"}]
    mock_get.assert_called_once_with("http://test-hass:8123/api/states", headers=sentinel.headers, timeout=10)

@patch("hass_sentinel.requests.get")
def test_get_error_log_success(mock_get, sentinel):
    mock_response = MagicMock()
    mock_response.text = "Error line 1\nError line 2"
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    log = sentinel.get_error_log()
    assert log == "Error line 1\nError line 2"
    mock_get.assert_called_once_with("http://test-hass:8123/api/error_log", headers=sentinel.headers, timeout=10)

def test_audit_entities(sentinel):
    states = [
        {"entity_id": "light.living_room", "state": "on"},
        {"entity_id": "sensor.temperature", "state": "unavailable"},
        {"entity_id": "switch.coffee_maker", "state": "unknown"},
    ]
    unavailable = sentinel.audit_entities(states)
    assert len(unavailable) == 2
    assert "sensor.temperature" in [e["entity_id"] for e in unavailable]
    assert "switch.coffee_maker" in [e["entity_id"] for e in unavailable]

def test_audit_batteries(sentinel):
    states = [
        # Battery device class, state < 20
        {"entity_id": "sensor.phone_battery", "state": "15", "attributes": {"device_class": "battery"}},
        # Battery device class, state >= 20
        {"entity_id": "sensor.tablet_battery", "state": "50", "attributes": {"device_class": "battery"}},
        # 'battery' in entity_id, state < 20
        {"entity_id": "sensor.mouse_battery", "state": "10.5", "attributes": {}},
        # battery_level attribute < 20
        {"entity_id": "sensor.temp_sensor", "state": "22.5", "attributes": {"battery_level": "18"}},
        # Not a battery
        {"entity_id": "light.living_room", "state": "on", "attributes": {}},
    ]
    low_battery = sentinel.audit_batteries(states)
    assert len(low_battery) == 3
    entity_ids = [e["entity_id"] for e in low_battery]
    assert "sensor.phone_battery" in entity_ids
    assert "sensor.mouse_battery" in entity_ids
    assert "sensor.temp_sensor" in entity_ids

def test_parse_error_log(sentinel):
    log_text = """
2023-10-27 10:00:00 WARNING (MainThread) [homeassistant.components.automation.test] Error executing script. Unexpected error for call_service at pos 1: ...
2023-10-27 10:00:00 WARNING (MainThread) [homeassistant.components.automation.test] Error executing script. Unexpected error for call_service at pos 1: ...
2023-10-27 10:01:00 ERROR (MainThread) [homeassistant.components.automation.other] Automation failed.
2023-10-27 10:02:00 INFO (MainThread) [homeassistant.components.automation.other] Automation triggered.
    """
    loops = sentinel.parse_error_log(log_text.strip())
    assert len(loops) == 1
    assert "2023-10-27 10:00:00 WARNING (MainThread) [homeassistant.components.automation.test] Error executing script. Unexpected error for call_service at pos 1: ..." in loops[0]

@patch("hass_sentinel.HassSentinel.get_states")
@patch("hass_sentinel.HassSentinel.get_error_log")
def test_run_audit(mock_get_log, mock_get_states, sentinel):
    mock_get_states.return_value = [
        {"entity_id": "sensor.test1", "state": "unavailable"},
        {"entity_id": "sensor.test2", "state": "15", "attributes": {"device_class": "battery"}},
    ]
    mock_get_log.return_value = "Automation error\nAutomation error"
    
    results = sentinel.run_audit()
    
    assert results["total_entities"] == 2
    assert "sensor.test1" in results["unavailable_entities"]
    assert "sensor.test2" in results["low_battery_entities"]
    assert len(results["automation_loops"]) == 1

@patch("hass_sentinel.HassSentinel.run_audit")
@patch("sys.argv", ["hass_sentinel.py", "--hass-url", "http://test", "--token", "test", "--audit-now", "--json"])
def test_main_cli_args(mock_run_audit):
    from hass_sentinel import main
    with patch("sys.exit") as mock_exit:
        main()
        mock_run_audit.assert_called_once()
        mock_exit.assert_called_once_with(0)
