import argparse
import asyncio
import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional
import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".arw", ".cr3", ".nef", ".dng",  # RAW
    ".jpg", ".jpeg",                 # JPEG
    ".mp4",                          # MP4
}

def find_dcim(source_path: Path) -> Optional[Path]:
    if not source_path.exists() or not source_path.is_dir():
        return None

    # Check if source_path itself is DCIM
    if source_path.name.upper() == "DCIM":
        return source_path

    for item in source_path.rglob("DCIM"):
        if item.is_dir():
            return item

    # Also check case-insensitively
    for item in source_path.rglob("*"):
        if item.is_dir() and item.name.upper() == "DCIM":
            return item

    return None

def get_media_files(dcim_path: Path) -> List[Path]:
    files = []
    for root, _, filenames in os.walk(dcim_path):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append(Path(root) / name)
    return files

def compute_checksum(file_path: Path, chunk_size: int = 8192) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()

async def copy_and_verify(src: Path, dest: Path, semaphore: asyncio.Semaphore) -> bool:
    async with semaphore:
        loop = asyncio.get_running_loop()

        # Ensure destination directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Compute source checksum first
        src_checksum = await loop.run_in_executor(None, compute_checksum, src)

        # Rsync-like behavior: skip if destination exists and matches checksum
        if dest.exists():
            dest_checksum = await loop.run_in_executor(None, compute_checksum, dest)
            if src_checksum == dest_checksum:
                logger.info(f"Skipping {src.name}, already exists and matches checksum.")
                return True

        # Copy file
        await loop.run_in_executor(None, shutil.copy2, src, dest)

        # Compute destination checksum to verify
        dest_checksum = await loop.run_in_executor(None, compute_checksum, dest)

        return src_checksum == dest_checksum

def unmount_device(mount_point: str):
    logger.info(f"Unmounting {mount_point}...")
    result = subprocess.run(["umount", mount_point], capture_output=True, text=True)
    if result.returncode == 0:
        logger.info(f"Successfully unmounted {mount_point}")
    else:
        logger.error(f"Failed to unmount {mount_point}: {result.stderr}")
        raise RuntimeError(f"Unmount failed: {result.stderr}")

async def send_telegram_notification(webhook_url: str, message: str):
    async with aiohttp.ClientSession() as session:
        payload = {"text": message}
        async with session.post(webhook_url, json=payload) as response:
            if response.status not in (200, 204):
                logger.error(f"Failed to send Telegram notification: {response.status}")

async def process_ingestion(source: str, destination: str, webhook_url: Optional[str] = None, no_unmount: bool = False):
    source_path = Path(source)
    dest_path = Path(destination)

    logger.info(f"Starting ingestion from {source} to {destination}")

    dcim_path = find_dcim(source_path)
    if not dcim_path:
        logger.error("No DCIM directory found in the source path.")
        return

    logger.info(f"Found DCIM directory at {dcim_path}")

    media_files = get_media_files(dcim_path)
    if not media_files:
        logger.info("No supported media files found.")
        return

    logger.info(f"Found {len(media_files)} media files.")

    tasks = []
    total_size_bytes = 0

    # Limit concurrency to 2 to prevent SD card thrashing
    semaphore = asyncio.Semaphore(2)

    for src_file in media_files:
        total_size_bytes += src_file.stat().st_size

        # Preserve relative path structure inside DCIM
        rel_path = src_file.relative_to(dcim_path)
        dest_file = dest_path / rel_path

        tasks.append(copy_and_verify(src_file, dest_file, semaphore))

    results = await asyncio.gather(*tasks)

    success_count = sum(results)
    failed_count = len(results) - success_count
    total_gb = total_size_bytes / (1024 ** 3)

    logger.info(f"Transfer complete: {success_count} succeeded, {failed_count} failed.")
    logger.info(f"Total data transferred: {total_gb:.2f} GB")

    if failed_count == 0:
        if webhook_url:
            msg = f"✅ Camera Ingestion Complete!\nFiles: {success_count}\nData Transferred: {total_gb:.2f} GB"
            await send_telegram_notification(webhook_url, msg)

        if not no_unmount:
            unmount_device(source)
    else:
        logger.error("Some files failed checksum verification. Aborting unmount.")
        if webhook_url:
            msg = f"❌ Camera Ingestion Failed!\nSuccessfully copied: {success_count}\nFailed: {failed_count}\nData Transferred: {total_gb:.2f} GB"
            await send_telegram_notification(webhook_url, msg)

def main():
    parser = argparse.ArgumentParser(description="Zero-Touch SD Card Camera Ingest Daemon")
    parser.add_argument("source", help="Source mount point (e.g., /media/pi/SDCARD)")
    parser.add_argument("destination", help="Destination directory (e.g., /mnt/photos_staging)")
    parser.add_argument("--webhook", help="Telegram webhook URL for notifications", default=None)
    parser.add_argument("--no-unmount", action="store_true", help="Do not unmount the source after successful ingestion")

    args = parser.parse_args()

    asyncio.run(process_ingestion(args.source, args.destination, args.webhook, args.no_unmount))

if __name__ == "__main__":
    main()
