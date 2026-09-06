import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

def test_seed_monitors(mocker):
    # Setup mock API
    mock_api_class = MagicMock()
    mock_api_instance = mock_api_class.return_value
    mock_api_instance.login = MagicMock()
    mock_api_instance.add_monitor = MagicMock()
    mock_api_instance.disconnect = MagicMock()

    # Import seed_monitors dynamically to ensure mocks are applied
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("seed_monitors", "projects/36-uptime-kuma/seed_monitors.py")
    seed_monitors = importlib.util.module_from_spec(spec)

    # Mocking uptime_kuma_api module within the loaded module
    sys.modules["uptime_kuma_api"] = MagicMock()

    # Need to load the module after mocking sys.modules if we were doing regular imports,
    # but here we just manually replace it in the dynamically loaded module
    spec.loader.exec_module(seed_monitors)

    mock_MonitorType = MagicMock()
    mock_MonitorType.HTTP = "http"
    mock_MonitorType.PORT = "port"
    mock_MonitorType.PING = "ping"

    mocker.patch.object(seed_monitors, 'UptimeKumaApi', mock_api_class)
    mocker.patch.object(seed_monitors, 'MonitorType', mock_MonitorType)

    # Run the main function
    seed_monitors.main()

    # Verify connection
    mock_api_class.assert_called_once_with("http://localhost:3001")
    mock_api_instance.login.assert_called_once_with("admin", "admin")

    # Verify monitor creation (expecting 11 NAS + 6 Pi5 + 1 Gateway = 18 calls)
    assert mock_api_instance.add_monitor.call_count == 18

    # Verify a few specific calls
    mock_api_instance.add_monitor.assert_any_call(
        type="http",
        name="NAS - Plex",
        url="http://192.168.1.80:32400/web"
    )

    mock_api_instance.add_monitor.assert_any_call(
        type="ping",
        name="Gateway - Ping",
        hostname="192.168.1.254"
    )

    mock_api_instance.disconnect.assert_called_once()

import os
import json

def test_alert_bridge_missing_payload(mocker):
    # Import alert_bridge dynamically
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("alert_bridge", "projects/36-uptime-kuma/alert_bridge.py")
    alert_bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alert_bridge)

    client = TestClient(alert_bridge.app)
    response = client.post("/webhook", json={})
    assert response.status_code == 400
    assert "missing 'msg' field" in response.json()["detail"]

def test_alert_bridge_success(mocker, tmp_path):
    # Prepare environment variables
    mocker.patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "test_token",
        "TELEGRAM_CHAT_ID": "test_chat_id",
        "NAS_SLO_WATCHDOG_LOG": str(tmp_path / "test_nas_slo_watchdog.log")
    })

    # Import alert_bridge dynamically
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("alert_bridge", "projects/36-uptime-kuma/alert_bridge.py")
    alert_bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alert_bridge)

    # Update LOG_FILE based on mocked env var inside the module
    alert_bridge.LOG_FILE = str(tmp_path / "test_nas_slo_watchdog.log")

    # Mock httpx AsyncClient
    mock_post = mocker.patch('httpx.AsyncClient.post', new_callable=mocker.AsyncMock)
    mock_post.return_value.raise_for_status = MagicMock()

    client = TestClient(alert_bridge.app)
    payload = {
        "heartbeat": {"status": 0},
        "monitor": {"name": "Test Monitor"},
        "msg": "Connection timeout"
    }

    response = client.post("/webhook", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Alert processed and dispatched"}

    # Check if Telegram was called
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.telegram.org/bottest_token/sendMessage"
    assert "Test Monitor" in kwargs["json"]["text"]
    assert "🔴" in kwargs["json"]["text"]

    # Check if log file was written
    log_file = tmp_path / "test_nas_slo_watchdog.log"
    assert log_file.exists()

    with open(log_file, "r") as f:
        log_entry = json.loads(f.readline())
        assert log_entry["source"] == "uptime-kuma"
        assert log_entry["incident"]["msg"] == "Connection timeout"
