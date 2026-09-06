import sys
from pathlib import Path
import pytest
from unittest.mock import patch, mock_open, MagicMock

# Include parent directory to load route_optimizer
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import route_optimizer

@patch("route_optimizer.subprocess.run")
def test_probe_mtu(mock_run):
    # Mock subprocess.run for MTU probe
    def side_effect(*args, **kwargs):
        payload_size = int(args[0][6])
        mock_result = MagicMock()
        if payload_size + 28 <= 1350:
            mock_result.returncode = 0
        else:
            mock_result.returncode = 1
        return mock_result

    mock_run.side_effect = side_effect
    mtu = route_optimizer.probe_mtu("10.0.0.1")
    assert mtu == 1350

    # Test without target
    assert route_optimizer.probe_mtu(None) == 1280

@patch("route_optimizer.subprocess.run")
def test_measure_latency_and_jitter(mock_run):
    # Mock success latency measurement
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "rtt min/avg/max/mdev = 1.0/15.5/3.0/0.1 ms"
    mock_run.return_value = mock_result

    latency, jitter = route_optimizer.measure_latency_and_jitter("10.0.0.1")
    assert latency == 15.5
    assert jitter == 0.1

    # Test without target
    assert route_optimizer.measure_latency_and_jitter(None) == (-1.0, -1.0)

    # Test failure
    mock_result.returncode = 1
    latency, jitter = route_optimizer.measure_latency_and_jitter("10.0.0.1")
    assert latency == -1.0
    assert jitter == -1.0

def test_verify_dns_leak():
    # Test valid configuration
    valid_resolv = "nameserver 192.168.1.80\nnameserver 192.168.1.92"
    with patch("builtins.open", mock_open(read_data=valid_resolv)):
        assert route_optimizer.verify_dns_leak() is False

    # Test leaked configuration
    leaked_resolv = "nameserver 192.168.1.80\nnameserver 8.8.8.8"
    with patch("builtins.open", mock_open(read_data=leaked_resolv)):
        assert route_optimizer.verify_dns_leak() is True

    # Test error handling (defaults to True for safety)
    with patch("builtins.open", side_effect=Exception("File not found")):
        assert route_optimizer.verify_dns_leak() is True

def test_parse_args():
    with patch("sys.argv", ["route_optimizer.py", "--probe-now", "--target-peer", "10.0.0.1"]):
        args = route_optimizer.parse_args()
        assert args.probe_now is True
        assert args.target_peer == "10.0.0.1"

@patch("route_optimizer.start_http_server")
@patch("route_optimizer.probe_mtu")
@patch("route_optimizer.measure_latency_and_jitter")
@patch("route_optimizer.verify_dns_leak")
@patch("sys.argv", ["route_optimizer.py", "--probe-now", "--target-peer", "10.0.0.1", "--dry-run"])
def test_main_loop(mock_verify_dns, mock_measure_latency, mock_probe_mtu, mock_start_http):
    mock_probe_mtu.return_value = 1380
    mock_measure_latency.return_value = (20.0, 0.5)
    mock_verify_dns.return_value = False

    route_optimizer.main()

    # With dry-run, we should not start HTTP server
    mock_start_http.assert_not_called()
    mock_probe_mtu.assert_called_once_with("10.0.0.1")
    mock_measure_latency.assert_called_once_with("10.0.0.1")
    mock_verify_dns.assert_called_once()

@patch("route_optimizer.probe_mtu")
@patch("route_optimizer.measure_latency_and_jitter")
@patch("route_optimizer.verify_dns_leak")
@patch("sys.argv", ["route_optimizer.py", "--json"])
def test_main_json_output(mock_verify_dns, mock_measure_latency, mock_probe_mtu, capsys):
    mock_verify_dns.return_value = False
    route_optimizer.main()
    captured = capsys.readouterr()
    assert '"status": "success"' in captured.out
    assert '"dns_leak": false' in captured.out
