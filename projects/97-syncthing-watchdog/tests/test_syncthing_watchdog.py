import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import responses
import argparse
import logging
from unittest.mock import patch, MagicMock
from syncthing_watchdog import SyncthingClient, SyncthingWatchdog, main
import time
from datetime import datetime, timezone

@pytest.fixture
def client():
    return SyncthingClient("http://localhost:8384", "test-key")

@pytest.fixture
def watchdog():
    return SyncthingWatchdog("http://localhost:8384", "test-key", dry_run=True)

@responses.activate
def test_get_config(client):
    responses.add(responses.GET, "http://localhost:8384/rest/config", json={"folders": [{"id": "folder1"}]}, status=200)
    config = client.get_config()
    assert config == {"folders": [{"id": "folder1"}]}

@responses.activate
def test_get_system_status(client):
    responses.add(responses.GET, "http://localhost:8384/rest/system/status", json={"myID": "device1"}, status=200)
    status = client.get_system_status()
    assert status == {"myID": "device1"}

@responses.activate
def test_get_system_connections(client):
    responses.add(responses.GET, "http://localhost:8384/rest/system/connections", json={"connections": {"dev2": {"connected": True}}}, status=200)
    conns = client.get_system_connections()
    assert "connections" in conns

@responses.activate
def test_get_db_completion(client):
    responses.add(responses.GET, "http://localhost:8384/rest/db/completion?device=dev1&folder=folder1", json={"completion": 100.0}, status=200)
    comp = client.get_db_completion("dev1", "folder1")
    assert comp == {"completion": 100.0}

@responses.activate
def test_get_db_ignores(client):
    responses.add(responses.GET, "http://localhost:8384/rest/db/ignores?folder=folder1", json={"ignore": []}, status=200)
    ignores = client.get_db_ignores("folder1")
    assert ignores == {"ignore": []}

@responses.activate
def test_get_db_browse(client):
    responses.add(responses.GET, "http://localhost:8384/rest/db/browse?folder=folder1&prefix=&levels=0", json=[{"name": "file1.txt", "size": 10}], status=200)
    browse = client.get_db_browse("folder1")
    assert len(browse) == 1
    assert browse[0]["name"] == "file1.txt"

@responses.activate
def test_conflict_detection(watchdog):
    responses.add(responses.GET, "http://localhost:8384/rest/config", json={"folders": [{"id": "folder1"}]}, status=200)

    browse_data = [
        {"name": "normal_file.txt", "size": 10},
        {"name": "doc.sync-conflict-20230101-120000-XYZ123.txt", "size": 100, "modTime": "2023"},
        {"name": "dir1", "children": [
            {"name": "image.sync-conflict-abc.png", "size": 50}
        ]}
    ]
    responses.add(responses.GET, "http://localhost:8384/rest/db/browse?folder=folder1&prefix=&levels=0", json=browse_data, status=200)

    conflicts = watchdog.check_conflicts()
    assert len(conflicts) == 2
    assert conflicts[0]['file'] == "doc.sync-conflict-20230101-120000-XYZ123.txt"
    assert conflicts[0]['conflicting_device'] == "XYZ123"
    assert conflicts[1]['file'] == "dir1/image.sync-conflict-abc.png"
    assert conflicts[1]['conflicting_device'] == "UNKNOWN"

@responses.activate
def test_run_check_metrics(watchdog):
    responses.add(responses.GET, "http://localhost:8384/rest/system/connections",
                  json={"connections": {"dev1": {"connected": True}, "dev2": {"connected": False}}}, status=200)

    responses.add(responses.GET, "http://localhost:8384/rest/config",
                  json={"devices": [{"deviceID": "dev1"}, {"deviceID": "dev2"}], "folders": [{"id": "folder1", "devices": [{"deviceID": "dev1"}, {"deviceID": "dev2"}]}]}, status=200)

    responses.add(responses.GET, "http://localhost:8384/rest/db/browse?folder=folder1&prefix=&levels=0", json=[], status=200)

    responses.add(responses.GET, "http://localhost:8384/rest/db/completion?device=dev1&folder=folder1", json={"completion": 80.0}, status=200)

    result = watchdog.run_check()
    assert result['connected_devices'] == 1
    assert len(result['conflicts']) == 0

@patch('sys.argv', ['syncthing_watchdog.py', '--check-now', '--api-key', 'test-key', '--json'])
def test_cli_json_output(capsys):
    with patch('syncthing_watchdog.SyncthingWatchdog.run_check') as mock_run_check:
        mock_run_check.return_value = {"status": "ok"}
        main()
        captured = capsys.readouterr()
        assert '"status": "ok"' in captured.out

@patch('sys.argv', ['syncthing_watchdog.py', '--check-now', '--api-key', 'test-key', '--dry-run'])
def test_cli_dry_run_log(caplog):
    caplog.set_level(logging.INFO)
    with patch('syncthing_watchdog.SyncthingWatchdog.run_check') as mock_run_check:
        mock_run_check.return_value = {"status": "ok"}
        main()
        assert "Check complete:" in caplog.text

@responses.activate
def test_device_disconnection_threshold(watchdog, caplog):
    caplog.set_level(logging.WARNING)
    responses.add(responses.GET, "http://localhost:8384/rest/system/connections",
                  json={"connections": {"dev1": {"connected": True}, "dev2": {"connected": False}}}, status=200)
    responses.add(responses.GET, "http://localhost:8384/rest/config",
                  json={"devices": [{"deviceID": "dev1"}, {"deviceID": "dev2"}], "folders": []}, status=200)

    with patch('syncthing_watchdog.datetime') as mock_datetime:
        # First run at T=0
        mock_datetime.now.return_value = datetime.fromtimestamp(1000, tz=timezone.utc)
        watchdog.run_check()
        assert "disconnected for over 1 hour" not in caplog.text

        # Second run at T=3601 (over 1 hour)
        mock_datetime.now.return_value = datetime.fromtimestamp(4601, tz=timezone.utc)
        watchdog.run_check()
        assert "Device dev2 has been disconnected for over 1 hour." in caplog.text

@responses.activate
def test_stuck_sync_threshold(watchdog, caplog):
    caplog.set_level(logging.WARNING)
    responses.add(responses.GET, "http://localhost:8384/rest/system/connections",
                  json={"connections": {"dev1": {"connected": True}}}, status=200)
    responses.add(responses.GET, "http://localhost:8384/rest/config",
                  json={"devices": [{"deviceID": "dev1"}], "folders": [{"id": "folder1", "devices": [{"deviceID": "dev1"}]}]}, status=200)
    responses.add(responses.GET, "http://localhost:8384/rest/db/browse?folder=folder1&prefix=&levels=0", json=[], status=200)
    responses.add(responses.GET, "http://localhost:8384/rest/db/completion?device=dev1&folder=folder1", json={"completion": 80.0}, status=200)

    with patch('syncthing_watchdog.datetime') as mock_datetime:
        # First run at T=0
        mock_datetime.now.return_value = datetime.fromtimestamp(1000, tz=timezone.utc)
        watchdog.run_check()
        assert "stuck at" not in caplog.text

        # Second run at T=1801 (over 30 mins)
        mock_datetime.now.return_value = datetime.fromtimestamp(2801, tz=timezone.utc)
        watchdog.run_check()
        assert "Sync for folder 'folder1' on device 'dev1' is stuck at 80.00% for over 30 minutes." in caplog.text
