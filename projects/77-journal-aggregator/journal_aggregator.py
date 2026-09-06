import argparse
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

class JournalParser:
    def __init__(self, file_stream=None):
        self.file_stream = file_stream or sys.stdin

    def parse(self):
        for line in self.file_stream:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

class SeverityClassifier:
    def __init__(self, max_priority: int = 3):
        self.max_priority = max_priority

    def categorize(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        priority_str = entry.get("PRIORITY")
        if priority_str is None:
            return None
        try:
            priority = int(priority_str)
        except ValueError:
            return None

        if priority > self.max_priority:
            return None

        subsystem = entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER") or entry.get("_TRANSPORT") or "unknown"
        
        entry["_CLASSIFIED_PRIORITY"] = priority
        entry["_CLASSIFIED_SUBSYSTEM"] = subsystem
        return entry

class IncidentCorrelator:
    def __init__(self, threshold: int = 10, window: int = 60):
        self.threshold = threshold
        self.window = window
        self.unit_errors: Dict[str, List[int]] = {}

    def process(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        subsystem = entry.get("_CLASSIFIED_SUBSYSTEM", "unknown")
        # Systemd journal REALTIME_TIMESTAMP is in microseconds
        timestamp_str = entry.get("__REALTIME_TIMESTAMP")
        if not timestamp_str:
            import time
            timestamp = int(time.time())
        else:
            try:
                timestamp = int(timestamp_str) // 1000000
            except ValueError:
                import time
                timestamp = int(time.time())
                
        if subsystem not in self.unit_errors:
            self.unit_errors[subsystem] = []
            
        self.unit_errors[subsystem].append(timestamp)
        
        # Keep only errors within the window
        self.unit_errors[subsystem] = [ts for ts in self.unit_errors[subsystem] if timestamp - ts <= self.window]
        
        if len(self.unit_errors[subsystem]) > self.threshold:
            entry["_IS_CASCADE"] = True
            # Clear window to prevent spamming
            self.unit_errors[subsystem] = []
        else:
            entry["_IS_CASCADE"] = False
            
        return entry

class AlertFormatter:
    def format(self, entry: Dict[str, Any]) -> str:
        cascade = " [CASCADE FAILURE]" if entry.get("_IS_CASCADE") else ""
        return f"ALERT{cascade}: [{entry.get('_CLASSIFIED_PRIORITY')}] {entry.get('_CLASSIFIED_SUBSYSTEM')}: {entry.get('MESSAGE')}"

def setup_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-Node Systemd Journal Log Aggregator & Filter")
    parser.add_argument("--input-file", type=str, help="Path to input journal file (JSON lines format)")
    parser.add_argument("--priority", type=int, default=3, help="Maximum priority level to process (0-7). Default is 3 (Err).")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without emitting alerts.")
    parser.add_argument("--json", action="store_true", help="Output in JSON format.")
    return parser

def main():
    parser = setup_argparse()
    args = parser.parse_args()
    
    if args.input_file:
        try:
            f = open(args.input_file, "r")
        except FileNotFoundError:
            print(f"Error: Could not open {args.input_file}", file=sys.stderr)
            sys.exit(1)
        parser = JournalParser(f)
    else:
        parser = JournalParser(sys.stdin)
        
    classifier = SeverityClassifier(max_priority=args.priority)
    correlator = IncidentCorrelator()
    formatter = AlertFormatter()
    
    for entry in parser.parse():
        classified = classifier.categorize(entry)
        if classified:
            correlated = correlator.process(classified)
            
            if args.json:
                print(json.dumps(correlated))
            else:
                alert = formatter.format(correlated)
                if not args.dry_run:
                    print(alert)
                else:
                    print(f"(DRY-RUN) {alert}")

if __name__ == "__main__":
    main()
