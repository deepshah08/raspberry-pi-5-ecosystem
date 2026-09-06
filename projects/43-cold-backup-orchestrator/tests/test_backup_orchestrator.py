import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sys
import os
sys.modules.pop('backup_orchestrator', None)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backup_orchestrator import BackupOrchestrator

@pytest.fixture
def orchestrator():
    return BackupOrchestrator(source="/tmp/source", target="/tmp/target")

@pytest.fixture
def dry_run_orchestrator():
    return BackupOrchestrator(source="/tmp/source", target="/tmp/target", dry_run=True)

@patch('os.path.ismount')
@patch('os.access')
@patch('pathlib.Path.exists')
def test_verify_mount_success(mock_exists, mock_access, mock_ismount, orchestrator):
    mock_exists.return_value = True
    mock_ismount.return_value = True
    mock_access.return_value = True
    assert orchestrator.verify_mount() is True

@patch('pathlib.Path.exists')
def test_verify_mount_target_not_exists(mock_exists, orchestrator):
    mock_exists.return_value = False
    assert orchestrator.verify_mount() is False

@patch('subprocess.run')
def test_execute_rsync_smr_args(mock_run, orchestrator):
    mock_run.return_value = MagicMock(returncode=0, stdout="Total transferred file size: 1,073,741,824 bytes")
    success, transferred = orchestrator.execute_rsync()
    assert success is True
    assert transferred == 1.0 # 1GB

    args, kwargs = mock_run.call_args
    cmd = args[0]

    assert "rsync" in cmd
    assert "-a" in cmd
    assert "--stats" in cmd
    assert "--bwlimit=60M" in cmd
    assert "--no-inc-recursive" in cmd
    assert "--delete" in cmd
    assert "--exclude=.backup_manifest.sha256*" in cmd
    assert "/tmp/source/" in cmd
    assert "/tmp/target" in cmd

@patch('subprocess.run')
def test_execute_rsync_dry_run(mock_run, dry_run_orchestrator):
    mock_run.return_value = MagicMock(returncode=0, stdout="success")
    success, transferred = dry_run_orchestrator.execute_rsync()
    assert success is True
    assert transferred == 0.0

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert "--dry-run" in cmd

@patch('subprocess.run')
@patch('pathlib.Path.exists')
def test_validate_integrity_success(mock_exists, mock_run, orchestrator):
    mock_exists.return_value = False # Force new manifest generation
    mock_run.return_value = MagicMock(returncode=0)

    assert orchestrator.validate_integrity() is True

    # Should be called twice (generate manifest, move manifest)
    assert mock_run.call_count == 2

    # First call is generation
    generate_call_args = mock_run.call_args_list[0][0][0]
    assert "sha256sum" in generate_call_args
    assert "find" in generate_call_args

    # Second call is move
    move_call_args = mock_run.call_args_list[1][0][0]
    assert move_call_args[0] == "mv"

@patch('subprocess.run')
@patch('pathlib.Path.exists')
def test_validate_integrity_with_verify(mock_exists, mock_run, orchestrator):
    mock_exists.return_value = True # Force verify then generate
    mock_run.return_value = MagicMock(returncode=0)

    assert orchestrator.validate_integrity() is True

    assert mock_run.call_count == 3

    verify_call_args = mock_run.call_args_list[0][0][0]
    assert "sha256sum -c" in verify_call_args

def test_validate_integrity_dry_run(dry_run_orchestrator):
    with patch('subprocess.run') as mock_run:
        assert dry_run_orchestrator.validate_integrity() is True
        mock_run.assert_not_called()

@patch('subprocess.run')
def test_spindown_execution(mock_run, orchestrator):
    def side_effect(*args, **kwargs):
        mock = MagicMock(returncode=0)
        cmd = args[0]
        if "findmnt" in cmd:
            mock.stdout = "/dev/sdc1\n"
        elif "lsblk" in cmd:
            mock.stdout = "sdc\n"
        return mock

    mock_run.side_effect = side_effect
    assert orchestrator.spindown_disk() is True

    # Sync, findmnt, lsblk, umount, hdparm
    assert mock_run.call_count == 5

    assert mock_run.call_args_list[0][0][0] == ["sync"]
    assert mock_run.call_args_list[1][0][0] == ["findmnt", "-n", "-o", "SOURCE", "/tmp/target"]
    assert mock_run.call_args_list[2][0][0] == ["lsblk", "-n", "-d", "-o", "PKNAME", "/dev/sdc1"]
    assert mock_run.call_args_list[3][0][0] == ["umount", "/tmp/target"]
    assert mock_run.call_args_list[4][0][0] == ["hdparm", "-y", "/dev/sdc"]

def test_spindown_dry_run(dry_run_orchestrator):
    with patch('subprocess.run') as mock_run:
        assert dry_run_orchestrator.spindown_disk() is True
        mock_run.assert_not_called()

@patch('requests.post')
@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"})
def test_send_telegram_alert(mock_post, orchestrator):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    orchestrator.send_telegram_alert("Test message")

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "api.telegram.org/bottoken" in args[0]
    assert kwargs["json"]["text"] == "Test message"
    assert kwargs["json"]["chat_id"] == "chat"

@patch('requests.post')
@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"})
def test_send_telegram_alert_dry_run(mock_post, dry_run_orchestrator):
    dry_run_orchestrator.send_telegram_alert("Test message")
    mock_post.assert_not_called()
