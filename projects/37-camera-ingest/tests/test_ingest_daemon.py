import os
import shutil
import pytest
import asyncio
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from ingest_daemon import (
    find_dcim,
    get_media_files,
    compute_checksum,
    copy_and_verify,
    process_ingestion,
    unmount_device
)

@pytest.fixture
def mock_camera_fs(tmp_path):
    """Creates a mock camera file system."""
    source = tmp_path / "sdcard"
    dest = tmp_path / "destination"

    source.mkdir()
    dest.mkdir()

    dcim_path = source / "DCIM" / "100CANON"
    dcim_path.mkdir(parents=True)

    # Create valid media files
    (dcim_path / "img1.JPG").write_text("jpeg content")
    (dcim_path / "img2.cr3").write_text("raw content")
    (dcim_path / "video.mp4").write_text("video content")

    # Create an invalid file
    (dcim_path / "data.txt").write_text("should be ignored")

    return source, dest, dcim_path

def test_find_dcim(mock_camera_fs):
    source, _, dcim_expected = mock_camera_fs

    # Test typical deep nesting
    dcim_found = find_dcim(source)
    assert dcim_found is not None
    assert dcim_found.name == "DCIM"

    # Test root is DCIM
    assert find_dcim(dcim_found) == dcim_found

def test_get_media_files(mock_camera_fs):
    _, _, dcim_expected = mock_camera_fs
    files = get_media_files(dcim_expected.parent)

    assert len(files) == 3
    file_names = [f.name for f in files]
    assert "img1.JPG" in file_names
    assert "img2.cr3" in file_names
    assert "video.mp4" in file_names
    assert "data.txt" not in file_names

def test_compute_checksum(tmp_path):
    f = tmp_path / "test.bin"
    f.write_text("hello world")

    # Checksum of "hello world"
    expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert compute_checksum(f) == expected

@pytest.mark.asyncio
async def test_copy_and_verify(tmp_path):
    src = tmp_path / "src.jpg"
    dest = tmp_path / "dest.jpg"

    src.write_text("test image content")

    semaphore = asyncio.Semaphore(2)
    result = await copy_and_verify(src, dest, semaphore)

    assert result is True
    assert dest.exists()
    assert dest.read_text() == "test image content"

@pytest.mark.asyncio
async def test_copy_and_verify_skip_existing(tmp_path):
    src = tmp_path / "src.jpg"
    dest = tmp_path / "dest.jpg"

    src.write_text("test image content")
    dest.write_text("test image content") # already exists

    # We can patch shutil.copy2 to verify it's not called
    with patch("shutil.copy2") as mock_copy:
        semaphore = asyncio.Semaphore(2)
        result = await copy_and_verify(src, dest, semaphore)
        assert result is True
        mock_copy.assert_not_called()

@patch("subprocess.run")
def test_unmount_device_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    unmount_device("/mnt/test")
    mock_run.assert_called_once_with(["umount", "/mnt/test"], capture_output=True, text=True)

@patch("subprocess.run")
def test_unmount_device_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="device is busy")
    with pytest.raises(RuntimeError, match="Unmount failed"):
        unmount_device("/mnt/test")

@patch("ingest_daemon.unmount_device")
@patch("ingest_daemon.send_telegram_notification")
@pytest.mark.asyncio
async def test_process_ingestion_success(mock_notify, mock_unmount, mock_camera_fs):
    source, dest, _ = mock_camera_fs

    await process_ingestion(str(source), str(dest), webhook_url="http://fake.webhook", no_unmount=False)

    # Verify files copied
    dest_dcim = dest / "100CANON"
    assert (dest_dcim / "img1.JPG").exists()
    assert (dest_dcim / "img2.cr3").exists()
    assert (dest_dcim / "video.mp4").exists()
    assert not (dest_dcim / "data.txt").exists()

    # Verify webhook called
    assert mock_notify.called
    msg = mock_notify.call_args[0][1]
    assert "✅ Camera Ingestion Complete" in msg
    assert "Files: 3" in msg

    # Verify unmount called
    mock_unmount.assert_called_once_with(str(source))

@patch("ingest_daemon.copy_and_verify", new_callable=AsyncMock)
@patch("ingest_daemon.unmount_device")
@patch("ingest_daemon.send_telegram_notification")
@pytest.mark.asyncio
async def test_process_ingestion_failure(mock_notify, mock_unmount, mock_copy, mock_camera_fs):
    source, dest, _ = mock_camera_fs

    # Force checksum failure for one of the files
    # Return True, False, True to simulate one failure
    mock_copy.side_effect = [True, False, True]

    await process_ingestion(str(source), str(dest), webhook_url="http://fake.webhook", no_unmount=False)

    # Webhook should report failure
    assert mock_notify.called
    msg = mock_notify.call_args[0][1]
    assert "❌ Camera Ingestion Failed" in msg
    assert "Failed: 1" in msg

    # Unmount should NOT be called
    assert not mock_unmount.called
