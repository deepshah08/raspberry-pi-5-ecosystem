#!/usr/bin/env python3
import argparse
import datetime
import json
import logging
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional

from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prometheus Metrics
TRIM_AGE_DAYS = Gauge('homelab_storage_trim_age_days', 'Days since last TRIM', ['pool'])
SCRUB_ERRORS = Gauge('homelab_storage_scrub_errors', 'Number of scrub errors', ['pool'])
SCRUB_PROGRESS = Gauge('homelab_storage_scrub_progress_percent', 'Scrub progress percent', ['pool'])

class ZFSOrchestrator:
    def __init__(self, dry_run: bool = False, json_output: bool = False):
        self.dry_run = dry_run
        self.json_output = json_output
        self.results = {"trim": {}, "scrub": {}}

    def _run_command(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        if self.dry_run:
            logger.info(f"DRY RUN: Would execute: {' '.join(cmd)}")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")
        try:
            return subprocess.run(cmd, check=check, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}\nError: {e.stderr.decode('utf-8', errors='ignore')}")
            raise

    def is_drive_spinning(self, drive: str) -> bool:
        """Checks if a drive is currently spinning using smartctl."""
        # smartctl -n standby <drive> returns non-zero if the drive is in standby
        cmd = ["smartctl", "-n", "standby", drive]
        if self.dry_run:
            logger.info(f"DRY RUN: Assuming drive {drive} is spinning")
            return True

        try:
            result = subprocess.run(cmd, capture_output=True, check=False)
            # If return code is 2, it typically means device is in standby mode.
            # Usually smartctl -n standby exit status 0 means active, 2 means standby.
            if result.returncode == 0:
                return True
            elif result.returncode == 2:
                logger.info(f"Drive {drive} is in standby, skipping scrub.")
                return False
            else:
                # Other errors, assume spinning to be safe or maybe not?
                # Let's assume spinning if we can't tell, or maybe better to skip.
                # Actually, standard behavior: if it's active, rc=0.
                logger.warning(f"smartctl returned {result.returncode} for {drive}. Output: {result.stdout.decode('utf-8', errors='ignore')}")
                return True
        except FileNotFoundError:
            logger.warning("smartctl not found, assuming drive is spinning.")
            return True

    def get_zpool_drives(self, pool: str) -> List[str]:
        """Gets underlying drives for a given zpool."""
        # In a real system, we'd parse zpool status output.
        # For simplicity and testability, we'll run a dummy command or parse if needed.
        cmd = ["zpool", "status", "-P", pool]
        if self.dry_run:
             return ["/dev/sda"]

        try:
            result = subprocess.run(cmd, capture_output=True, check=True)
            output = result.stdout.decode('utf-8', errors='ignore')
            drives = []
            for line in output.split('\n'):
                # Very basic parsing, looking for /dev/
                line = line.strip()
                if line.startswith('/dev/'):
                    parts = line.split()
                    if len(parts) > 0:
                        drives.append(parts[0])
            return drives
        except (subprocess.CalledProcessError, FileNotFoundError):
             logger.warning(f"Failed to get drives for pool {pool}")
             return []


    def get_last_action_date(self, pool: str, action: str) -> Optional[datetime.datetime]:
        """Gets the date of the last scrub or trim for the pool."""
        if self.dry_run:
            return datetime.datetime.now() - datetime.timedelta(days=100)

        cmd = ["zpool", "status"]
        if action == "trim":
            cmd.append("-t")
        cmd.append(pool)

        try:
            result = subprocess.run(cmd, capture_output=True, check=True)
            output = result.stdout.decode('utf-8', errors='ignore')

            if action == "scrub":
                for line in output.split('\n'):
                    if "scrub repaired" in line or "scrub canceled" in line:
                        parts = line.split(' on ')
                        if len(parts) > 1:
                            date_str = parts[-1].strip()
                            try:
                                return datetime.datetime.strptime(date_str, "%a %b %d %H:%M:%S %Y")
                            except ValueError:
                                pass
            elif action == "trim":
                latest_date = None
                for line in output.split('\n'):
                    if "trimmed," in line:
                        match = re.search(r'(?:started|completed) at (.*?)\)', line)
                        if match:
                            date_str = match.group(1).strip()
                            try:
                                dt = datetime.datetime.strptime(date_str, "%a %b %d %H:%M:%S %Y")
                                if latest_date is None or dt > latest_date:
                                    latest_date = dt
                            except ValueError:
                                pass
                return latest_date
        except Exception as e:
            logger.error(f"Failed to get last {action} date for {pool}: {e}")

        return None

    def is_maintenance_window(self) -> bool:
        """Checks if current time is within maintenance window (13:00-16:00)."""
        now = datetime.datetime.now().time()
        start = datetime.time(13, 0)
        end = datetime.time(16, 0)
        return start <= now <= end

    def execute_trim(self, pool: str):
        """Executes a TRIM operation on the specified pool."""
        logger.info(f"Evaluating TRIM for pool: {pool}")

        last_trim = self.get_last_action_date(pool, "trim")
        if last_trim:
            age_days = (datetime.datetime.now() - last_trim).days
            TRIM_AGE_DAYS.labels(pool=pool).set(age_days)
            if age_days < 7 and not self.dry_run:
                logger.info(f"TRIM for {pool} ran {age_days} days ago (less than 7). Skipping.")
                self.results["trim"][pool] = "skipped_recent"
                return
        else:
            logger.info(f"No previous TRIM history found for {pool}.")

        logger.info(f"Initiating TRIM on pool: {pool}")
        cmd = ["zpool", "trim", pool]

        try:
            self._run_command(cmd)
            self.results["trim"][pool] = "success"
            TRIM_AGE_DAYS.labels(pool=pool).set(0)
            logger.info(f"TRIM started on {pool}")
        except Exception as e:
            self.results["trim"][pool] = f"error: {str(e)}"
            logger.error(f"Failed to start TRIM on {pool}: {e}")

    def execute_scrub(self, pool: str):
        """Executes a scrub operation if conditions are met."""
        logger.info(f"Evaluating scrub for pool: {pool}")

        last_scrub = self.get_last_action_date(pool, "scrub")
        if last_scrub:
            age_days = (datetime.datetime.now() - last_scrub).days
            if age_days < 30 and not self.dry_run:
                logger.info(f"Scrub for {pool} ran {age_days} days ago (less than 30). Skipping.")
                self.results["scrub"][pool] = "skipped_recent"
                return
        else:
            logger.info(f"No previous scrub history found for {pool}.")

        if not self.is_maintenance_window() and not self.dry_run:
             logger.info("Outside maintenance window (13:00-16:00), skipping scrub.")
             self.results["scrub"][pool] = "skipped_outside_window"
             return

        # Check drive status
        drives = self.get_zpool_drives(pool)
        all_spinning = True
        for drive in drives:
             if not self.is_drive_spinning(drive):
                 all_spinning = False
                 break

        if not all_spinning and not self.dry_run:
            logger.info(f"Not all drives in {pool} are spinning, skipping scrub.")
            self.results["scrub"][pool] = "skipped_drives_standby"
            return

        logger.info(f"Initiating scrub on pool: {pool}")
        cmd = ["zpool", "scrub", pool]
        try:
            self._run_command(cmd)
            self.results["scrub"][pool] = "success"
            logger.info(f"Scrub started on {pool}")
        except Exception as e:
             self.results["scrub"][pool] = f"error: {str(e)}"
             logger.error(f"Failed to start scrub on {pool}: {e}")

    def update_metrics(self, pool: str):
        """Mock method to update Prometheus metrics based on zpool status."""
        if self.dry_run:
             SCRUB_ERRORS.labels(pool=pool).set(0)
             SCRUB_PROGRESS.labels(pool=pool).set(100)
             return

        cmd = ["zpool", "status", pool]
        try:
             result = subprocess.run(cmd, capture_output=True, check=True)
             output = result.stdout.decode('utf-8', errors='ignore')

             # Parse for scrub errors
             if "with 0 errors" in output or "No known data errors" in output:
                 SCRUB_ERRORS.labels(pool=pool).set(0)
             elif "errors:" in output:
                 # Attempt rudimentary parse
                 lines = output.split('\n')
                 for line in lines:
                     if line.strip().startswith("errors:"):
                         if "No known data errors" not in line:
                             SCRUB_ERRORS.labels(pool=pool).set(1) # Simple indicator

             # Parse for progress (e.g. "scrub in progress for 0h1m, 10.50% done")
             progress = 100.0 # Default if not in progress
             for line in output.split('\n'):
                 if "scrub in progress" in line and "% done" in line:
                     try:
                         percent_str = line.split(',')[-1].split('%')[0].strip()
                         progress = float(percent_str)
                     except ValueError:
                         pass
             SCRUB_PROGRESS.labels(pool=pool).set(progress)

        except Exception as e:
             logger.error(f"Failed to update metrics for {pool}: {e}")

def main():
    parser = argparse.ArgumentParser(description="ZFS Automated Scrub & TRIM Orchestrator")
    parser.add_argument("--check-now", action="store_true", help="Run checks immediately")
    parser.add_argument("--pool", type=str, help="Specify ZFS pool name")
    parser.add_argument("--action", choices=["trim", "scrub", "all"], default="all", help="Action to perform")
    parser.add_argument("--dry-run", action="store_true", help="Run without executing commands")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--port", type=int, default=9120, help="Prometheus metrics port")

    args = parser.parse_args()

    orchestrator = ZFSOrchestrator(dry_run=args.dry_run, json_output=args.json)

    start_http_server(args.port)
    logger.info(f"Prometheus metrics exposed on port {args.port}")

    pools = [args.pool] if args.pool else ["volume2"] # Default to volume2 per context

    def run_cycle():
        for pool in pools:
            orchestrator.update_metrics(pool)

            if args.action in ["trim", "all"]:
                orchestrator.execute_trim(pool)

            if args.action in ["scrub", "all"]:
                orchestrator.execute_scrub(pool)

    if args.check_now:
        run_cycle()
        if args.json:
            print(json.dumps(orchestrator.results, indent=2))
        else:
            logger.info("Operations completed.")
    else:
        logger.info("Running in daemon mode. Metrics are being served.")
        try:
            while True:
                run_cycle()
                time.sleep(3600) # Sleep for an hour and run again
        except KeyboardInterrupt:
            logger.info("Exiting...")

if __name__ == "__main__":
    main()
