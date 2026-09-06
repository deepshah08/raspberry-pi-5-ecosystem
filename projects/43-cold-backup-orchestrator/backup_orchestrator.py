import argparse
import logging
import os
import subprocess
import sys
import time
import requests
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BackupOrchestrator:
    def __init__(self, source: str, target: str, dry_run: bool = False, spindown_only: bool = False):
        self.source = Path(source) if source else None
        self.target = Path(target) if target else None
        self.dry_run = dry_run
        self.spindown_only = spindown_only

    def verify_mount(self) -> bool:
        """Verifies backup drive presence and filesystem readiness."""
        if not self.target:
            logger.error("Target path is not set.")
            return False

        if not self.target.exists():
            logger.error(f"Target path {self.target} does not exist.")
            return False

        if not os.path.ismount(self.target):
            logger.warning(f"Target path {self.target} is not a mount point. It might not be the external drive.")
            # In some setups, we might still want to proceed, but for a backup drive, it usually should be a mount point.
            # We'll consider it a failure for safety if it's not a mount point, unless we override (not implemented).
            return False

        # Additional filesystem readiness checks could go here, e.g. checking read/write permissions.
        if not os.access(self.target, os.R_OK | os.W_OK):
            logger.error(f"Target path {self.target} is not readable/writable.")
            return False

        logger.info(f"Target path {self.target} is mounted and ready.")
        return True

    def run(self):
        start_time = time.time()

        if self.spindown_only:
            logger.info("Spindown only mode enabled.")
            self.spindown_disk()
            return

        if not self.verify_mount():
            logger.error("Mount verification failed. Aborting.")
            self.send_telegram_alert("Backup failed: Mount verification failed.")
            sys.exit(1)

        logger.info("Starting backup process.")

        # Calculate size before
        # Note: simplistic calculation

        rsync_success, transferred_gb = self.execute_rsync()
        if not rsync_success:
            self.send_telegram_alert("Backup failed during rsync phase.")
            sys.exit(1)

        integrity_success = self.validate_integrity()
        if not integrity_success:
            self.send_telegram_alert("Backup failed during integrity validation phase.")
            sys.exit(1)

        spindown_success = self.spindown_disk()

        elapsed_time = time.time() - start_time
        hours, rem = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(rem, 60)
        time_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

        message = f"Backup completed successfully in {time_str}.\nTransferred: {transferred_gb:.2f} GB.\nSpindown {'successful' if spindown_success else 'failed'}."
        self.send_telegram_alert(message)

    def execute_rsync(self) -> tuple[bool, float]:
        """Executes SMR-optimized rsync engine and returns (success, transferred_gb)."""
        logger.info("Executing SMR-optimized rsync.")
        # SMR-optimized rsync engine: Enforces --bwlimit=60M, sequential ordering, single process, and --no-inc-recursive to protect SMR shingled tracks.
        cmd = [
            "rsync",
            "-a", # archive mode
            "--info=progress2",
            "--stats",
            "--bwlimit=60M",
            "--no-inc-recursive", # process all files before transferring, good for SMR sequential writing
            "--delete", # keep target in sync with source
            "--exclude=.backup_manifest.sha256*",
        ]

        if self.dry_run:
            cmd.append("--dry-run")
            logger.info("Running rsync in DRY RUN mode.")

        # Ensure trailing slash on source to copy contents, not the folder itself
        source_str = str(self.source)
        if not source_str.endswith('/'):
            source_str += '/'

        cmd.extend([source_str, str(self.target)])

        logger.info(f"Running command: {' '.join(cmd)}")

        import re
        try:
            # We use subprocess.run to execute a single process sequentially
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("Rsync completed successfully.")
            logger.debug(f"Rsync output:\n{result.stdout}")

            # Parse output for transferred bytes using --stats output
            transferred_bytes = 0.0
            match = re.search(r"Total transferred file size: ([\d,]+) bytes", result.stdout)
            if match:
                transferred_bytes = float(match.group(1).replace(',', ''))

            return True, transferred_bytes / (1024**3)
        except subprocess.CalledProcessError as e:
            logger.error(f"Rsync failed with return code {e.returncode}.")
            logger.error(f"Rsync stderr:\n{e.stderr}")
            return False, 0.0

    def validate_integrity(self) -> bool:
        """Generates and verifies incremental SHA256 checksum manifests."""
        logger.info("Validating integrity with SHA256.")

        if self.dry_run:
            logger.info("Skipping integrity validation in dry run mode.")
            return True

        manifest_file = self.target / ".backup_manifest.sha256"

        # We find all files in the target, and compute their sha256 sums
        # For a massive backup this can be slow, but it's required for integrity validation
        # In a real-world scenario, we might want to do incremental validation or rely on rsync's checksum
        # But the prompt requires: "Integrity validator: Generates and verifies incremental SHA256 checksum manifests."

        import shlex
        try:
            # First, check if manifest exists and verify against it
            if manifest_file.exists():
                logger.info(f"Found existing manifest {manifest_file}. Verifying...")
                # Ensure we run this in the target directory
                verify_cmd = f"cd {shlex.quote(str(self.target))} && sha256sum -c .backup_manifest.sha256"
                try:
                    subprocess.run(verify_cmd, shell=True, check=True, executable='/bin/bash')
                    logger.info("Previous integrity manifest verified successfully.")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Integrity verification failed for existing manifest: {e}")
                    return False

            # Generate a new manifest for the current state.
            cmd = f"cd {shlex.quote(str(self.target))} && find . -type f ! -name '.backup_manifest.sha256' ! -name '.backup_manifest.sha256.new' -exec sha256sum {{}} + > .backup_manifest.sha256.new"
            logger.info(f"Generating new SHA256 manifest: {cmd}")
            subprocess.run(cmd, shell=True, check=True, executable='/bin/bash')

            # Move the new manifest into place
            subprocess.run(["mv", f"{self.target}/.backup_manifest.sha256.new", str(manifest_file)], check=True)
            logger.info("Integrity validation manifest generated successfully.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Integrity validation generation failed: {e}")
            return False

    def spindown_disk(self) -> bool:
        """Syncs OS buffers, unmounts safely if applicable, and dispatches spindown."""
        logger.info("Initiating disk spindown.")

        if self.dry_run:
            logger.info("Skipping disk spindown in dry run mode.")
            return True

        if not self.target:
            logger.error("Target path not set, cannot spindown.")
            return False

        import shlex
        try:
            # Sync OS buffers
            logger.info("Syncing OS buffers...")
            subprocess.run(["sync"], check=True)

            # Find block device before unmounting
            block_dev = None
            try:
                # Use findmnt to get the source device for the mount point
                findmnt_cmd = ["findmnt", "-n", "-o", "SOURCE", str(self.target)]
                result = subprocess.run(findmnt_cmd, check=True, capture_output=True, text=True)
                source_part = result.stdout.strip()
                if source_part:
                    # e.g., /dev/sdb1 -> /dev/sdb
                    # We can use lsblk to get the parent disk
                    lsblk_cmd = ["lsblk", "-n", "-d", "-o", "PKNAME", source_part]
                    lsblk_result = subprocess.run(lsblk_cmd, check=True, capture_output=True, text=True)
                    disk_name = lsblk_result.stdout.strip()
                    if disk_name:
                        block_dev = f"/dev/{disk_name}"
                    else:
                        # Fallback if PKNAME is empty (e.g. source_part is already the disk)
                        lsblk_cmd = ["lsblk", "-n", "-d", "-o", "NAME", source_part]
                        lsblk_result = subprocess.run(lsblk_cmd, check=True, capture_output=True, text=True)
                        disk_name = lsblk_result.stdout.strip()
                        if disk_name:
                            block_dev = f"/dev/{disk_name}"
            except subprocess.CalledProcessError:
                logger.warning(f"Could not reliably determine block device for {self.target}")

            # Unmount
            logger.info(f"Unmounting {self.target}...")
            subprocess.run(["umount", str(self.target)], check=True)

            if block_dev:
                logger.info(f"Dispatching spindown via hdparm on {block_dev}...")
                subprocess.run(["hdparm", "-y", block_dev], check=False)
            else:
                logger.warning("No block device found, skipping hdparm spindown. Relying on udev idle rule.")

            logger.info("Spindown dispatched.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Spindown process failed: {e}")
            return False

    def send_telegram_alert(self, message: str):
        """Sends a Telegram notification."""
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        if not bot_token or not chat_id:
            logger.warning("Telegram credentials not found. Skipping alert.")
            return

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message
        }

        if self.dry_run:
            logger.info(f"DRY RUN: Would send Telegram alert: {message}")
            return

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Telegram alert sent successfully.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram alert: {e}")

def parse_args():
    parser = argparse.ArgumentParser(description="Cold Backup & SMR Spindown Orchestrator")
    parser.add_argument("--source", type=str, help="Source storage path", required=False)
    parser.add_argument("--target", type=str, help="Target backup drive path", required=False)
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without making actual changes")
    parser.add_argument("--spindown-only", action="store_true", help="Only perform the spindown operation")
    return parser.parse_args()

def main():
    args = parse_args()

    if not args.spindown_only and (not args.source or not args.target):
        logger.error("--source and --target are required unless --spindown-only is used.")
        sys.exit(1)

    orchestrator = BackupOrchestrator(
        source=args.source,
        target=args.target,
        dry_run=args.dry_run,
        spindown_only=args.spindown_only
    )
    orchestrator.run()

if __name__ == "__main__":
    main()
