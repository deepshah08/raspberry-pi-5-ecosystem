import argparse
import sys
import json
import time
import ntplib
from prometheus_client import start_http_server, Gauge

from typing import List, Dict, Any, Optional

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-Node NTP Clock Drift & PTP Time Synchronizer")
    parser.add_argument("--check-now", action="store_true", help="Perform an immediate check and exit")
    parser.add_argument("--servers", nargs="+", default=["192.168.1.1", "192.168.1.92", "pool.ntp.org"], help="List of NTP servers to query")
    parser.add_argument("--threshold-ms", type=float, default=50.0, help="Clock drift threshold in milliseconds")
    parser.add_argument("--dry-run", action="store_true", help="Perform checks but do not start metrics server or loop")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    return parser.parse_args()

def check_ntp_server(server: str, threshold_ms: float) -> Dict[str, Any]:
    client = ntplib.NTPClient()
    try:
        response = client.request(server, version=3, timeout=5)
        offset = response.offset
        delay = response.delay
        # Calculate drift in ms
        drift_ms = abs(offset * 1000)
        is_warning = drift_ms > threshold_ms
        return {
            "server": server,
            "offset_seconds": offset,
            "delay_seconds": delay,
            "drift_ms": drift_ms,
            "warning": is_warning,
            "error": None
        }
    except Exception as e:
        return {
            "server": server,
            "offset_seconds": None,
            "delay_seconds": None,
            "drift_ms": None,
            "warning": True,  # Treat error as warning state for alerting
            "error": str(e)
        }

def run_checks(servers: List[str], threshold_ms: float, output_json: bool = False) -> List[Dict[str, Any]]:
    results = []
    for server in servers:
        res = check_ntp_server(server, threshold_ms)
        results.append(res)

    if output_json:
        print(json.dumps(results, indent=2))
    else:
        for res in results:
            if res["error"]:
                print(f"Server: {res['server']} | Error: {res['error']}")
            else:
                warn_str = " [WARNING: DRIFT EXCEEDED]" if res["warning"] else ""
                print(f"Server: {res['server']} | Offset: {res['offset_seconds']:.6f}s | Delay: {res['delay_seconds']:.6f}s{warn_str}")
    return results

def main() -> None:
    args = parse_args()

    if args.check_now or args.dry_run:
        run_checks(args.servers, args.threshold_ms, args.json)
        return

    # Define Prometheus Metrics
    offset_gauge = Gauge("homelab_ntp_offset_seconds", "NTP clock offset in seconds", ["server"])
    rtt_gauge = Gauge("homelab_ntp_rtt_seconds", "NTP round trip time (delay) in seconds", ["server"])
    warning_gauge = Gauge("homelab_ntp_drift_warning", "NTP clock drift warning (1 if drift > threshold, 0 otherwise)", ["server"])

    # Start Prometheus HTTP server
    start_http_server(9114)
    if not args.json:
        print("Starting NTP Drift Sentinel on port 9114...")

    while True:
        results = run_checks(args.servers, args.threshold_ms, args.json)
        for res in results:
            server = res["server"]
            if res["error"] is None:
                offset_gauge.labels(server=server).set(res["offset_seconds"])
                rtt_gauge.labels(server=server).set(res["delay_seconds"])
                warning_gauge.labels(server=server).set(1 if res["warning"] else 0)
            else:
                warning_gauge.labels(server=server).set(1)
        time.sleep(15)

if __name__ == "__main__":
    main()
