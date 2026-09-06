import argparse
import socket
import sys
import time

def measure_latency(host: str, port: int) -> float:
    """
    Measures TCP handshake latency to the target host and port.
    Returns latency in milliseconds, or -1.0 if failed.
    """
    start_time = time.time()
    try:
        with socket.create_connection((host, port), timeout=2.0):
            pass
        end_time = time.time()
        return (end_time - start_time) * 1000.0
    except (socket.timeout, ConnectionRefusedError, OSError):
        return -1.0

def measure_throughput(host: str, port: int, duration: int) -> float:
    """
    Measures TCP throughput to the target host and port by sending dummy data.
    Returns throughput in Mbps, or -1.0 if failed.
    """
    # 64KB chunk
    chunk = b'x' * (64 * 1024)
    bytes_sent = 0
    start_time = time.time()
    end_time = start_time + duration

    try:
        with socket.create_connection((host, port), timeout=2.0) as s:
            # Try to send as much data as possible within the duration
            s.settimeout(0.5)
            while time.time() < end_time:
                try:
                    sent = s.send(chunk)
                    if sent == 0:
                        break
                    bytes_sent += sent
                except socket.timeout:
                    # Timeout during send, continue if within duration
                    continue
                except BlockingIOError:
                    # Non-blocking socket might raise this
                    continue

        actual_duration = time.time() - start_time
        if actual_duration <= 0:
            return 0.0

        # Convert bytes to megabits
        megabits = (bytes_sent * 8) / 1_000_000
        return megabits / actual_duration
    except (socket.timeout, ConnectionRefusedError, OSError):
        return -1.0

def evaluate_link_degraded(throughput_mbps: float, threshold_mbps: float) -> bool:
    """
    Evaluates whether the link is degraded based on throughput and threshold.
    Returns True if throughput > 0 and throughput < threshold.
    """
    if throughput_mbps < 0:
        return True # Consider connection failure as degraded
    return throughput_mbps < threshold_mbps

def parse_args(args=None):
    parser = argparse.ArgumentParser(description="Internal Speedtest Server & Bandwidth Saturation Sentry")

    parser.add_argument("--check-now", action="store_true", help="Run a single check and exit")
    parser.add_argument("--target-host", type=str, required=True, help="Target host IP or hostname")
    parser.add_argument("--port", type=int, default=5201, help="Target port for speedtest (default: 5201)")
    parser.add_argument("--duration", type=int, default=5, help="Burst test duration in seconds (default: 5)")
    parser.add_argument("--threshold-mbps", type=float, default=800.0, help="Degradation threshold in Mbps (default: 800.0)")
    parser.add_argument("--dry-run", action="store_true", help="Print results to stdout without starting Prometheus exporter")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    return parser.parse_args(args)

def run_test(host: str, port: int, duration: int, threshold_mbps: float) -> dict:
    latency_ms = measure_latency(host, port)
    throughput_mbps = measure_throughput(host, port, duration)
    is_degraded = evaluate_link_degraded(throughput_mbps, threshold_mbps)

    return {
        "rtt_ms": latency_ms,
        "bandwidth_mbps": throughput_mbps,
        "link_degraded": is_degraded
    }

def main():
    args = parse_args()

    if args.check_now or args.dry_run:
        result = run_test(args.target_host, args.port, args.duration, args.threshold_mbps)
        if args.json:
            import json
            print(json.dumps(result))
        else:
            print(f"Latency: {result['rtt_ms']:.2f} ms")
            print(f"Throughput: {result['bandwidth_mbps']:.2f} Mbps")
            print(f"Link Degraded: {result['link_degraded']}")
        return

    try:
        from prometheus_client import start_http_server, Gauge
    except ImportError:
        print("Error: prometheus_client library is not installed. Please install it or use --dry-run")
        sys.exit(1)

    gauge_bandwidth = Gauge('homelab_network_bandwidth_mbps', 'Network bandwidth in Mbps')
    gauge_rtt = Gauge('homelab_network_rtt_ms', 'Network round-trip time in milliseconds')
    gauge_degraded = Gauge('homelab_network_link_degraded', '1 if link is degraded, 0 otherwise')

    print("Starting Prometheus exporter on port 9115...")
    start_http_server(9115)

    while True:
        result = run_test(args.target_host, args.port, args.duration, args.threshold_mbps)
        gauge_bandwidth.set(result['bandwidth_mbps'])
        gauge_rtt.set(result['rtt_ms'])
        gauge_degraded.set(1 if result['link_degraded'] else 0)

        # Test every 60 seconds (minus test duration)
        sleep_time = max(0, 60 - args.duration)
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
