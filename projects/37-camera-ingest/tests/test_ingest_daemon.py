import os
import asyncio
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import hashlib

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ingest_daemon import (
    find_dcim,
    get_media_files,
    compute_checksum,
    copy_and_verify,
    unmount_device,
    process_ingestion
)

def test_find_dcim():
    with tempfile.TemporaryDirectory() as temp_dir:
        dcim_path = os.path.join(temp_dir, "DCIM")
        os.makedirs(dcim_path)
        os.makedirs(os.path.join(temp_dir, "OTHER"))

        found_path = find_dcim(Path(temp_dir))
        assert found_path is not None
        assert "DCIM" in str(found_path)

def test_get_media_files():
    with tempfile.TemporaryDirectory() as temp_dir:
        open(os.path.join(temp_dir, "test1.jpg"), 'w').close()
        open(os.path.join(temp_dir, "test2.mp4"), 'w').close()
        open(os.path.join(temp_dir, "test3.txt"), 'w').close()

        files = get_media_files(Path(temp_dir))
        assert len(files) == 2
        file_names = [f.name for f in files]
        assert "test1.jpg" in file_names
        assert "test2.mp4" in file_names

def test_compute_checksum():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"test data")
        temp_path = f.name

    try:
        checksum = compute_checksum(Path(temp_path))
        hasher = hashlib.sha256()
        hasher.update(b"test data")
        assert checksum == hasher.hexdigest()
    finally:
        os.unlink(temp_path)

@pytest.mark.asyncio
async def test_copy_and_verify():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = os.path.join(temp_dir, "src.jpg")
        dst = os.path.join(temp_dir, "dst.jpg")

        with open(src, "wb") as f:
            f.write(b"image data")

        semaphore = asyncio.Semaphore(1)
        success = await copy_and_verify(Path(src), Path(dst), semaphore)
        assert success is True
        assert os.path.exists(dst)

@pytest.mark.asyncio
async def test_copy_and_verify_skip_existing():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = os.path.join(temp_dir, "src.jpg")
        dst = os.path.join(temp_dir, "dst.jpg")

        with open(src, "wb") as f:
            f.write(b"image data")
        with open(dst, "wb") as f:
            f.write(b"image data")

        semaphore = asyncio.Semaphore(1)
        success = await copy_and_verify(Path(src), Path(dst), semaphore)
        assert success is True

def test_unmount_device_success():
    with patch("subprocess.run") as mock_run:
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_run.return_value = mock_process

        try:
            unmount_device("/dev/sdb1")
        except Exception:
            pytest.fail("unmount_device raised an exception unexpectedly")

def test_unmount_device_failure():
    with patch("subprocess.run") as mock_run:
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_run.return_value = mock_process

        with pytest.raises(RuntimeError):
            unmount_device("/dev/sdb1")

@pytest.mark.asyncio
async def test_process_ingestion_success():
    with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
        dcim = os.path.join(src_dir, "DCIM", "100CANON")
        os.makedirs(dcim)
        open(os.path.join(dcim, "IMG_0001.JPG"), 'w').close()

        with patch("ingest_daemon.unmount_device"), \
             patch("ingest_daemon.send_telegram_notification") as mock_alert:

            await process_ingestion(src_dir, dst_dir, webhook_url="http://test")

            assert os.path.exists(os.path.join(dst_dir, "100CANON", "IMG_0001.JPG"))
            mock_alert.assert_called()

@pytest.mark.asyncio
async def test_process_ingestion_failure():
    with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
        # No DCIM directory
        with patch("ingest_daemon.unmount_device"), \
             patch("ingest_daemon.send_telegram_notification") as mock_alert:

            await process_ingestion(src_dir, dst_dir, webhook_url="http://test")

            mock_alert.assert_not_called()
