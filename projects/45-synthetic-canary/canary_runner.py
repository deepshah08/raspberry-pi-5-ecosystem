import argparse
import asyncio
import logging
import os
import time

import dns.asyncresolver
import httpx
from prometheus_client import start_http_server, Gauge, Counter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Metrics
PROBE_DURATION = Gauge('canary_probe_duration_seconds', 'Duration of probe in seconds', ['target', 'type'])
PROBE_SUCCESS = Gauge('canary_probe_success', 'Success status of probe (1=success, 0=failure)', ['target', 'type'])
SLO_VIOLATION = Counter('canary_slo_violation_count', 'Count of SLO violations', ['target', 'type'])

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

DNS_TARGETS = [
    {"name": "Pi-hole 1", "ip": "192.168.1.80", "slo_ms": 500, "domain": "google.com"},
    {"name": "Pi-hole 2", "ip": "192.168.1.92", "slo_ms": 500, "domain": "google.com"},
]

HTTP_TARGETS = [
    {"name": "OmniSearch", "url": "http://localhost:8008", "slo_ms": 1000}, # Use 1000ms for alert based on requirements (">1000ms for HTTP"). The 200ms target latency is for tracking but alert threshold is 1000ms. Wait, requirements say "if latency exceeds SLO thresholds (>500ms for DNS or >1000ms for HTTP) or consecutive failures occur."
    {"name": "SearXNG", "url": "http://localhost:8888", "slo_ms": 1000},
    {"name": "Audiobookshelf", "url": "http://localhost:13378", "slo_ms": 1000},
    {"name": "Uptime Kuma", "url": "http://localhost:3001", "slo_ms": 1000},
    {"name": "Unified Dashboard", "url": "http://localhost:3030", "slo_ms": 1000},
]

# Track consecutive failures
failure_counts = {}

async def send_telegram_alert(message: str, dry_run: bool = False):
    if dry_run:
        logger.info(f"[DRY RUN] Telegram Alert: {message}")
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set. Skipping alert.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🚨 *SLO Violation / Canary Alert* 🚨\n{message}",
        "parse_mode": "Markdown"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, timeout=10.0)
            resp.raise_for_status()
            logger.info(f"Sent Telegram alert: {message}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

async def probe_dns(target, dry_run: bool):
    target_name = target['name']
    ip = target['ip']
    domain = target['domain']
    alert_threshold_ms = 500

    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = [ip]
    resolver.timeout = 2.0
    resolver.lifetime = 2.0

    start_time = time.time()
    success = False
    duration = 0.0

    try:
        await resolver.resolve(domain, 'A')
        duration = time.time() - start_time
        success = True
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"DNS probe failed for {target_name} ({ip}): {e}")

    PROBE_DURATION.labels(target=target_name, type='dns').set(duration)
    PROBE_SUCCESS.labels(target=target_name, type='dns').set(1 if success else 0)

    duration_ms = duration * 1000

    if not success:
        failure_counts[target_name] = failure_counts.get(target_name, 0) + 1
        SLO_VIOLATION.labels(target=target_name, type='dns').inc()
        if failure_counts[target_name] >= 2: # consecutive failures
             await send_telegram_alert(f"DNS resolution failed for {target_name} ({ip}) 2+ times consecutively.", dry_run)
             failure_counts[target_name] = 0 # reset after alerting
    else:
        failure_counts[target_name] = 0
        if duration_ms > alert_threshold_ms:
            SLO_VIOLATION.labels(target=target_name, type='dns').inc()
            await send_telegram_alert(f"DNS latency SLO breached for {target_name} ({ip}). Latency: {duration_ms:.2f}ms (Threshold: {alert_threshold_ms}ms).", dry_run)

    logger.info(f"DNS {target_name}: success={success}, duration={duration_ms:.2f}ms")

async def probe_http(target, dry_run: bool):
    target_name = target['name']
    url = target['url']
    alert_threshold_ms = 1000

    start_time = time.time()
    success = False
    duration = 0.0

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=5.0)
            resp.raise_for_status()
            duration = time.time() - start_time
            success = True
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"HTTP probe failed for {target_name} ({url}): {e}")

    PROBE_DURATION.labels(target=target_name, type='http').set(duration)
    PROBE_SUCCESS.labels(target=target_name, type='http').set(1 if success else 0)

    duration_ms = duration * 1000

    if not success:
        failure_counts[target_name] = failure_counts.get(target_name, 0) + 1
        SLO_VIOLATION.labels(target=target_name, type='http').inc()
        if failure_counts[target_name] >= 2:
            await send_telegram_alert(f"HTTP probe failed for {target_name} ({url}) 2+ times consecutively.", dry_run)
            failure_counts[target_name] = 0
    else:
        failure_counts[target_name] = 0
        if duration_ms > alert_threshold_ms:
            SLO_VIOLATION.labels(target=target_name, type='http').inc()
            await send_telegram_alert(f"HTTP latency SLO breached for {target_name} ({url}). Latency: {duration_ms:.2f}ms (Threshold: {alert_threshold_ms}ms).", dry_run)

    logger.info(f"HTTP {target_name}: success={success}, duration={duration_ms:.2f}ms")

async def run_probes(dry_run: bool):
    logger.info("Starting probe round...")
    tasks = []
    for target in DNS_TARGETS:
        tasks.append(probe_dns(target, dry_run))
    for target in HTTP_TARGETS:
        tasks.append(probe_http(target, dry_run))

    await asyncio.gather(*tasks)
    logger.info("Probe round complete.")

async def main():
    parser = argparse.ArgumentParser(description="Homelab End-to-End Synthetic Canaries & SLO Monitor")
    parser.add_argument("--interval", type=int, default=60, help="Interval between probe runs in seconds")
    parser.add_argument("--single-run", action="store_true", help="Run once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not send actual Telegram alerts")

    args = parser.parse_args()

    if not args.single_run:
        start_http_server(9115)
        logger.info("Prometheus metrics server started on port 9115")

    while True:
        await run_probes(args.dry_run)

        if args.single_run:
            break

        await asyncio.sleep(args.interval)

if __name__ == "__main__":
    asyncio.run(main())
