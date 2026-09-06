import pytest
from unittest.mock import patch, mock_open, MagicMock
import subprocess
import time
from vpn_sentry import (
    check_handshakes,
    check_dns_leaks,
    check_latency_throughput,
    send_telegram_alert
)

@patch('subprocess.check_output')
@patch('time.time')
def test_check_handshakes_healthy(mock_time, mock_check_output):
    # Setup mock current time to be 1000
    mock_time.return_value = 1000.0

    # Setup mock subprocess output
    # Peer 1 handshake at 900 (100s ago, healthy < 180s)
    # Peer 2 handshake at 990 (10s ago, healthy < 180s)
    mock_output = "peer1_pubkey\t900\npeer2_pubkey\t990\n"
    mock_check_output.return_value = mock_output

    results = check_handshakes("wg0")

    assert "peer1_pubkey" in results
    assert results["peer1_pubkey"][0] is True
    assert results["peer1_pubkey"][1] == 100.0

    assert "peer2_pubkey" in results
    assert results["peer2_pubkey"][0] is True
    assert results["peer2_pubkey"][1] == 10.0

@patch('subprocess.check_output')
@patch('time.time')
def test_check_handshakes_stale_and_none(mock_time, mock_check_output):
    # Setup mock current time to be 1000
    mock_time.return_value = 1000.0

    # Setup mock subprocess output
    # Peer 1 handshake at 800 (200s ago, stale > 180s)
    # Peer 2 handshake at 0 (never)
    mock_output = "peer1_pubkey\t800\npeer2_pubkey\t0\n"
    mock_check_output.return_value = mock_output

    results = check_handshakes("wg0")

    assert "peer1_pubkey" in results
    assert results["peer1_pubkey"][0] is False
    assert results["peer1_pubkey"][1] == 200.0

    assert "peer2_pubkey" in results
    assert results["peer2_pubkey"][0] is False
    assert results["peer2_pubkey"][1] == -1

@patch('builtins.open', new_callable=mock_open, read_data="nameserver 192.168.1.80\nnameserver 192.168.1.92\n")
def test_check_dns_leaks_passed(mock_file):
    assert check_dns_leaks() is True

@patch('builtins.open', new_callable=mock_open, read_data="nameserver 192.168.1.80\nnameserver 8.8.8.8\n")
def test_check_dns_leaks_failed_leak(mock_file):
    assert check_dns_leaks() is False

@patch('builtins.open', new_callable=mock_open, read_data="search localdomain\n")
def test_check_dns_leaks_no_nameservers(mock_file):
    assert check_dns_leaks() is False

@patch('subprocess.check_output')
def test_check_latency_throughput_healthy(mock_check_output):
    mock_output = "4 packets transmitted, 4 received, 0% packet loss, time 3004ms\nrtt min/avg/max/mdev = 0.285/0.380/0.468/0.068 ms"
    mock_check_output.return_value = mock_output

    stats = check_latency_throughput("192.168.1.80")

    assert stats['packet_loss'] == 0.0
    assert stats['rtt_avg'] == 0.380

@patch('subprocess.check_output')
def test_check_latency_throughput_degraded(mock_check_output):
    # Simulate ping failure via exception
    err = subprocess.CalledProcessError(1, 'ping')
    err.output = "4 packets transmitted, 2 received, 50% packet loss, time 3004ms\nrtt min/avg/max/mdev = 0.285/1.500/0.468/0.068 ms"
    mock_check_output.side_effect = err

    stats = check_latency_throughput("192.168.1.80")

    assert stats['packet_loss'] == 50.0
    assert stats['rtt_avg'] == 1.500

@patch('httpx.post')
@patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'mock_token', 'TELEGRAM_CHAT_ID': 'mock_id'})
def test_send_telegram_alert(mock_post):
    mock_response = MagicMock()
    mock_post.return_value = mock_response

    result = send_telegram_alert("Test message")

    assert result is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "api.telegram.org/botmock_token" in args[0]
    assert kwargs['json']['chat_id'] == "mock_id"
    assert "Test message" in kwargs['json']['text']

def test_send_telegram_alert_dry_run():
    result = send_telegram_alert("Test message", dry_run=True)
    assert result is True
