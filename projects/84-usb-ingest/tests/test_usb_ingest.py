import sys
from pathlib import Path
import os
import shutil
import hashlib
import pytest
from unittest.mock import patch, MagicMock

# Standard path insertion to make standalone test execution work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from usb_ingest import DeviceDetector, MountCoordinator, MediaIngester, main

@pytest.fixture
def temp_dirs(tmp_path):
    source_dir = tmp_path / "source"
    staging_dir = tmp_path / "staging"
    source_dir.mkdir()
    staging_dir.mkdir()

    # Create valid and invalid media files
    (source_dir / "test1.mp4").write_text("dummy video content")
    (source_dir / "test2.jpg").write_text("dummy image content")
    (source_dir / "test3.txt").write_text("dummy text content - should be ignored")

    # Create subfolder with valid media file
    sub_dir = source_dir / "photos"
    sub_dir.mkdir()
    (sub_dir / "test4.cr3").write_text("dummy raw content")

    return source_dir, staging_dir

@patch('os.readlink')
@patch('pathlib.Path.iterdir')
@patch('pathlib.Path.exists')
def test_device_detector(mock_exists, mock_iterdir, mock_readlink):
    detector = DeviceDetector()

    mock_exists.return_value = True

    # Mock /sys/block contents
    dev_sdb = MagicMock()
    dev_sdb.name = "sdb"

    dev_sda = MagicMock()
    dev_sda.name = "sda"

    mock_iterdir.side_effect = [[dev_sdb, dev_sda]]

    # sdb is usb, sda is not
    def readlink_side_effect(path):
        if "sdb" in getattr(path, "name", str(path)):
            return "../../devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/host4/target4:0:0/4:0:0:0/block/sdb"
        return "../../devices/pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0/block/sda"

    mock_readlink.side_effect = readlink_side_effect

    # Mock partitions inside sdb
    part_sdb1 = MagicMock()
    part_sdb1.is_dir.return_value = True
    part_sdb1.name = "sdb1"

    part_sdb2 = MagicMock()
    part_sdb2.is_dir.return_value = True
    part_sdb2.name = "sdb2"

    dev_sdb.iterdir.return_value = [part_sdb1, part_sdb2]

    partitions = detector.get_usb_partitions()

    assert partitions == ["/dev/sdb1", "/dev/sdb2"]

@patch('subprocess.check_call')
def test_mount_coordinator(mock_check_call, tmp_path):
    mount_point = tmp_path / "mnt"
    coordinator = MountCoordinator("/dev/sdb1", mount_point)

    coordinator.mount()
    mock_check_call.assert_called_with(["mount", "-o", "ro,noexec,nosuid", "/dev/sdb1", str(mount_point)])
    assert mount_point.exists()

    coordinator.unmount()
    mock_check_call.assert_called_with(["umount", str(mount_point)])

def test_media_ingester_filters_and_copies(temp_dirs):
    source_dir, staging_dir = temp_dirs

    ingester = MediaIngester(source_dir, staging_dir)
    ingester.ingest()

    # Find timestamped folder
    timestamp_dirs = list(staging_dir.iterdir())
    assert len(timestamp_dirs) == 1
    target_dir = timestamp_dirs[0]

    # Check copied files
    assert (target_dir / "test1.mp4").exists()
    assert (target_dir / "test2.jpg").exists()
    assert (target_dir / "photos" / "test4.cr3").exists()

    # Check ignored files
    assert not (target_dir / "test3.txt").exists()

def test_media_ingester_dry_run(temp_dirs):
    source_dir, staging_dir = temp_dirs

    ingester = MediaIngester(source_dir, staging_dir, dry_run=True)
    ingester.ingest()

    # No timestamped folder should be created
    timestamp_dirs = list(staging_dir.iterdir())
    assert len(timestamp_dirs) == 0

def test_media_ingester_verify_hash(temp_dirs):
    source_dir, staging_dir = temp_dirs

    ingester = MediaIngester(source_dir, staging_dir, verify_hash=True)
    ingester.ingest()

    # Find timestamped folder
    timestamp_dirs = list(staging_dir.iterdir())
    assert len(timestamp_dirs) == 1
    target_dir = timestamp_dirs[0]

    # Just checking it didn't fail
    assert (target_dir / "test1.mp4").exists()

def test_media_ingester_verify_hash_mismatch(temp_dirs, monkeypatch):
    source_dir, staging_dir = temp_dirs

    ingester = MediaIngester(source_dir, staging_dir, verify_hash=True)

    # Mock internal sha256 function to return mismatched hashes
    original_calc = ingester._calculate_sha256

    def mocked_calc(filepath):
        if str(staging_dir) in str(filepath):
            return "badhash"
        return original_calc(filepath)

    monkeypatch.setattr(ingester, '_calculate_sha256', mocked_calc)

    with pytest.raises(ValueError, match="Hash mismatch"):
        ingester.ingest()

@patch('sys.argv', ['usb_ingest.py', '--scan-now', '--staging-dir', '/tmp/staging', '--dry-run'])
@patch('usb_ingest.DeviceDetector')
def test_main_cli(mock_detector_class):
    mock_detector = mock_detector_class.return_value
    mock_detector.get_usb_partitions.return_value = ["/dev/sdb1"]

    with patch('usb_ingest.MountCoordinator') as mock_mount_class:
        mock_mount = mock_mount_class.return_value

        with patch('usb_ingest.MediaIngester') as mock_ingester_class:
            mock_ingester = mock_ingester_class.return_value

            main()

            mock_detector.get_usb_partitions.assert_called_once()
            mock_mount.mount.assert_called_once()

            mock_ingester_class.assert_called_once_with(
                source_dir="/tmp/usb_ingest_mnt_0",
                staging_dir="/tmp/staging",
                dry_run=True,
                verify_hash=False
            )
            mock_ingester.ingest.assert_called_once()
