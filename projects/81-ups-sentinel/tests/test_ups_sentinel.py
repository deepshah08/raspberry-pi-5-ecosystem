import sys
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ups_sentinel import NUTClient, PowerStateMachine, ShutdownOrchestrator, parse_args, update_prometheus_metrics
import ups_sentinel

@pytest.fixture
def mock_socket():
    with patch('socket.socket') as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock_cls.return_value.__enter__.return_value = mock_sock
        yield mock_sock

@pytest.fixture
def orchestrator():
    return ShutdownOrchestrator(dry_run=True)

@pytest.fixture
def state_machine(orchestrator):
    return PowerStateMachine(orchestrator)

def test_nut_client_get_ups_name(mock_socket):
    mock_socket.recv.return_value = b"UPS myups\n"
    client = NUTClient('localhost', 3493)
    assert client.ups_name == 'myups'

def test_nut_client_query_variable(mock_socket):
    # Setup mock to return UPS name on first call, then VAR value on second call
    mock_socket.recv.side_effect = [
        b"UPS myups\n",
        b'VAR myups battery.charge "100.0"\n'
    ]
    client = NUTClient('localhost', 3493)
    assert client.ups_name == 'myups'

    charge = client.query_variable("battery.charge")
    assert charge == "100.0"

def test_nut_client_get_metrics(mock_socket):
    mock_socket.recv.side_effect = [
        b"UPS myups\n",
        b'VAR myups battery.charge "100.0"\n',
        b'VAR myups battery.runtime "1500"\n',
        b'VAR myups ups.status "OL"\n',
        b'VAR myups ups.load "25"\n'
    ]
    client = NUTClient('localhost', 3493)
    metrics = client.get_metrics()

    assert metrics['battery.charge'] == 100.0
    assert metrics['battery.runtime'] == 1500.0
    assert metrics['ups.load'] == 25.0
    assert metrics['ups.status'] == "OL"

def test_state_machine_online_to_on_battery(state_machine, orchestrator):
    with patch.object(orchestrator, 'emit_alert') as mock_alert:
        state_machine.evaluate({'ups.status': 'OB', 'battery.charge': 100.0, 'battery.runtime': 1500.0})
        assert state_machine.last_state == 'ON_BATTERY'
        mock_alert.assert_called_once_with("WARNING: Utility power failed. UPS on battery.")
        assert not state_machine.shutdown_triggered

def test_state_machine_low_battery_charge(state_machine, orchestrator):
    with patch.object(orchestrator, 'perform_shutdown') as mock_shutdown:
        state_machine.evaluate({'ups.status': 'OB', 'battery.charge': 24.0, 'battery.runtime': 1500.0})
        assert state_machine.last_state == 'LOW_BATTERY'
        mock_shutdown.assert_called_once()
        assert state_machine.shutdown_triggered

def test_state_machine_low_battery_runtime(state_machine, orchestrator):
    with patch.object(orchestrator, 'perform_shutdown') as mock_shutdown:
        state_machine.evaluate({'ups.status': 'OB', 'battery.charge': 50.0, 'battery.runtime': 599.0})
        assert state_machine.last_state == 'LOW_BATTERY'
        mock_shutdown.assert_called_once()
        assert state_machine.shutdown_triggered

def test_state_machine_low_battery_status(state_machine, orchestrator):
    with patch.object(orchestrator, 'perform_shutdown') as mock_shutdown:
        state_machine.evaluate({'ups.status': 'LB', 'battery.charge': 100.0, 'battery.runtime': 1500.0})
        assert state_machine.last_state == 'LOW_BATTERY'
        mock_shutdown.assert_called_once()
        assert state_machine.shutdown_triggered

def test_shutdown_orchestrator():
    orchestrator = ShutdownOrchestrator(dry_run=True)
    with patch.object(orchestrator, 'execute_command') as mock_exec:
        orchestrator.perform_shutdown()
        assert mock_exec.call_count == 4
        # Validate order
        calls = mock_exec.call_args_list
        assert calls[0][0][0] == "192.168.1.80"
        assert "docker stop" in calls[0][0][1]
        assert calls[1][0][0] == "192.168.1.80"
        assert "umount /volume1" in calls[1][0][1]
        assert calls[2][0][0] == "192.168.1.92"
        assert "shutdown" in calls[2][0][1]
        assert calls[3][0][0] == "192.168.1.80"
        assert "shutdown" in calls[3][0][1]

def test_prometheus_metrics():
    metrics = {
        'battery.charge': 85.5,
        'battery.runtime': 1200.0,
        'ups.load': 30.0,
        'ups.status': 'OB'
    }
    update_prometheus_metrics(metrics)
    # Check that prometheus vars were updated (hard to introspect without _value, but we ensure no crash)
    assert ups_sentinel.prom_charge._value.get() == 85.5
    assert ups_sentinel.prom_runtime._value.get() == 1200.0
    assert ups_sentinel.prom_load._value.get() == 30.0
    assert ups_sentinel.prom_status._value.get() == 2  # OB = 2

def test_parse_args():
    with patch('sys.argv', ['ups_sentinel.py', '--check-now', '--host', '192.168.1.100', '--port', '1234', '--dry-run', '--json']):
        args = parse_args()
        assert args.check_now is True
        assert args.host == '192.168.1.100'
        assert args.port == 1234
        assert args.dry_run is True
        assert args.json is True
