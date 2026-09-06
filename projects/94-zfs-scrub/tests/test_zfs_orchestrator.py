import sys
from pathlib import Path
import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zfs_orchestrator import ZFSOrchestrator, TRIM_AGE_DAYS, SCRUB_ERRORS, SCRUB_PROGRESS

def test_zfs_orchestrator_init():
    orc = ZFSOrchestrator(dry_run=True, json_output=False)
    assert orc.dry_run is True
    assert orc.json_output is False
    assert orc.results == {"trim": {}, "scrub": {}}

@patch('subprocess.run')
def test_is_drive_spinning(mock_run):
    orc = ZFSOrchestrator(dry_run=False)

    # Mock drive spinning (active)
    mock_run.return_value = MagicMock(returncode=0)
    assert orc.is_drive_spinning("/dev/sda") is True

    # Mock drive standby
    mock_run.return_value = MagicMock(returncode=2)
    assert orc.is_drive_spinning("/dev/sdb") is False

@patch('subprocess.run')
def test_get_zpool_drives(mock_run):
    orc = ZFSOrchestrator(dry_run=False)

    mock_stdout = b"pool: volume2\nconfig:\n\tNAME\n\tvolume2\n\t  /dev/nvme0n1\n\t  /dev/nvme1n1"
    mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)

    drives = orc.get_zpool_drives("volume2")
    assert "/dev/nvme0n1" in drives
    assert "/dev/nvme1n1" in drives

@patch('zfs_orchestrator.datetime')
def test_is_maintenance_window(mock_datetime):
    orc = ZFSOrchestrator()

    # Inside window
    mock_datetime.datetime.now.return_value.time.return_value = datetime.time(14, 0)
    mock_datetime.time = datetime.time
    assert orc.is_maintenance_window() is True

    # Outside window
    mock_datetime.datetime.now.return_value.time.return_value = datetime.time(12, 0)
    assert orc.is_maintenance_window() is False

@patch('zfs_orchestrator.ZFSOrchestrator.get_last_action_date')
@patch('subprocess.run')
def test_execute_trim(mock_run, mock_date):
    orc = ZFSOrchestrator(dry_run=False)
    mock_run.return_value = MagicMock(returncode=0)
    # Mock date to be old enough
    mock_date.return_value = datetime.datetime.now() - datetime.timedelta(days=10)

    orc.execute_trim("volume2")
    assert orc.results["trim"]["volume2"] == "success"

@patch('zfs_orchestrator.ZFSOrchestrator.get_last_action_date')
@patch('subprocess.run')
def test_execute_trim_recent(mock_run, mock_date):
    orc = ZFSOrchestrator(dry_run=False)
    mock_run.return_value = MagicMock(returncode=0)
    # Mock date to be too recent
    mock_date.return_value = datetime.datetime.now() - datetime.timedelta(days=2)

    orc.execute_trim("volume2")
    assert orc.results["trim"]["volume2"] == "skipped_recent"

@patch('zfs_orchestrator.ZFSOrchestrator.get_last_action_date')
@patch('zfs_orchestrator.ZFSOrchestrator.is_maintenance_window')
@patch('zfs_orchestrator.ZFSOrchestrator.get_zpool_drives')
@patch('zfs_orchestrator.ZFSOrchestrator.is_drive_spinning')
@patch('subprocess.run')
def test_execute_scrub_success(mock_run, mock_spinning, mock_drives, mock_window, mock_date):
    orc = ZFSOrchestrator(dry_run=False)

    mock_date.return_value = datetime.datetime.now() - datetime.timedelta(days=40)
    mock_window.return_value = True
    mock_drives.return_value = ["/dev/sda", "/dev/sdb"]
    mock_spinning.return_value = True
    mock_run.return_value = MagicMock(returncode=0)

    orc.execute_scrub("volume1")
    assert orc.results["scrub"]["volume1"] == "success"

@patch('zfs_orchestrator.ZFSOrchestrator.get_last_action_date')
def test_execute_scrub_recent(mock_date):
    orc = ZFSOrchestrator(dry_run=False)
    mock_date.return_value = datetime.datetime.now() - datetime.timedelta(days=10)

    orc.execute_scrub("volume1")
    assert orc.results["scrub"]["volume1"] == "skipped_recent"

@patch('zfs_orchestrator.ZFSOrchestrator.get_last_action_date')
@patch('zfs_orchestrator.ZFSOrchestrator.is_maintenance_window')
def test_execute_scrub_outside_window(mock_window, mock_date):
    orc = ZFSOrchestrator(dry_run=False)
    mock_date.return_value = datetime.datetime.now() - datetime.timedelta(days=40)
    mock_window.return_value = False

    orc.execute_scrub("volume1")
    assert orc.results["scrub"]["volume1"] == "skipped_outside_window"

@patch('zfs_orchestrator.ZFSOrchestrator.get_last_action_date')
@patch('zfs_orchestrator.ZFSOrchestrator.is_maintenance_window')
@patch('zfs_orchestrator.ZFSOrchestrator.get_zpool_drives')
@patch('zfs_orchestrator.ZFSOrchestrator.is_drive_spinning')
def test_execute_scrub_drives_standby(mock_spinning, mock_drives, mock_window, mock_date):
    orc = ZFSOrchestrator(dry_run=False)
    mock_date.return_value = datetime.datetime.now() - datetime.timedelta(days=40)
    mock_window.return_value = True
    mock_drives.return_value = ["/dev/sda", "/dev/sdb"]

    # One drive in standby
    mock_spinning.side_effect = [True, False]

    orc.execute_scrub("volume1")
    assert orc.results["scrub"]["volume1"] == "skipped_drives_standby"

@patch('subprocess.run')
def test_update_metrics(mock_run):
    orc = ZFSOrchestrator(dry_run=False)

    # Mock normal status
    mock_stdout_ok = b"pool: volume2\nstate: ONLINE\nscan: scrub repaired 0B in 0h0m with 0 errors\nerrors: No known data errors"
    mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout_ok)

    orc.update_metrics("volume2")
    assert SCRUB_ERRORS.labels(pool="volume2")._value.get() == 0.0

    # Mock in progress
    mock_stdout_prog = b"pool: volume2\nstate: ONLINE\nscan: scrub in progress for 0h1m, 15.50% done\nerrors: No known data errors"
    mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout_prog)

    orc.update_metrics("volume2")
    assert SCRUB_PROGRESS.labels(pool="volume2")._value.get() == 15.5

    # Mock error
    mock_stdout_err = b"pool: volume2\nstate: DEGRADED\nerrors: 5 data errors, use '-v' for a list"
    mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout_err)

    orc.update_metrics("volume2")
    assert SCRUB_ERRORS.labels(pool="volume2")._value.get() == 1.0

@patch('subprocess.run')
def test_get_last_action_date(mock_run):
    orc = ZFSOrchestrator(dry_run=False)

    mock_stdout_scrub = b"scan: scrub repaired 0B in 0h0m with 0 errors on Sun Sep  1 14:00:00 2024\n"
    mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout_scrub)
    dt = orc.get_last_action_date("volume2", "scrub")
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 9
    assert dt.day == 1

    mock_stdout_trim = b"trim: \n\ttrimmed, started at Sun Sep  1 14:00:00 2024)\n"
    mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout_trim)
    dt2 = orc.get_last_action_date("volume2", "trim")
    assert dt2 is not None
    assert dt2.year == 2024

def test_dry_run():
    orc = ZFSOrchestrator(dry_run=True)

    assert orc.is_drive_spinning("/dev/sda") is True
    assert orc.get_zpool_drives("volume2") == ["/dev/sda"]

    orc.execute_trim("volume2")
    assert orc.results["trim"]["volume2"] == "success"

    orc.execute_scrub("volume2")
    assert orc.results["scrub"]["volume2"] == "success"
