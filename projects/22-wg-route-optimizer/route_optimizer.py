import argparse
import sys
import subprocess
import time
import socket
import json
import random
import logging

from prometheus_client import start_http_server, Gauge, Info

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("route_optimizer")

# Prometheus Metrics
WG_MTU_SIZE = Gauge("homelab_wg_mtu_size", "Optimal MTU size calculated for WireGuard tunnel")
WG_LATENCY_MS = Gauge("homelab_wg_latency_ms", "Average latency (RTT) in milliseconds")
WG_JITTER_MS = Gauge("homelab_wg_jitter_ms", "Average jitter (mdev) in milliseconds")
WG_DNS_LEAK = Gauge("homelab_wg_dns_leak_detected", "DNS leak detected (1) or not (0)")

def probe_mtu(target: str) -> int:
    """
    Probes for the optimal MTU to the target by sending ICMP packets with the DF bit set.
    Returns the maximum MTU size (1280 to 1420) that succeeds.
    """
    if not target:
        logger.error("Target IP required for MTU probing.")
        return 1280

    low = 1280
    high = 1420
    best_mtu = 1280

    while low <= high:
        mid = (low + high) // 2
        payload_size = mid - 28 # Subtract 28 bytes for IP+ICMP headers

        try:
            # -c 1: 1 packet
            # -M do: Don't fragment (Linux)
            # -s size: Payload size
            # -W 1: Timeout 1 second
            result = subprocess.run(
                ["ping", "-c", "1", "-M", "do", "-s", str(payload_size), "-W", "1", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2
            )
            if result.returncode == 0:
                best_mtu = mid
                low = mid + 1
            else:
                high = mid - 1
        except Exception as e:
            logger.debug(f"Ping failed for MTU {mid}: {e}")
            high = mid - 1

    return best_mtu


def measure_latency_and_jitter(target: str) -> tuple[float, float]:
    """
    Measures ping latency (RTT) and jitter to the target.
    Returns (avg_rtt, jitter) in ms, or (-1.0, -1.0) if unreachable.
    """
    if not target:
        return -1.0, -1.0

    try:
        # -c 3: 3 packets
        # -W 1: Timeout 1s
        result = subprocess.run(
            ["ping", "-c", "3", "-W", "1", target],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Parse avg latency from output like: rtt min/avg/max/mdev = 1.0/2.0/3.0/0.1 ms
            lines = result.stdout.strip().split('\n')
            for line in reversed(lines):
                if 'min/avg/max' in line:
                    parts = line.split('=')
                    if len(parts) > 1:
                        stats = parts[1].strip().split()[0]
                        avg = float(stats.split('/')[1])
                        jitter = float(stats.split('/')[3])
                        return avg, jitter
    except Exception as e:
        logger.debug(f"Latency measurement failed: {e}")

    return -1.0, -1.0


def verify_dns_leak() -> bool:
    """
    Verifies that DNS queries are strictly resolving through the local Pi-holes.
    Returns True if a leak is detected (resolving via public DNS), False otherwise.
    Since we can't easily intercept all DNS without privileges, this function
    can simulate the check by ensuring the system resolver doesn't fall back to
    public DNS IPs.
    """
    try:
        # Check /etc/resolv.conf
        with open("/etc/resolv.conf", "r") as f:
            content = f.read()

        nameservers = []
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith("nameserver"):
                parts = line.split()
                if len(parts) > 1:
                    nameservers.append(parts[1])

        allowed_dns = {"192.168.1.80", "192.168.1.92"}
        for ns in nameservers:
            if ns not in allowed_dns:
                logger.warning(f"DNS Leak Detected! Unauthorized nameserver found: {ns}")
                return True

        return False
    except Exception as e:
        logger.error(f"Error checking DNS leak: {e}")
        return True # Default to leaking on error for safety


def parse_args():
    parser = argparse.ArgumentParser(description="Homelab WireGuard Split-Tunnel Route & MTU Optimizer")
    parser.add_argument("--probe-now", action="store_true", help="Force immediate MTU probe and measurement")
    parser.add_argument("--target-peer", type=str, help="Target peer IP for ping/MTU probing")
    parser.add_argument("--dry-run", action="store_true", help="Do not export metrics or enforce changes")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    return parser.parse_args()

def main():
    args = parse_args()

    if args.json:
        mtu = probe_mtu(args.target_peer) if args.target_peer else 1280
        latency, jitter = measure_latency_and_jitter(args.target_peer) if args.target_peer else (-1.0, -1.0)
        leak = verify_dns_leak()
        print(json.dumps({
            "status": "success",
            "mtu": mtu,
            "latency_ms": latency,
            "jitter_ms": jitter,
            "dns_leak": leak
        }))
        return

    logger.info(f"Initialized with args: {args}")

    if not args.dry_run:
        logger.info("Starting Prometheus HTTP server on port 9129")
        start_http_server(9129)

    while True:
        mtu = probe_mtu(args.target_peer) if args.target_peer else 1280
        latency, jitter = measure_latency_and_jitter(args.target_peer) if args.target_peer else (-1.0, -1.0)
        leak = verify_dns_leak()

        if not args.dry_run:
            if args.target_peer:
                WG_MTU_SIZE.set(mtu)
                WG_LATENCY_MS.set(latency)
                WG_JITTER_MS.set(jitter)
            WG_DNS_LEAK.set(1 if leak else 0)

        logger.info(f"Metrics Updated - MTU: {mtu}, Latency: {latency}ms, Jitter: {jitter}ms, DNS Leak: {leak}")

        if args.probe_now:
            break

        time.sleep(60)

if __name__ == "__main__":
    main()
