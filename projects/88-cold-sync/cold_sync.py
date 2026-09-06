#!/usr/bin/env python3
import argparse
import json
import logging
import subprocess
import sys
from typing import Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def get_device_from_path(path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ['df', '-P', path],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) > 1:
            dev = lines[-1].split()[0]
            if dev.startswith('/dev/sd') and dev[-1].isdigit():
                import re
                match = re.match(r'(/dev/sd[a-z]+)\d*', dev)
                if match:
                    return match.group(1)
            return dev
    except Exception as e:
        logging.warning(f"Could not determine device for path {path}: {e}")
    return None

def check_standby(device: Optional[str]) -> bool:
    if not device:
        return False
    try:
        result = subprocess.run(
            ['smartctl', '-n', 'standby', device],
            capture_output=True, text=True
        )
        if "STANDBY" in result.stdout.upper() or result.returncode == 2:
            return True
        return False
    except FileNotFoundError:
        logging.error("smartctl not found. Cannot check standby state.")
        return False
    except Exception as e:
        logging.error(f"Error checking standby state: {e}")
        return False

def run_sync(source: str, target: str, bwlimit: str, dry_run: bool) -> Tuple[bool, str]:
    cmd = ['rsync', '-av']
    if bwlimit:
        cmd.append(f'--bwlimit={bwlimit}')
    if dry_run:
        cmd.append('--dry-run')
    cmd.extend([source, target])

    logging.info(f"Running sync: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info("Sync completed successfully.")
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        logging.error(f"Sync failed with return code {e.returncode}: {e.stderr}")
        return False, e.stderr

def spindown_drive(device: Optional[str]) -> bool:
    if not device:
        return False

    try:
        logging.info("Running sync to flush buffers...")
        subprocess.run(['sync'], check=True)
        logging.info(f"Spinning down device {device}...")
        result = subprocess.run(['hdparm', '-y', device], check=True, capture_output=True, text=True)
        logging.info("Spindown command sent.")
        return True
    except FileNotFoundError:
        logging.error("hdparm not found.")
        return False
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to spin down device {device}: {e.stderr}")
        return False

def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Cold USB Storage Sync")
    parser.add_argument('--sync-now', action='store_true', help="Execute sync immediately")
    parser.add_argument('--source', type=str, required=True, help="Source path for sync")
    parser.add_argument('--target', type=str, required=True, help="Target path for sync")
    parser.add_argument('--bwlimit', type=str, default="60M", help="Bandwidth limit for rsync")
    parser.add_argument('--dry-run', action='store_true', help="Perform a dry run without modifying data")
    parser.add_argument('--json', action='store_true', help="Output results in JSON format")

    args = parser.parse_args()

    output = {
        "status": "started",
        "source": args.source,
        "target": args.target,
        "bwlimit": args.bwlimit,
        "dry_run": args.dry_run,
        "standby_aborted": False,
        "sync_success": False,
        "spindown_success": False
    }

    if not args.sync_now:
        if args.json:
            print(json.dumps(output))
        else:
            logging.info("Started without --sync-now. Exiting.")
        sys.exit(0)

    device = get_device_from_path(args.target)

    if check_standby(device):
        msg = f"Device {device} is in standby. Aborting sync to respect standby."
        if args.json:
            output["status"] = "aborted"
            output["standby_aborted"] = True
            output["error"] = msg
            print(json.dumps(output))
        else:
            logging.info(msg)
        sys.exit(0)

    success, sync_output = run_sync(args.source, args.target, args.bwlimit, args.dry_run)
    output["sync_success"] = success

    if success:
        spindown_success = spindown_drive(device)
        output["spindown_success"] = spindown_success
        output["status"] = "success"
    else:
        output["status"] = "failed"
        output["error"] = sync_output

    if args.json:
        print(json.dumps(output))
    else:
        if success:
            logging.info("Operation completed successfully.")
        else:
            logging.error("Operation failed.")
            sys.exit(1)

if __name__ == "__main__":
    main()
