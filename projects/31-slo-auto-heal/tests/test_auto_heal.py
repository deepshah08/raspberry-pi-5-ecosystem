import json
import pytest
from unittest.mock import patch, MagicMock
from auto_heal_daemon import AutoHealDaemon

@pytest.fixture
def daemon():
    # Use a dummy log path, we will mock the methods that use it
    d = AutoHealDaemon(log_path="/tmp/dummy_incidents.jsonl")
    return d

def test_process_line_valid_json(daemon):
    incident = {
        "id": "inc-001",
        "severity": "SEV-1",
        "status": "open",
        "persistent": False,
        "description": "DB crash",
        "component": "database"
    }

    with patch.object(daemon, 'evaluate_incident') as mock_eval:
        daemon.process_line(json.dumps(incident))
        mock_eval.assert_called_once_with(incident)

def test_process_line_invalid_json(daemon):
    with patch.object(daemon, 'evaluate_incident') as mock_eval:
        daemon.process_line("{invalid json")
        mock_eval.assert_not_called()

def test_evaluate_incident_sev1_open(daemon):
    incident = {
        "id": "inc-001",
        "severity": "SEV-1",
        "status": "open"
    }
    with patch.object(daemon, 'dispatch_remediation', return_value=True) as mock_dispatch:
        daemon.evaluate_incident(incident)
        mock_dispatch.assert_called_once_with(incident)
        assert "inc-001" in daemon.handled_incidents

def test_evaluate_incident_sev2_persistent(daemon):
    incident = {
        "id": "inc-002",
        "severity": "SEV-2",
        "status": "open",
        "persistent": True
    }
    with patch.object(daemon, 'dispatch_remediation', return_value=True) as mock_dispatch:
        daemon.evaluate_incident(incident)
        mock_dispatch.assert_called_once_with(incident)
        assert "inc-002" in daemon.handled_incidents

def test_evaluate_incident_sev2_not_persistent(daemon):
    incident = {
        "id": "inc-003",
        "severity": "SEV-2",
        "status": "open",
        "persistent": False
    }
    with patch.object(daemon, 'dispatch_remediation') as mock_dispatch:
        daemon.evaluate_incident(incident)
        mock_dispatch.assert_not_called()
        assert "inc-003" not in daemon.handled_incidents

def test_evaluate_incident_resolved(daemon):
    incident = {
        "id": "inc-004",
        "severity": "SEV-1",
        "status": "resolved"
    }
    with patch.object(daemon, 'dispatch_remediation') as mock_dispatch:
        daemon.evaluate_incident(incident)
        mock_dispatch.assert_not_called()
        assert "inc-004" not in daemon.handled_incidents

def test_evaluate_incident_duplicate(daemon):
    incident = {
        "id": "inc-005",
        "severity": "SEV-1",
        "status": "open"
    }
    daemon.handled_incidents.add("inc-005")

    with patch.object(daemon, 'dispatch_remediation') as mock_dispatch:
        daemon.evaluate_incident(incident)
        mock_dispatch.assert_not_called()

@patch('auto_heal_daemon.JULES_API_URL', 'http://dummy/api')
@patch('auto_heal_daemon.TELEGRAM_BOT_TOKEN', 'dummy_token')
@patch('auto_heal_daemon.TELEGRAM_CHAT_ID', 'dummy_chat')
def test_dispatch_remediation_success(daemon):
    incident = {
        "id": "inc-006",
        "severity": "SEV-1",
        "status": "open",
        "description": "DNS failure",
        "component": "CoreDNS"
    }

    with patch.object(daemon, '_send_jules_request', return_value=True) as mock_jules, \
         patch.object(daemon, '_send_telegram_alert', return_value=True) as mock_telegram:

        result = daemon.dispatch_remediation(incident)
        assert result is True

        # Verify jules payload
        mock_jules.assert_called_once()
        payload = mock_jules.call_args[0][0]
        assert payload["incident_id"] == "inc-006"
        assert "DNS failure" in payload["prompt"]
        assert payload["component"] == "CoreDNS"

        mock_telegram.assert_called_once()

@patch('auto_heal_daemon.urllib.request.urlopen')
def test_send_jules_request(mock_urlopen, daemon):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch('auto_heal_daemon.JULES_API_URL', 'http://test'):
        assert daemon._send_jules_request({"test": "data"}) is True

@patch('auto_heal_daemon.urllib.request.urlopen')
def test_send_telegram_alert(mock_urlopen, daemon):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    with patch('auto_heal_daemon.TELEGRAM_BOT_TOKEN', 'token'), \
         patch('auto_heal_daemon.TELEGRAM_CHAT_ID', 'chat'):
        assert daemon._send_telegram_alert("Hello") is True
