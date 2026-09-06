import argparse
import sys
import time
import logging
import subprocess
import re
from typing import Optional, Dict
from prometheus_client import start_http_server, Gauge, Counter

# Prometheus metrics
HOMELAB_WG_PEER_HANDSHAKE_SECONDS = Gauge(
    'homelab_wg_peer_handshake_seconds',
    'Time in seconds since last handshake',
    ['peer_ip']
)
HOMELAB_WG_TUNNEL_HEALTHY = Gauge(
    'homelab_wg_tunnel_healthy',
    'Whether the tunnel is healthy (1) or not (0)',
    ['peer_ip']
)
HOMELAB_WG_FAILOVER_COUNT = Counter(
    'homelab_wg_failover_count',
    'Number of times failover was triggered'
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_wg_peer_stats() -> Dict[str, Dict[str, int]]:
    """
    Runs `wg show all dump` and parses the output.
    Returns a dictionary mapping peer endpoint IPs to their stats (latest handshake age).
    """
    stats = {}
    try:
        result = subprocess.run(
            ['wg', 'show', 'all', 'dump'],
            capture_output=True, text=True, check=True
        )
        current_time = int(time.time())
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('\t')
            # The dump format: interface pubkey preshared_key endpoint allowed_ips latest_handshake transfer_rx transfer_tx persistent_keepalive
            if len(parts) >= 6:
                endpoint = parts[3]
                try:
                    latest_handshake = int(parts[5])
                except ValueError:
                    latest_handshake = 0
                
                if endpoint != '(none)':
                    ip = endpoint.split(':')[0]
                    if latest_handshake > 0:
                        age = current_time - latest_handshake
                    else:
                        age = -1
                    stats[ip] = {'handshake_age': age}
    except Exception as e:
        logging.error(f"Failed to get wg dump: {e}")
    return stats

def check_latency(ip: str, timeout: int = 1) -> float:
    """
    Pings the IP and returns round-trip time in milliseconds.
    Returns -1.0 if ping fails or times out.
    """
    try:
        # ping -c 1 -W <timeout> <ip>
        result = subprocess.run(
            ['ping', '-c', '1', '-W', str(timeout), ip],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            # Extract time=XX ms
            match = re.search(r'time=([\d\.]+)\s*ms', result.stdout)
            if match:
                return float(match.group(1))
    except Exception as e:
        logging.error(f"Failed to ping {ip}: {e}")
    return -1.0


class FailoverController:
    def __init__(self, primary_ip: str, secondary_ip: str, dry_run: bool = False):
        self.primary_ip = primary_ip
        self.secondary_ip = secondary_ip
        self.dry_run = dry_run
        self.active_node = primary_ip

    def failover(self, new_active_ip: str):
        if self.active_node != new_active_ip:
            logging.warning(f"Triggering failover from {self.active_node} to {new_active_ip}")
            HOMELAB_WG_FAILOVER_COUNT.inc()
            self.active_node = new_active_ip
            if not self.dry_run:
                # Update DNS records here (mocked as logging for this project)
                logging.info(f"Executing DNS update: routing traffic to {new_active_ip}")
            else:
                logging.info(f"DRY RUN: Would route traffic to {new_active_ip}")


def parse_args():
    parser = argparse.ArgumentParser(description='WireGuard High-Availability Failover Monitor')
    parser.add_argument('--check-now', action='store_true', help='Run a single check immediately and exit')
    parser.add_argument('--primary-ip', required=True, help='Primary node IP address')
    parser.add_argument('--secondary-ip', required=True, help='Secondary node IP address')
    parser.add_argument('--interval', type=int, default=30, help='Check interval in seconds')
    parser.add_argument('--dry-run', action='store_true', help='Do not actually execute failover actions')
    return parser.parse_args()

def main():
    args = parse_args()
    
    if not args.check_now:
        logging.info("Starting Prometheus metrics server on port 9112")
        start_http_server(9112)
        
    logging.info(f"Monitoring WireGuard tunnels: Primary={args.primary_ip}, Secondary={args.secondary_ip}")

    controller = FailoverController(args.primary_ip, args.secondary_ip, args.dry_run)

    while True:
        stats = get_wg_peer_stats()
        
        primary_handshake = stats.get(args.primary_ip, {}).get('handshake_age', -1)
        secondary_handshake = stats.get(args.secondary_ip, {}).get('handshake_age', -1)
        
        primary_latency = check_latency(args.primary_ip)
        secondary_latency = check_latency(args.secondary_ip)
        
        # update metrics
        HOMELAB_WG_PEER_HANDSHAKE_SECONDS.labels(peer_ip=args.primary_ip).set(primary_handshake)
        HOMELAB_WG_PEER_HANDSHAKE_SECONDS.labels(peer_ip=args.secondary_ip).set(secondary_handshake)
        
        primary_healthy = 1 if (0 <= primary_handshake <= 60 and 0 <= primary_latency <= 50) else 0
        secondary_healthy = 1 if (0 <= secondary_handshake <= 60 and 0 <= secondary_latency <= 50) else 0
        
        HOMELAB_WG_TUNNEL_HEALTHY.labels(peer_ip=args.primary_ip).set(primary_healthy)
        HOMELAB_WG_TUNNEL_HEALTHY.labels(peer_ip=args.secondary_ip).set(secondary_healthy)
        
        logging.info(f"Primary ({args.primary_ip}): Handshake={primary_handshake}s, Latency={primary_latency}ms, Healthy={primary_healthy}")
        logging.info(f"Secondary ({args.secondary_ip}): Handshake={secondary_handshake}s, Latency={secondary_latency}ms, Healthy={secondary_healthy}")

        if primary_healthy == 0 and secondary_healthy == 1:
            controller.failover(args.secondary_ip)
        elif primary_healthy == 1:
            controller.failover(args.primary_ip)
        
        if args.check_now:
            break
        time.sleep(args.interval)

if __name__ == '__main__':
    main()
