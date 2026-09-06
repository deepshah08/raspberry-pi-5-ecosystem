import os
import sqlite3
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import requests
from backup_orchestrator import RetentionManager, RcloneSyncRunner, SnapshotCoordinator, send_telegram_alert

@pytest.fixture
def temp_dirs(tmp_path):
    source_dir = tmp_path / "source"
    staging_dir = tmp_path / "staging"
    source_dir.mkdir()
    staging_dir.mkdir()

    # Create some dummy files
    (source_dir / "config.txt").write_text("dummy config")

    # Create a dummy sqlite db (file only, we mock the actual connection)
    db_path = source_dir / "data.db"
    db_path.write_text("dummy sqlite db content")

    return source_dir, staging_dir

@patch('sqlite3.connect')
def test_snapshot_generation(mock_connect, temp_dirs):
    source_dir, staging_dir = temp_dirs

    # Mock the connection context manager and execute
    mock_conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn

    coordinator = SnapshotCoordinator(str(source_dir), str(staging_dir))

    snapshot_dir = coordinator.create_snapshot()

    assert snapshot_dir.exists()
    assert (snapshot_dir / "config.txt").exists()
    # The data.db is copied by fallback since it's just dummy text, but we need to check if connect was called

    mock_connect.assert_called_once()
    assert f"file:{source_dir}/data.db?mode=ro" in mock_connect.call_args[0][0]

    mock_conn.execute.assert_called_once()
    assert "VACUUM INTO" in mock_conn.execute.call_args[0][0]

@patch('sqlite3.connect')
def test_snapshot_generation_dry_run(mock_connect, temp_dirs):
    source_dir, staging_dir = temp_dirs
    coordinator = SnapshotCoordinator(str(source_dir), str(staging_dir), dry_run=True)

    snapshot_dir = coordinator.create_snapshot()

    assert not snapshot_dir.exists()

@patch('subprocess.run')
def test_rclone_sync_runner(mock_run, temp_dirs):
    _, staging_dir = temp_dirs
    # Add dummy file to staging_dir for stats test
    (staging_dir / "dummy.txt").write_text("hello")
    mock_run.return_value = MagicMock(stdout="success", stderr="Transferred:   	    3.585 MiB / 3.585 MiB, 100%, 0 B/s, ETA -", returncode=0)

    runner = RcloneSyncRunner("/fake/rclone.conf", "crypt:", "20M")
    result = runner.sync(staging_dir)

    assert result is True
    mock_run.assert_called_once()
    called_args = mock_run.call_args[0][0]
    assert called_args[:3] == ["rclone", "copy", str(staging_dir)]
    assert called_args[3] == f"crypt:/{staging_dir.name}"
    assert "--config" in called_args
    assert "/fake/rclone.conf" in called_args
    assert "--bwlimit" in called_args
    assert "20M" in called_args
    assert "--stats-one-line" in called_args
    assert "--dry-run" not in called_args

    # Check stats parsing
    assert runner.stats["files"] == 1
    assert runner.stats["bytes"] == 5

@patch('subprocess.run')
def test_rclone_sync_runner_dry_run(mock_run, temp_dirs):
    _, staging_dir = temp_dirs
    mock_run.return_value = MagicMock(stdout="success", stderr="", returncode=0)

    runner = RcloneSyncRunner("/fake/rclone.conf", "crypt:", "20M", dry_run=True)
    result = runner.sync(staging_dir)

    assert result is True
    called_args = mock_run.call_args[0][0]
    assert "--dry-run" in called_args

@patch('subprocess.run')
def test_retention_manager(mock_run, temp_dirs):
    _, staging_dir = temp_dirs

    # Create old and new local snapshots
    old_snapshot = staging_dir / "snapshot_old"
    old_snapshot.mkdir()
    new_snapshot = staging_dir / "snapshot_new"
    new_snapshot.mkdir()

    # Fake mtime for old local snapshot to be 10 days ago
    old_time = time.time() - (10 * 86400)
    os.utime(old_snapshot, (old_time, old_time))

    manager = RetentionManager(str(staging_dir), "/fake/rclone.conf", "crypt:", retention_days=7)
    manager.prune_local_snapshots()

    assert not old_snapshot.exists()
    assert new_snapshot.exists()

    # Test prune_remote_snapshots
    # Mock lsf output returning two directories

    now = time.time()
    dt_old = time.localtime(now - (10 * 86400))
    dt_new = time.localtime(now)

    old_str = time.strftime("%Y%m%d_%H%M%S", dt_old)
    new_str = time.strftime("%Y%m%d_%H%M%S", dt_new)

    mock_run.return_value = MagicMock(stdout=f"snapshot_{old_str}/\nsnapshot_{new_str}/\n", returncode=0)

    manager.prune_remote_snapshots()

    # First call is lsf, second call should be purge for the old one
    assert mock_run.call_count == 2
    purge_args = mock_run.call_args_list[1][0][0]

    assert purge_args[:2] == ["rclone", "purge"]
    assert purge_args[2] == f"crypt:/snapshot_{old_str}"

@patch('requests.post')
def test_send_telegram_alert(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    send_telegram_alert("test_token", "test_chat_id", True, "Test success message")

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "test_token" in args[0]

    payload = kwargs['json']
    assert payload['chat_id'] == "test_chat_id"
    assert "✅ SUCCESS" in payload['text']
    assert "Test success message" in payload['text']

@patch('requests.post')
def test_send_telegram_alert_missing_creds(mock_post):
    send_telegram_alert("", "", True, "Should not send")
    mock_post.assert_not_called()
