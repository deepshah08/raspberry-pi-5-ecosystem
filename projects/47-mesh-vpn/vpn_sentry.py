import argparse
import logging
import os
import subprocess
import time
import re
import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ALLOWED_DNS_NODES = ["192.168.1.80", "192.168.1.92"]

def send_telegram_alert(message: str, dry_run: bool = False):
    if dry_run:
        logger.info(f"[DRY RUN] Telegram Alert: {message}")
        return True

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram credentials not set. Skipping alert.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": f"🚨 *VPN Sentry Alert* 🚨\n{message}",
        "parse_mode": "Markdown"
    }

    try:
        resp = httpx.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        logger.info(f"Sent Telegram alert: {message}")
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False

def check_handshakes(interface: str) -> dict:
    """
    Checks the latest handshakes for the given WireGuard interface.
    Alerts if any handshake is older than 3 minutes (180 seconds).
    Returns a dict mapping peer pubkey to (is_healthy, time_since_handshake).
    """
    try:
        output = subprocess.check_output(['wg', 'show', interface, 'latest-handshakes'], stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to run wg show: {e.output}")
        return {}
    except FileNotFoundError:
        logger.error("wg command not found. Ensure WireGuard is installed.")
        return {}

    current_time = time.time()
    results = {}
    for line in output.strip().split('\n'):
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 2:
            peer = parts[0]
            timestamp = int(parts[1])
            if timestamp == 0:
                logger.warning(f"Peer {peer} has no handshake.")
                results[peer] = (False, -1)
                continue

            time_since = current_time - timestamp
            is_healthy = time_since <= 180
            results[peer] = (is_healthy, time_since)

            if not is_healthy:
                logger.warning(f"Peer {peer} handshake is stale: {time_since:.1f}s ago")
            else:
                logger.info(f"Peer {peer} handshake is healthy: {time_since:.1f}s ago")

    return results

def check_dns_leaks() -> bool:
    """
    Validates that /etc/resolv.conf only contains permitted local DNS nodes.
    Alerts if public DNS servers or non-permitted servers are found.
    Returns True if no leaks detected, False otherwise.
    """
    try:
        with open("/etc/resolv.conf", "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        logger.error("/etc/resolv.conf not found.")
        return False

    nameservers = []
    for line in lines:
        line = line.strip()
        if line.startswith("nameserver "):
            parts = line.split()
            if len(parts) >= 2:
                nameservers.append(parts[1])

    if not nameservers:
        logger.warning("No nameservers found in /etc/resolv.conf.")
        return False

    has_leak = False
    for ns in nameservers:
        if ns not in ALLOWED_DNS_NODES:
            logger.error(f"DNS Leak Detected! Unauthorized nameserver: {ns}")
            has_leak = True

    if has_leak:
        return False

    logger.info("DNS Leak Check Passed: Only local ad-blocking nodes in use.")
    return True

def check_latency_throughput(ip_address: str) -> dict:
    """
    Measures latency and packet loss to a peer using ping.
    Returns a dict with 'rtt_avg' (ms) and 'packet_loss' (percentage).
    """
    try:
        # Send 4 pings, wait max 1 sec for response per packet
        output = subprocess.check_output(
            ['ping', '-c', '4', '-W', '1', ip_address],
            stderr=subprocess.STDOUT,
            text=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Ping failed to {ip_address}:\n{e.output}")
        # Even if it fails, some output might be parsable for packet loss
        output = e.output
    except FileNotFoundError:
         logger.error("ping command not found.")
         return {'rtt_avg': -1.0, 'packet_loss': 100.0}

    # Parse packet loss
    # e.g., "4 packets transmitted, 4 received, 0% packet loss, time 3004ms"
    loss_match = re.search(r'(\d+)%\s+packet\s+loss', output)
    packet_loss = float(loss_match.group(1)) if loss_match else 100.0

    # Parse rtt
    # e.g., "rtt min/avg/max/mdev = 0.285/0.380/0.468/0.068 ms"
    rtt_match = re.search(r'rtt min/avg/max/mdev = [\d\.]+/(?P<avg>[\d\.]+)/[\d\.]+/', output)
    if not rtt_match:
        # Try alternate ping format (macOS)
        # e.g. "round-trip min/avg/max/stddev = 0.198/0.320/0.465/0.098 ms"
        rtt_match = re.search(r'round-trip min/avg/max/(?:mdev|stddev) = [\d\.]+/(?P<avg>[\d\.]+)/[\d\.]+/', output)

    rtt_avg = float(rtt_match.group('avg')) if rtt_match else -1.0

    logger.info(f"Ping {ip_address}: loss={packet_loss}%, avg_rtt={rtt_avg}ms")
    return {'rtt_avg': rtt_avg, 'packet_loss': packet_loss}

def main():
    parser = argparse.ArgumentParser(description="Homelab Mesh VPN & WireGuard Sentry")
    parser.add_argument("--interface", type=str, default="wg0", help="WireGuard interface to monitor")
    parser.add_argument("--check-dns-leaks", action="store_true", help="Perform DNS leak validation")
    parser.add_argument("--dry-run", action="store_true", help="Do not send actual Telegram alerts")
    parser.add_argument("--check-peer", type=str, action='append', help="Peer IP to check latency/loss")

    args = parser.parse_args()

    issues_found = []

    # 1. Check DNS Leaks
    if args.check_dns_leaks:
        if not check_dns_leaks():
            issues_found.append("DNS Leak Detected: Unauthorized upstreams in /etc/resolv.conf!")

    # 2. Check Handshakes
    results = check_handshakes(args.interface)
    for peer, (is_healthy, time_since) in results.items():
        if not is_healthy:
            if time_since == -1:
                issues_found.append(f"WireGuard Peer {peer} has no handshake.")
            else:
                issues_found.append(f"WireGuard Peer {peer} handshake is stale ({time_since:.1f}s ago).")

    # 3. Check Latency
    if args.check_peer:
        for ip in args.check_peer:
            stats = check_latency_throughput(ip)
            if stats['packet_loss'] >= 50.0:
                 issues_found.append(f"High packet loss ({stats['packet_loss']}%) to peer {ip}.")

    # 4. Alerting
    if issues_found:
        message = "\n".join(f"- {msg}" for msg in issues_found)
        logger.warning(f"Issues detected:\n{message}")
        send_telegram_alert(message, args.dry_run)
    else:
        logger.info("All checks passed. Mesh VPN is healthy.")

if __name__ == "__main__":
    main()
