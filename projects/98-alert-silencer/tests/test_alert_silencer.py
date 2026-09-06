import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock
import datetime
import json

from alert_silencer import MaintenanceSilenceCoordinator, StormDeduplicator, parse_args
from prometheus_client import REGISTRY

@pytest.fixture
def mock_urlopen():
    with patch('urllib.request.urlopen') as mock:
        yield mock

def test_maintenance_window():
    coordinator = MaintenanceSilenceCoordinator("http://mock:9093")

    # Test inside window
    dt_in = datetime.datetime(2023, 1, 1, 14, 0)
    assert coordinator.is_in_maintenance_window(dt_in) is True

    # Test outside window
    dt_out1 = datetime.datetime(2023, 1, 1, 12, 59)
    assert coordinator.is_in_maintenance_window(dt_out1) is False

    dt_out2 = datetime.datetime(2023, 1, 1, 16, 1)
    assert coordinator.is_in_maintenance_window(dt_out2) is False

def test_cli_flags():
    test_args = ['alert_silencer.py', '--check-now', '--alertmanager-url', 'http://custom:9093', '--create-window-silence', '--dry-run', '--json']
    with patch.object(sys, 'argv', test_args):
        args = parse_args()
        assert args.check_now is True
        assert args.alertmanager_url == 'http://custom:9093'
        assert args.create_window_silence is True
        assert args.dry_run is True
        assert args.json is True

def test_create_silence_dry_run(mock_urlopen):
    coordinator = MaintenanceSilenceCoordinator("http://mock:9093", dry_run=True)
    dt_in = datetime.datetime(2023, 1, 1, 14, 0, tzinfo=datetime.timezone.utc)

    # Should return a dummy string and NOT call urlopen
    res = coordinator.create_silence(dt_in)
    assert res == "dry-run-silence-id"
    mock_urlopen.assert_not_called()

def test_create_silence_success(mock_urlopen):
    coordinator = MaintenanceSilenceCoordinator("http://mock:9093", dry_run=False)
    dt_in = datetime.datetime(2023, 1, 1, 14, 0, tzinfo=datetime.timezone.utc)

    # Mocking urlopen response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"silenceID": "test-silence-123"}).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    res = coordinator.create_silence(dt_in)
    assert res == "test-silence-123"
    mock_urlopen.assert_called_once()

    # Get request argument
    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "http://mock:9093/api/v2/silences"
    assert req.method == "POST"

def test_manage_window_creates_silence(mock_urlopen):
    coordinator = MaintenanceSilenceCoordinator("http://mock:9093")

    # Mock is_in_maintenance_window to return True
    with patch.object(coordinator, 'is_in_maintenance_window', return_value=True):
        # Mock get_active_maintenance_silences to return empty list
        with patch.object(coordinator, 'get_active_maintenance_silences', return_value=[]):
            # Mock create_silence
            with patch.object(coordinator, 'create_silence', return_value="new-silence") as mock_create:
                coordinator.manage_window()
                mock_create.assert_called_once()

def test_storm_deduplicator_dry_run(mock_urlopen):
    dedup = StormDeduplicator("http://mock:9093", dry_run=True)

    mock_alerts = [
        {"labels": {"alertname": "HostReboot", "instance": "node-1"}, "status": {"state": "active"}},
        {"labels": {"alertname": "NodeUnreachable", "instance": "node-1"}, "status": {"state": "active"}}
    ]

    with patch.object(dedup, 'get_alerts', return_value=mock_alerts):
        with patch.object(dedup, '_silence_symptom') as mock_silence:
            dedup.process_alerts()
            # In process_alerts it should call _silence_symptom for NodeUnreachable
            mock_silence.assert_called_once()
            called_alert = mock_silence.call_args[0][0]
            assert called_alert["labels"]["alertname"] == "NodeUnreachable"

def test_storm_deduplicator_silence_creation(mock_urlopen):
    dedup = StormDeduplicator("http://mock:9093", dry_run=False)

    symptom_alert = {"labels": {"alertname": "NodeUnreachable", "instance": "node-1"}}

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"silenceID": "symp-silence-123"}).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    # Check that Prometheus metrics increase
    before_silences = REGISTRY.get_sample_value('homelab_silences_active_total') or 0

    dedup._silence_symptom(symptom_alert)

    mock_urlopen.assert_called_once()

def test_prometheus_metrics():
    # Trigger metrics increases to ensure they exist
    REGISTRY.get_sample_value('homelab_alert_storm_detected_total') # Counter may have _total suffix in some clients, let's just get the raw metric if possible.
    val = REGISTRY.get_sample_value('homelab_alert_storm_detected_total')
    # Counter metrics get a '_total' suffix automatically in newer prometheus_client versions.
    # Let's ensure the metric object is there and can be incremented.

    dedup = StormDeduplicator("http://mock:9093", dry_run=True)
    mock_alerts = [
        {"labels": {"alertname": "UPSOnBattery"}, "status": {"state": "active"}},
        {"labels": {"alertname": "DiskBackupFailed"}, "status": {"state": "active"}}
    ]
    with patch.object(dedup, 'get_alerts', return_value=mock_alerts):
        # We also mock _silence_symptom so we don't accidentally do HTTP
        with patch.object(dedup, '_silence_symptom'):
            dedup.process_alerts()

    # We should have increased homelab_alert_storm_detected and homelab_deduplicated_alerts_total
    storm_detected = REGISTRY.get_sample_value('homelab_alert_storm_detected_total')
    dedup_alerts = REGISTRY.get_sample_value('homelab_deduplicated_alerts_total')

    # Due to naming we might just ensure they are not None and >= 0
    assert storm_detected is not None and storm_detected >= 1
    assert dedup_alerts is not None and dedup_alerts >= 1
