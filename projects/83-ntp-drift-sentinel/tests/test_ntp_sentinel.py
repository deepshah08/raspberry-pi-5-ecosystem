import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import json
from unittest.mock import patch, MagicMock, call
from ntp_sentinel import check_ntp_server, parse_args, run_checks, main

@patch('ntplib.NTPClient')
def test_check_ntp_server_success_no_warning(mock_ntp_client):
    mock_client_instance = mock_ntp_client.return_value
    mock_response = MagicMock()
    mock_response.offset = 0.010  # 10ms
    mock_response.delay = 0.050
    mock_client_instance.request.return_value = mock_response

    result = check_ntp_server("192.168.1.1", 50.0)

    assert result["server"] == "192.168.1.1"
    assert result["offset_seconds"] == 0.010
    assert result["delay_seconds"] == 0.050
    assert result["drift_ms"] == 10.0
    assert result["warning"] is False
    assert result["error"] is None

@patch('ntplib.NTPClient')
def test_check_ntp_server_success_warning(mock_ntp_client):
    mock_client_instance = mock_ntp_client.return_value
    mock_response = MagicMock()
    mock_response.offset = 0.060  # 60ms
    mock_response.delay = 0.050
    mock_client_instance.request.return_value = mock_response

    result = check_ntp_server("192.168.1.1", 50.0)

    assert result["server"] == "192.168.1.1"
    assert result["offset_seconds"] == 0.060
    assert result["delay_seconds"] == 0.050
    assert result["drift_ms"] == 60.0
    assert result["warning"] is True
    assert result["error"] is None

@patch('ntplib.NTPClient')
def test_check_ntp_server_error(mock_ntp_client):
    mock_client_instance = mock_ntp_client.return_value
    mock_client_instance.request.side_effect = Exception("Connection Refused")

    result = check_ntp_server("192.168.1.92", 50.0)

    assert result["server"] == "192.168.1.92"
    assert result["offset_seconds"] is None
    assert result["delay_seconds"] is None
    assert result["drift_ms"] is None
    assert result["warning"] is True
    assert result["error"] == "Connection Refused"

@patch('sys.argv', ['ntp_sentinel.py', '--check-now', '--servers', '10.0.0.1', '10.0.0.2', '--threshold-ms', '100', '--json'])
def test_parse_args():
    args = parse_args()
    assert args.check_now is True
    assert args.servers == ['10.0.0.1', '10.0.0.2']
    assert args.threshold_ms == 100.0
    assert args.json is True
    assert args.dry_run is False

@patch('ntp_sentinel.check_ntp_server')
def test_run_checks_json_output(mock_check, capsys):
    mock_check.side_effect = [
        {"server": "10.0.0.1", "offset_seconds": 0.01, "delay_seconds": 0.05, "drift_ms": 10.0, "warning": False, "error": None}
    ]
    results = run_checks(["10.0.0.1"], 50.0, output_json=True)
    assert len(results) == 1

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output[0]["server"] == "10.0.0.1"

@patch('ntp_sentinel.start_http_server')
@patch('ntp_sentinel.run_checks')
@patch('ntp_sentinel.time.sleep')
@patch('ntp_sentinel.parse_args')
def test_main_prometheus_metrics(mock_parse_args, mock_sleep, mock_run_checks, mock_start_http):
    mock_args = MagicMock()
    mock_args.check_now = False
    mock_args.dry_run = False
    mock_args.json = False
    mock_args.servers = ["10.0.0.1"]
    mock_args.threshold_ms = 50.0
    mock_parse_args.return_value = mock_args

    mock_run_checks.return_value = [
        {"server": "10.0.0.1", "offset_seconds": 0.01, "delay_seconds": 0.05, "drift_ms": 10.0, "warning": False, "error": None}
    ]

    mock_sleep.side_effect = KeyboardInterrupt() # Exit the while loop

    with pytest.raises(KeyboardInterrupt):
        main()

    mock_start_http.assert_called_once_with(9114)
