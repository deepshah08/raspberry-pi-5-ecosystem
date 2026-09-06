import argparse
import json
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List
from prometheus_client import start_http_server, Counter, Gauge

TRANSFERS_TOTAL = Counter('homelab_wormhole_transfers_total', 'Total number of transfers processed')
ACTIVE_TRANSFERS = Gauge('homelab_wormhole_active_transfers', 'Current number of active transfers')
BYTES_TRANSFERRED = Counter('homelab_wormhole_bytes_transferred_total', 'Total bytes transferred')

@dataclass
class TransferSession:
    token: str
    bytes_transferred: int
    start_time: float
    is_active: bool

class TransitSentry:
    def __init__(self):
        self.sessions: Dict[str, TransferSession] = {}

    def start_transfer(self, token: str) -> None:
        if token not in self.sessions or not self.sessions[token].is_active:
            self.sessions[token] = TransferSession(
                token=token,
                bytes_transferred=0,
                start_time=time.time(),
                is_active=True
            )
            ACTIVE_TRANSFERS.inc()
            TRANSFERS_TOTAL.inc()

    def update_transfer(self, token: str, bytes_added: int) -> None:
        if token in self.sessions and self.sessions[token].is_active:
            self.sessions[token].bytes_transferred += bytes_added
            BYTES_TRANSFERRED.inc(bytes_added)

    def end_transfer(self, token: str) -> None:
        if token in self.sessions and self.sessions[token].is_active:
            self.sessions[token].is_active = False
            ACTIVE_TRANSFERS.dec()

class StorageCleaner:
    def __init__(self, buffer_dir: str, retention_seconds: int = 3600):
        self.buffer_dir = Path(buffer_dir)
        self.retention_seconds = retention_seconds
        if not self.buffer_dir.exists():
            self.buffer_dir.mkdir(parents=True, exist_ok=True)

    def clean(self, dry_run: bool = False, json_output: bool = False) -> List[str]:
        pruned_files = []
        now = time.time()
        for filepath in self.buffer_dir.glob('*'):
            if filepath.is_file():
                mtime = filepath.stat().st_mtime
                if now - mtime > self.retention_seconds:
                    if not dry_run:
                        filepath.unlink()
                    pruned_files.append(str(filepath))

        if json_output:
            print(json.dumps({"pruned_files": pruned_files, "dry_run": dry_run}))
        else:
            for f in pruned_files:
                logging.info(f"Pruned: {f} (dry_run={dry_run})")

        return pruned_files

def run_server(args):
    start_http_server(9133)
    cleaner = StorageCleaner(buffer_dir=args.buffer_dir)
    logging.info(f"Starting server on port 9133, monitoring {args.buffer_dir}")
    try:
        while True:
            cleaner.clean(dry_run=args.dry_run, json_output=args.json)
            time.sleep(60)
    except KeyboardInterrupt:
        logging.info("Shutting down...")

def main(args_list=None):
    parser = argparse.ArgumentParser(description="Homelab Encrypted P2P Wormhole Relay & Transit Sentry")
    parser.add_argument('--audit-now', action='store_true', help="Run the audit and cleanup immediately")
    parser.add_argument('--buffer-dir', type=str, default='/tmp/wormhole_staging', help="Path to staging buffer")
    parser.add_argument('--dry-run', action='store_true', help="Do not actually delete files")
    parser.add_argument('--json', action='store_true', help="Output in JSON format")

    args = parser.parse_args(args_list)
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    if args.audit_now:
        cleaner = StorageCleaner(buffer_dir=args.buffer_dir)
        cleaner.clean(dry_run=args.dry_run, json_output=args.json)
    else:
        run_server(args)

if __name__ == "__main__":
    main()
