import argparse
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


class WALReplicator:
    def __init__(self, source_db: str, replica_dir: str, dry_run: bool = False):
        self.source_db = Path(source_db)
        self.replica_dir = Path(replica_dir)
        self.dry_run = dry_run

        self.wal_path = self.source_db.with_name(self.source_db.name + "-wal")
        self.shm_path = self.source_db.with_name(self.source_db.name + "-shm")
        self.last_wal_state: Optional[Tuple[int, float]] = None

        if not self.dry_run:
            self.replica_dir.mkdir(parents=True, exist_ok=True)

    def detect_wal_changes(self) -> bool:
        """Detects if the WAL file has been modified."""
        if not self.wal_path.exists():
            logger.debug(f"WAL file {self.wal_path} does not exist.")
            return False

        try:
            stat = self.wal_path.stat()
            current_state = (stat.st_size, stat.st_mtime)
        except OSError as e:
            logger.error(f"Failed to stat WAL file: {e}")
            return False

        if self.last_wal_state != current_state:
            logger.info(f"WAL file changed. Previous: {self.last_wal_state}, Current: {current_state}")
            self.last_wal_state = current_state
            return True

        return False

    def run_passive_checkpoint(self) -> bool:
        """Runs a PASSIVE checkpoint safely using a read-only connection."""
        if self.dry_run:
            logger.info("DRY RUN: Skipping passive checkpoint.")
            return True

        if not self.source_db.exists():
            logger.error(f"Source DB {self.source_db} does not exist.")
            return False

        try:
            # Connect in standard mode instead of read-only.
            # A read-only connection cannot run WAL checkpoints because it needs to write to the database file
            # to transfer the WAL frames over.
            # (sqlite3 throws "disk I/O error" when PRAGMA wal_checkpoint is run on a read-only connection).
            with sqlite3.connect(self.source_db) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA wal_checkpoint(PASSIVE);")
                result = cursor.fetchone()
                logger.info(f"Passive checkpoint executed. Result: {result}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Failed to run passive checkpoint: {e}")
            return False

    def sync_replica(self) -> bool:
        """Copies the database files to the replica directory."""
        if self.dry_run:
            logger.info("DRY RUN: Skipping sync replica.")
            return True

        replica_db_path = self.replica_dir / self.source_db.name
        replica_wal_path = self.replica_dir / self.wal_path.name
        replica_shm_path = self.replica_dir / self.shm_path.name

        try:
            # Copy main DB
            shutil.copy2(self.source_db, replica_db_path)

            # Copy WAL if exists
            if self.wal_path.exists():
                shutil.copy2(self.wal_path, replica_wal_path)

            # Copy SHM if exists
            if self.shm_path.exists():
                shutil.copy2(self.shm_path, replica_shm_path)

            logger.info(f"Synced replica to {self.replica_dir}")
            return True
        except IOError as e:
            logger.error(f"Failed to sync replica: {e}")
            return False

    def verify_replica(self) -> bool:
        """Verifies the integrity of the replicated database."""
        if self.dry_run:
            logger.info("DRY RUN: Skipping verify replica.")
            return True

        replica_db_path = self.replica_dir / self.source_db.name
        if not replica_db_path.exists():
            logger.error(f"Replica DB {replica_db_path} does not exist.")
            return False

        try:
            with sqlite3.connect(replica_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                result = cursor.fetchone()
                if result and result[0] == "ok":
                    logger.info("Replica integrity check passed.")
                    return True
                else:
                    logger.error(f"Replica integrity check failed. Result: {result}")
                    return False
        except sqlite3.Error as e:
            logger.error(f"Failed to verify replica integrity: {e}")
            return False

    def run_cycle(self):
        """Runs a single replication cycle."""
        if self.detect_wal_changes():
            logger.info("WAL changes detected. Initiating replication cycle.")
            if self.run_passive_checkpoint():
                if self.sync_replica():
                    self.verify_replica()

    def run(self, interval: int):
        """Runs the replication continuously."""
        logger.info(f"Starting replication daemon. Source: {self.source_db}, Replica Dir: {self.replica_dir}, Interval: {interval}s")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                logger.error(f"Unexpected error in replication cycle: {e}")
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Continuous SQLite WAL & State Replication Sentry")
    parser.add_argument("--source-db", required=True, help="Path to the source SQLite database file")
    parser.add_argument("--replica-dir", required=True, help="Path to the replica directory")
    parser.add_argument("--interval", type=int, default=10, help="Interval in seconds between replication cycles (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Run without modifying state or copying files")

    args = parser.parse_args()

    replicator = WALReplicator(
        source_db=args.source_db,
        replica_dir=args.replica_dir,
        dry_run=args.dry_run
    )

    replicator.run(args.interval)

if __name__ == "__main__":
    main()
