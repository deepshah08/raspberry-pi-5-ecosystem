import sys
import os
from pathlib import Path
import datetime
import subprocess
import pytest
from unittest.mock import patch, MagicMock

# Ensure the module can be found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrub_sentinel import (
    is_maintenance_window,
    is_drive_standby,
    check_btrfs_integrity,
    check_zfs_integrity,
    check_integrity,
    prune_snapshots,
    dispatch_alert,
    parse_args
)

def test_maintenance_window():
    # 13:00 to 15:59 is True
    dt_14 = datetime.datetime(2023, 1, 1, 14, 0, 0)
    assert is_maintenance_window(dt_14) == True

    dt_13 = datetime.datetime(2023, 1, 1, 13, 0, 0)
    assert is_maintenance_window(dt_13) == True

    dt_15_59 = datetime.datetime(2023, 1, 1, 15, 59, 59)
    assert is_maintenance_window(dt_15_59) == True

    # Outside is False
    dt_12 = datetime.datetime(2023, 1, 1, 12, 59, 59)
    assert is_maintenance_window(dt_12) == False

    dt_16 = datetime.datetime(2023, 1, 1, 16, 0, 0)
    assert is_maintenance_window(dt_16) == False

@patch("subprocess.run")
def test_is_drive_standby(mock_run):
    # Standby by return code
    mock_run.return_value = MagicMock(returncode=2, stdout="")
    assert is_drive_standby("/dev/sda") == True

    # Standby by output string
    mock_run.return_value = MagicMock(returncode=0, stdout="Device is in STANDBY mode")
    assert is_drive_standby("/dev/sda") == True

    mock_run.return_value = MagicMock(returncode=0, stdout="Device is in SLEEP mode")
    assert is_drive_standby("/dev/sda") == True

    # Active
    mock_run.return_value = MagicMock(returncode=0, stdout="Device is active/idle")
    assert is_drive_standby("/dev/sda") == False

    # File not found
    mock_run.side_effect = FileNotFoundError()
    assert is_drive_standby("/dev/sda") == False

@patch("subprocess.run")
def test_check_btrfs_integrity(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="""
    scrub status for a678
    scrub started
    csum errors: 5
    uncorrectable errors: 2
    """)
    assert check_btrfs_integrity("/volume1") == 7

    mock_run.return_value = MagicMock(returncode=0, stdout="""
    scrub status for a678
    csum errors: 0
    uncorrectable errors: 0
    """)
    assert check_btrfs_integrity("/volume1") == 0

    mock_run.side_effect = FileNotFoundError()
    assert check_btrfs_integrity("/volume1") == 0

@patch("subprocess.run")
def test_check_zfs_integrity(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="""
  pool: zpool1
 state: ONLINE
config:
        NAME        STATE     READ WRITE CKSUM
        zpool1      ONLINE       0     0     0
          sda       ONLINE       0     0     3
          sdb       ONLINE       0     0     0
    """)
    assert check_zfs_integrity("/zpool1") == 3

    mock_run.return_value = MagicMock(returncode=0, stdout="""
  pool: zpool1
 state: ONLINE
config:
        NAME        STATE     READ WRITE CKSUM
        zpool1      ONLINE       0     0     0
          sda       ONLINE       0     0     0
    """)
    assert check_zfs_integrity("/zpool1") == 0

    assert check_zfs_integrity("") == 0

@patch("scrub_sentinel.initiate_btrfs_scrub")
@patch("scrub_sentinel.initiate_zfs_scrub")
@patch("scrub_sentinel.check_btrfs_integrity")
@patch("scrub_sentinel.check_zfs_integrity")
def test_check_integrity(mock_zfs, mock_btrfs, mock_init_zfs, mock_init_btrfs):
    mock_btrfs.return_value = 1
    mock_zfs.return_value = 2
    assert check_integrity("/pool") == 3
    mock_init_btrfs.assert_called_once_with("/pool")
    mock_init_zfs.assert_called_once_with("/pool")

@patch("scrub_sentinel.prune_btrfs_snapshots")
@patch("scrub_sentinel.prune_zfs_snapshots")
def test_prune_snapshots(mock_zfs_prune, mock_btrfs_prune):
    mock_btrfs_prune.return_value = 1
    mock_zfs_prune.return_value = 0
    msg1 = prune_snapshots("/volume1", dry_run=True)
    assert "keep last 30" in msg1
    assert "Pruned 1" in msg1

    mock_btrfs_prune.return_value = 0
    mock_zfs_prune.return_value = 2
    msg2 = prune_snapshots("/volume2", dry_run=True)
    assert "keep last 7" in msg2
    assert "Pruned 2" in msg2

def test_dispatch_alert():
    alert = dispatch_alert(5, "/volume1")
    assert alert is not None
    assert alert["severity"] == "high"
    assert "5 errors" in alert["message"]

    alert2 = dispatch_alert(0, "/volume1")
    assert alert2 is None

@patch("sys.argv", ["scrub_sentinel.py", "--check-now", "--pool-path", "/vol", "--dry-run", "--json"])
def test_parse_args():
    args = parse_args()
    assert args.check_now == True
    assert args.pool_path == "/vol"
    assert args.dry_run == True
    assert args.json == True
