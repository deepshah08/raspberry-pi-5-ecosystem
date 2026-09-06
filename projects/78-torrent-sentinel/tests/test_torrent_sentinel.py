import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock
from torrent_sentinel import (
    QBittorrentClient,
    ConfigurationAuditor,
    RatioEnforcer,
    SpindownHelper,
    parse_args
)

@pytest.fixture
def mock_client():
    client = MagicMock(spec=QBittorrentClient)
    client.get_preferences.return_value = {
        "bittorrent_protocol": 1,
        "max_ratio": 1.0,
        "max_ratio_act": 0,
        "max_active_downloads": 10,
        "max_active_uploads": 10,
        "max_active_torrents": 20
    }
    client.get_torrents.return_value = []
    return client

def test_preference_validation_clean(mock_client):
    auditor = ConfigurationAuditor(mock_client)
    actions = auditor.audit_and_enforce()
    assert len(actions) == 0
    mock_client.set_preferences.assert_not_called()

def test_preference_validation_enforce(mock_client):
    mock_client.get_preferences.return_value = {
        "bittorrent_protocol": 0,
        "max_ratio": 2.0,
        "max_ratio_act": 1,
        "max_active_downloads": 0,
        "max_active_uploads": 0,
        "max_active_torrents": 0
    }
    auditor = ConfigurationAuditor(mock_client)
    actions = auditor.audit_and_enforce()
    assert len(actions) == 6
    assert "Enforced TCP-only transport" in actions[0]
    assert "Enforced GlobalMaxRatio" in actions[1]
    assert "Enforced GlobalMaxRatioAction" in actions[2]
    assert "Enforced Max Active Downloads to 10" in actions[3]
    assert "Enforced Max Active Uploads to 10" in actions[4]
    assert "Enforced Max Active Torrents to 20" in actions[5]
    mock_client.set_preferences.assert_called_once_with({
        "bittorrent_protocol": 1,
        "max_ratio": 1.0,
        "max_ratio_act": 0,
        "max_active_downloads": 10,
        "max_active_uploads": 10,
        "max_active_torrents": 20
    })

def test_preference_validation_dry_run(mock_client):
    mock_client.get_preferences.return_value = {
        "bittorrent_protocol": 0,
        "max_ratio": 2.0,
        "max_ratio_act": 1,
        "max_active_downloads": 0,
        "max_active_uploads": 0,
        "max_active_torrents": 0
    }
    auditor = ConfigurationAuditor(mock_client, dry_run=True)
    actions = auditor.audit_and_enforce()
    assert len(actions) == 6
    assert "[DRY-RUN]" in actions[0]
    mock_client.set_preferences.assert_not_called()

def test_ratio_enforcer_clean(mock_client):
    mock_client.get_torrents.return_value = [
        {"hash": "1", "ratio": 0.5, "state": "uploading"}
    ]
    enforcer = RatioEnforcer(mock_client)
    actions = enforcer.enforce()
    assert len(actions) == 0
    mock_client.pause_torrents.assert_not_called()

def test_ratio_enforcer_pause(mock_client):
    mock_client.get_torrents.return_value = [
        {"hash": "1", "ratio": 1.5, "state": "uploading", "name": "test1"},
        {"hash": "2", "ratio": 0.5, "state": "uploading"}
    ]
    enforcer = RatioEnforcer(mock_client)
    actions = enforcer.enforce()
    assert len(actions) == 1
    assert "Paused torrent 'test1'" in actions[0]
    mock_client.pause_torrents.assert_called_once_with(["1"])

def test_ratio_enforcer_dry_run(mock_client):
    mock_client.get_torrents.return_value = [
        {"hash": "1", "ratio": 1.5, "state": "uploading", "name": "test1"}
    ]
    enforcer = RatioEnforcer(mock_client, dry_run=True)
    actions = enforcer.enforce()
    assert len(actions) == 1
    assert "[DRY-RUN]" in actions[0]
    mock_client.pause_torrents.assert_not_called()

def test_ratio_enforcer_ignores_paused(mock_client):
    mock_client.get_torrents.return_value = [
        {"hash": "1", "ratio": 1.5, "state": "pausedUP", "name": "test1"}
    ]
    enforcer = RatioEnforcer(mock_client)
    actions = enforcer.enforce()
    assert len(actions) == 0
    mock_client.pause_torrents.assert_not_called()

def test_spindown_readiness_ready(mock_client):
    mock_client.get_torrents.return_value = [
        {"hash": "1", "state": "pausedUP"}
    ]
    spindown = SpindownHelper(mock_client)
    actions = spindown.check_spindown_readiness()
    assert len(actions) == 1
    assert "eligible for spindown" in actions[0]

def test_spindown_readiness_not_ready(mock_client):
    mock_client.get_torrents.return_value = [
        {"hash": "1", "state": "uploading"}
    ]
    spindown = SpindownHelper(mock_client)
    actions = spindown.check_spindown_readiness()
    assert len(actions) == 0

def test_parse_args_defaults():
    args = parse_args([])
    assert not args.check_now
    assert args.api_url == "http://localhost:8080"
    assert args.target_ratio == 1.0
    assert not args.dry_run
    assert not args.json

def test_parse_args_custom():
    args = parse_args([
        "--check-now",
        "--api-url", "http://example.com:8080",
        "--target-ratio", "2.5",
        "--dry-run",
        "--json"
    ])
    assert args.check_now
    assert args.api_url == "http://example.com:8080"
    assert args.target_ratio == 2.5
    assert args.dry_run
    assert args.json

