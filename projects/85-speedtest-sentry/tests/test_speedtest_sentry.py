import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from speedtest_sentry import parse_args

def test_parse_args_defaults():
    args = parse_args(["--target-host", "192.168.1.80"])
    assert args.target_host == "192.168.1.80"
    assert args.port == 5201
    assert args.duration == 5
    assert args.threshold_mbps == 800.0
    assert not args.check_now
    assert not args.dry_run
    assert not args.json

def test_parse_args_custom():
    args = parse_args([
        "--target-host", "10.0.0.1",
        "--port", "8080",
        "--duration", "10",
        "--threshold-mbps", "1800.0",
        "--check-now",
        "--dry-run",
        "--json"
    ])
    assert args.target_host == "10.0.0.1"
    assert args.port == 8080
    assert args.duration == 10
    assert args.threshold_mbps == 1800.0
    assert args.check_now
    assert args.dry_run
    assert args.json

from unittest.mock import patch, MagicMock
import socket
from speedtest_sentry import measure_latency, measure_throughput

def test_measure_latency_success():
    with patch("socket.create_connection") as mock_conn, \
         patch("time.time", side_effect=[100.0, 100.005]):
        latency = measure_latency("192.168.1.80", 5201)
        assert abs(latency - 5.0) < 0.0001
        mock_conn.assert_called_once_with(("192.168.1.80", 5201), timeout=2.0)

def test_measure_latency_failure():
    with patch("socket.create_connection", side_effect=socket.timeout):
        latency = measure_latency("192.168.1.80", 5201)
        assert latency == -1.0

def test_measure_throughput_success():
    # Simulate time advancing and sending data
    mock_socket = MagicMock()
    mock_socket.send.return_value = 65536  # 64KB per send

    # We'll make it send 3 times, then time out the loop
    # Duration = 1 second
    times = [100.0, 100.1, 100.2, 100.3, 101.5, 101.5]

    with patch("socket.create_connection", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_socket)))), \
         patch("time.time", side_effect=times):
        # 3 sends * 65536 bytes = 196608 bytes
        # 196608 bytes * 8 = 1572864 bits
        # 1572864 bits / 1,000,000 = 1.572864 megabits
        # Actual duration = 101.5 - 100.0 = 1.5 seconds
        # Mbps = 1.572864 / 1.5 = 1.048576 Mbps
        throughput = measure_throughput("192.168.1.80", 5201, 1)
        assert abs(throughput - 1.048576) < 0.0001
        assert mock_socket.send.call_count >= 1

def test_measure_throughput_failure():
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        throughput = measure_throughput("192.168.1.80", 5201, 1)
        assert throughput == -1.0

from speedtest_sentry import evaluate_link_degraded, run_test

def test_evaluate_link_degraded():
    # Healthy 1GbE
    assert not evaluate_link_degraded(950.0, 800.0)
    # Degraded 1GbE
    assert evaluate_link_degraded(750.0, 800.0)
    # Complete failure
    assert evaluate_link_degraded(-1.0, 800.0)

def test_run_test():
    with patch("speedtest_sentry.measure_latency", return_value=1.5), \
         patch("speedtest_sentry.measure_throughput", return_value=900.0):
        result = run_test("192.168.1.80", 5201, 1, 800.0)
        assert result["rtt_ms"] == 1.5
        assert result["bandwidth_mbps"] == 900.0
        assert not result["link_degraded"]

from prometheus_client import REGISTRY
def test_prometheus_metrics():
    from speedtest_sentry import main
    import threading
    import time

    # Mock parse_args to return known values
    class DummyArgs:
        target_host = "127.0.0.1"
        port = 5201
        duration = 1
        threshold_mbps = 800.0
        check_now = False
        dry_run = False
        json = False

    with patch("speedtest_sentry.parse_args", return_value=DummyArgs()), \
         patch("speedtest_sentry.measure_latency", return_value=1.5), \
         patch("speedtest_sentry.measure_throughput", return_value=900.0), \
         patch("prometheus_client.start_http_server"), \
         patch("speedtest_sentry.time.sleep", side_effect=InterruptedError): # Stop the infinite loop

        try:
            main()
        except InterruptedError:
            pass

        # Metrics should be registered and updated
        bandwidth = REGISTRY.get_sample_value("homelab_network_bandwidth_mbps")
        rtt = REGISTRY.get_sample_value("homelab_network_rtt_ms")
        degraded = REGISTRY.get_sample_value("homelab_network_link_degraded")

        assert bandwidth == 900.0
        assert rtt == 1.5
        assert degraded == 0.0
