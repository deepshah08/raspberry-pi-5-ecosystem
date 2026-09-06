import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure the parent directory is in sys.path for absolute imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stream_limiter import PlexSessionAuditor, SessionTerminator, ConcurrencyGovernor, MetricsExporter, parse_args

# Mock Data
MOCK_SESSIONS = {
    "MediaContainer": {
        "Metadata": [
            {
                "Session": {"id": "session1"},
                "User": {"title": "user1"},
                "Media": [{"bitrate": 5000}],
                "TranscodeSession": {"videoDecision": "transcode"}
            },
            {
                "Session": {"id": "session2"},
                "User": {"title": "user2"},
                "Media": [{"bitrate": 8000, "Part": [{"Stream": [{"decision": "transcode", "streamType": 1}]}]}],
            },
            {
                "Session": {"id": "session3"},
                "User": {"title": "user3"},
                "Media": [{"bitrate": 15000}],
                "TranscodeSession": {"videoDecision": "direct play"}
            }
        ]
    }
}

@patch("requests.get")
def test_auditor_parsing(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = MOCK_SESSIONS
    mock_get.return_value = mock_response

    auditor = PlexSessionAuditor("http://plex:32400", "token")
    sessions = auditor.get_sessions()

    assert len(sessions) == 3
    assert sessions[0]["session_id"] == "session1"
    assert sessions[0]["user"] == "user1"
    assert sessions[0]["bitrate"] == 5000
    assert sessions[0]["is_transcoding"] is True

    assert sessions[1]["session_id"] == "session2"
    assert sessions[1]["is_transcoding"] is True

    assert sessions[2]["session_id"] == "session3"
    assert sessions[2]["is_transcoding"] is False

@patch("requests.get")
def test_session_terminator(mock_get):
    terminator = SessionTerminator("http://plex:32400", "token", dry_run=False)
    terminator.terminate("session1", "limit exceeded")

    mock_get.assert_called_once_with(
        "http://plex:32400/status/sessions/terminate",
        headers={"X-Plex-Token": "token"},
        params={"sessionId": "session1", "reason": "limit exceeded"}
    )

@patch("requests.get")
def test_session_terminator_dry_run(mock_get):
    terminator = SessionTerminator("http://plex:32400", "token", dry_run=True)
    terminator.terminate("session1", "limit exceeded")

    mock_get.assert_not_called()

def test_concurrency_governor():
    terminator = MagicMock()
    governor = ConcurrencyGovernor(max_transcodes=1, max_streams_per_user=None, terminator=terminator)

    sessions = [
        {"session_id": "session1", "user": "user1", "is_transcoding": True},
        {"session_id": "session2", "user": "user2", "is_transcoding": True},
        {"session_id": "session3", "user": "user3", "is_transcoding": False},
    ]

    governor.enforce(sessions)

    # Max transcodes is 1, so session2 should be terminated
    terminator.terminate.assert_called_once_with("session2", "Hardware transcode limit exceeded. Please try direct play.")

def test_concurrency_governor_max_streams_per_user():
    terminator = MagicMock()
    governor = ConcurrencyGovernor(max_transcodes=2, max_streams_per_user=1, terminator=terminator)

    sessions = [
        {"session_id": "session1", "user": "user1", "is_transcoding": False},
        {"session_id": "session2", "user": "user1", "is_transcoding": False},
        {"session_id": "session3", "user": "user2", "is_transcoding": False},
    ]

    governor.enforce(sessions)

    # Max streams per user is 1, so session2 (user1's second stream) should be terminated
    terminator.terminate.assert_called_once_with("session2", "Stream limit of 1 exceeded for user user1.")

def test_metrics_exporter():
    exporter = MetricsExporter(9117) # Different port for testing

    sessions = [
        {"session_id": "session1", "is_transcoding": True, "bitrate": 5000},
        {"session_id": "session2", "is_transcoding": True, "bitrate": 8000},
        {"session_id": "session3", "is_transcoding": False, "bitrate": 15000},
    ]

    exporter.update(sessions)

    # Test that the values are properly set. It's a bit tricky to read from Gauge directly without internal methods.
    # We can use _value.get() for testing purposes.
    assert exporter.active_streams._value.get() == 3
    assert exporter.transcodes._value.get() == 2
    assert exporter.bandwidth_bps._value.get() == (5000 + 8000 + 15000) * 1000

@patch("sys.argv", ["stream_limiter.py", "--plex-url", "http://plex:32400", "--plex-token", "token", "--max-transcodes", "3", "--check-now", "--dry-run", "--json"])
def test_cli_parsing():
    args = parse_args()
    assert args.plex_url == "http://plex:32400"
    assert args.plex_token == "token"
    assert args.max_transcodes == 3
    assert args.check_now is True
    assert args.dry_run is True
    assert args.json is True
