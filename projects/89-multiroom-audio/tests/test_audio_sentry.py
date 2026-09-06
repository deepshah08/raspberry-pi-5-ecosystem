import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock, patch
from audio_sentry import AudioSentry, SnapcastClient, parse_args

@pytest.fixture
def mock_client():
    client = MagicMock(spec=SnapcastClient)
    return client

from audio_sentry import CLIENTS_CONNECTED, CLIENT_LATENCY, STREAM_ACTIVE

def test_client_discovery(mock_client):
    mock_client.get_status.return_value = {
        "result": {
            "server": {
                "groups": [
                    {
                        "clients": [
                            {"id": "client_1", "connected": True, "host": {"name": "host1"}, "config": {"latency": 10}},
                            {"id": "client_2", "connected": True, "host": {"name": "host2"}, "config": {"latency": 20}}
                        ]
                    }
                ],
                "streams": [
                    {"id": "stream_1", "status": "playing"}
                ]
            }
        }
    }

    sentry = AudioSentry(mock_client, max_latency_ms=50)
    sentry.monitor()

    mock_client.mute_client.assert_not_called()
    assert CLIENTS_CONNECTED._value.get() == 2
    assert STREAM_ACTIVE._value.get() == 1
    assert CLIENT_LATENCY.labels(client_id="client_1", hostname="host1")._value.get() == 10
    assert CLIENT_LATENCY.labels(client_id="client_2", hostname="host2")._value.get() == 20

def test_latency_threshold_breach_and_mute(mock_client):
    mock_client.get_status.return_value = {
        "result": {
            "server": {
                "groups": [
                    {
                        "clients": [
                            {"id": "client_1", "connected": True, "host": {"name": "host1"}, "config": {"latency": 10}},
                            {"id": "client_desync", "connected": True, "host": {"name": "host2"}, "config": {"latency": 60}}
                        ]
                    }
                ],
                "streams": [
                    {"id": "stream_1", "status": "playing"}
                ]
            }
        }
    }

    sentry = AudioSentry(mock_client, max_latency_ms=50)
    sentry.monitor()

    mock_client.mute_client.assert_called_once_with("client_desync", mute=True)

def test_dry_run(mock_client):
    mock_client.get_status.return_value = {
        "result": {
            "server": {
                "groups": [
                    {
                        "clients": [
                            {"id": "client_desync", "connected": True, "host": {"name": "host2"}, "config": {"latency": 60}}
                        ]
                    }
                ],
                "streams": []
            }
        }
    }

    sentry = AudioSentry(mock_client, max_latency_ms=50, dry_run=True)
    sentry.monitor()

    mock_client.mute_client.assert_not_called()

def test_cli_flags():
    test_args = ["audio_sentry.py", "--check-now", "--host", "10.0.0.1", "--port", "1234", "--max-latency-ms", "100", "--dry-run", "--json"]
    with patch("sys.argv", test_args):
        args = parse_args()
        assert args.check_now is True
        assert args.host == "10.0.0.1"
        assert args.port == 1234
        assert args.max_latency_ms == 100
        assert args.dry_run is True
        assert args.json is True
