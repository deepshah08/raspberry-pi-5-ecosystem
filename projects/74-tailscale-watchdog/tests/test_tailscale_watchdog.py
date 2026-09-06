import sys
from pathlib import Path
import json
import pytest
import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tailscale_watchdog import SubnetRouteAuditor, ExpirySentinel, TailnetInspector

def generate_mock_status(key_expiry: str = None, host_name: str = "nas", routes: list = None) -> dict:
    return {
        "Self": {
            "HostName": "watchdog-node",
            "TailscaleIPs": ["100.1.1.1"],
            "KeyExpiry": "2030-01-01T00:00:00Z"
        },
        "Peer": {
            "node-1": {
                "HostName": host_name,
                "TailscaleIPs": ["100.2.2.2"],
                "KeyExpiry": key_expiry,
                "PrimaryRoutes": routes or [],
                "AllowedIPs": routes or []
            }
        }
    }

@pytest.fixture
def authorized_status():
    return generate_mock_status(
        key_expiry="2030-01-01T00:00:00Z",
        host_name="nas",
        routes=["192.168.1.0/24"]
    )

@pytest.fixture
def rogue_status():
    return generate_mock_status(
        key_expiry="2030-01-01T00:00:00Z",
        host_name="hacker-laptop",
        routes=["192.168.1.0/24"]
    )

def test_subnet_route_auditor_authorized(authorized_status):
    auditor = SubnetRouteAuditor(authorized_status)
    alerts = auditor.audit()
    assert len(alerts) == 0

def test_subnet_route_auditor_rogue(rogue_status):
    auditor = SubnetRouteAuditor(rogue_status)
    alerts = auditor.audit()
    assert len(alerts) == 1
    assert "Rogue subnet route detected" in alerts[0]
    assert "hacker-laptop" in alerts[0]

def test_subnet_route_auditor_authorized_by_ip():
    status = generate_mock_status(
        key_expiry="2030-01-01T00:00:00Z",
        host_name="some-device",
        routes=["192.168.1.0/24", "192.168.1.80"]
    )
    auditor = SubnetRouteAuditor(status)
    alerts = auditor.audit()
    assert len(alerts) == 0

def test_expiry_sentinel_healthy():
    status = generate_mock_status(key_expiry="2030-01-01T00:00:00Z")
    sentinel = ExpirySentinel(status)
    alerts = sentinel.check_expirations()
    assert len(alerts) == 0

def test_expiry_sentinel_expiring_soon():
    now = datetime.datetime.now(datetime.timezone.utc)
    soon = now + datetime.timedelta(days=10)
    status = generate_mock_status(key_expiry=soon.isoformat())
    sentinel = ExpirySentinel(status)
    alerts = sentinel.check_expirations()
    assert len(alerts) == 1
    assert "key expiring in" in alerts[0]

def test_expiry_sentinel_expired():
    now = datetime.datetime.now(datetime.timezone.utc)
    past = now - datetime.timedelta(days=1)
    status = generate_mock_status(key_expiry=past.isoformat())
    sentinel = ExpirySentinel(status)
    alerts = sentinel.check_expirations()
    assert len(alerts) == 1
    assert "key has expired!" in alerts[0]

@patch('tailscale_watchdog.TailnetInspector.get_status')
@patch('tailscale_watchdog.AlertDispatcher.dispatch')
def test_cli_dry_run(mock_dispatch, mock_get_status, authorized_status):
    mock_get_status.return_value = authorized_status
    
    # Simulate dry-run
    from tailscale_watchdog import main
    with patch('sys.argv', ['tailscale_watchdog.py', '--check-now', '--dry-run']):
        main()
        
    mock_dispatch.assert_called_once_with([])

@patch('tailscale_watchdog.TailnetInspector.get_status')
@patch('tailscale_watchdog.AlertDispatcher.dispatch')
def test_cli_alerts_generated(mock_dispatch, mock_get_status, rogue_status):
    # Simulate rogue node and expiring soon node
    now = datetime.datetime.now(datetime.timezone.utc)
    soon = now + datetime.timedelta(days=5)
    
    status = rogue_status
    status["Peer"]["node-1"]["KeyExpiry"] = soon.isoformat()
    
    mock_get_status.return_value = status
    
    from tailscale_watchdog import main
    with patch('sys.argv', ['tailscale_watchdog.py', '--check-now']):
        main()
        
    args, kwargs = mock_dispatch.call_args
    alerts = args[0]
    assert len(alerts) == 2
    assert "Rogue subnet route detected" in alerts[0]
    assert "key expiring in" in alerts[1]
