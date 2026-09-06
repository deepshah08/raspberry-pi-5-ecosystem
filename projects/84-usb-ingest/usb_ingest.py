import os
import sys
import argparse
import subprocess
import logging
import hashlib
from pathlib import Path
from datetime import datetime
import shutil
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DeviceDetector:
    """Detects USB block devices using /sys/block scans."""
    def __init__(self) -> None:
        self.sys_block: Path = Path("/sys/block")

    def get_usb_partitions(self) -> List[str]:
        """Returns a list of partition device paths (e.g., /dev/sdb1) for USB devices."""
        partitions: List[str] = []
        if not self.sys_block.exists():
            logging.warning(f"{self.sys_block} does not exist. Not on a standard Linux system?")
            return partitions

        for dev_path in self.sys_block.iterdir():
            # Check if device is a USB device
            # Typically usb devices will have 'usb' in their readlink path
            try:
                device_link: str = os.readlink(dev_path)
                if 'usb' in device_link.lower():
                    # Look for partitions in the device directory
                    for part_path in dev_path.iterdir():
                        if part_path.is_dir() and part_path.name.startswith(dev_path.name):
                            dev_name: str = part_path.name
                            partitions.append(f"/dev/{dev_name}")
            except OSError:
                pass

        return partitions

class MountCoordinator:
    """Safely invokes read-only mount on target filesystem."""
    def __init__(self, device_path: str, mount_point: str) -> None:
        self.device_path: str = device_path
        self.mount_point: Path = Path(mount_point)

    def mount(self) -> None:
        if not self.mount_point.exists():
            self.mount_point.mkdir(parents=True, exist_ok=True)

        cmd: List[str] = [
            "mount",
            "-o", "ro,noexec,nosuid",
            str(self.device_path),
            str(self.mount_point)
        ]
        logging.info(f"Executing mount: {' '.join(cmd)}")
        subprocess.check_call(cmd)

    def unmount(self) -> None:
        cmd: List[str] = ["umount", str(self.mount_point)]
        logging.info(f"Executing unmount: {' '.join(cmd)}")
        subprocess.check_call(cmd)

class MediaIngester:
    """Copies recognized media files into timestamped staging folder with SHA-256 hash verification."""
    SUPPORTED_EXTENSIONS = {'.mp4', '.mkv', '.jpg', '.cr3', '.flac'}

    def __init__(self, source_dir: str | Path, staging_dir: str | Path, dry_run: bool = False, verify_hash: bool = False) -> None:
        self.source_dir: Path = Path(source_dir)
        self.staging_dir: Path = Path(staging_dir)
        self.dry_run: bool = dry_run
        self.verify_hash: bool = verify_hash

    def _calculate_sha256(self, filepath: str | Path) -> Optional[str]:
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except OSError as e:
            logging.error(f"Failed to read {filepath} for hashing: {e}")
            return None

    def ingest(self) -> None:
        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir: Path = self.staging_dir / timestamp

        dir_created = False

        for root, dirs, files in os.walk(self.source_dir):
            for file in files:
                file_path: Path = Path(root) / file
                if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    rel_path: Path = file_path.relative_to(self.source_dir)
                    dest_path: Path = target_dir / rel_path

                    logging.info(f"Found media file: {file_path}")

                    if not self.dry_run:
                        if not dir_created:
                            target_dir.mkdir(parents=True, exist_ok=True)
                            dir_created = True
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        logging.info(f"Copying {file_path} to {dest_path}")
                        shutil.copy2(file_path, dest_path)

                        if self.verify_hash:
                            logging.info(f"Verifying hash for {file_path}")
                            src_hash: Optional[str] = self._calculate_sha256(file_path)
                            dst_hash: Optional[str] = self._calculate_sha256(dest_path)

                            if src_hash != dst_hash:
                                logging.error(f"Hash mismatch for {file_path}! Src: {src_hash}, Dst: {dst_hash}")
                                raise ValueError(f"Hash mismatch for {file_path}")
                            else:
                                logging.info(f"Hash verification successful for {file_path}")
                    else:
                        logging.info(f"[DRY-RUN] Would copy {file_path} to {dest_path}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-Touch USB Drive Ingest & Media Auto-Mounter")
    parser.add_argument("--scan-now", action="store_true", help="Scan for USB devices immediately")
    parser.add_argument("--staging-dir", type=str, required=True, help="Path to staging directory")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without modifying files")
    parser.add_argument("--verify-hash", action="store_true", help="Verify SHA-256 hashes of copied files")

    args = parser.parse_args()

    if args.scan_now:
        detector = DeviceDetector()
        partitions = detector.get_usb_partitions()

        if not partitions:
            logging.info("No USB partitions detected.")
            return

        for i, partition in enumerate(partitions):
            mount_point = f"/tmp/usb_ingest_mnt_{i}"
            coordinator = MountCoordinator(partition, mount_point)

            try:
                coordinator.mount()

                ingester = MediaIngester(
                    source_dir=mount_point,
                    staging_dir=args.staging_dir,
                    dry_run=args.dry_run,
                    verify_hash=args.verify_hash
                )

                ingester.ingest()

            except Exception as e:
                logging.error(f"Error processing partition {partition}: {e}")
            finally:
                try:
                    coordinator.unmount()
                except Exception as e:
                    logging.error(f"Failed to unmount {partition}: {e}")

if __name__ == "__main__":
    main()
