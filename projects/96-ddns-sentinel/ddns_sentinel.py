import argparse
import logging
import requests
import sys
import time
import json
import os
from prometheus_client import start_http_server, Counter, Gauge
import dns.resolver

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prometheus metrics
homelab_ddns_ip_changed_total = Counter('homelab_ddns_ip_changed_total', 'Total number of times the public IP has changed')
homelab_ddns_sync_success = Counter('homelab_ddns_sync_success', 'Total number of successful DNS record synchronizations')
homelab_ddns_propagation_verified = Gauge('homelab_ddns_propagation_verified', 'Whether the global DNS resolution matches the current IP (1 = verified, 0 = failed)')
homelab_ddns_current_ip = Gauge('homelab_ddns_current_ip', 'Current detected public IP encoded in labels', ['ip'])

def get_args():
    parser = argparse.ArgumentParser(description="Automated Homelab Dynamic DNS Sentinel")
    parser.add_argument("--check-now", action="store_true", help="Run once and exit immediately")
    parser.add_argument("--zone-id", help="Cloudflare Zone ID")
    parser.add_argument("--domain", help="Domain to update (e.g., test.example.com)")
    parser.add_argument("--dry-run", action="store_true", help="Do not make any changes")
    parser.add_argument("--json", action="store_true", help="Output JSON logs")
    return parser.parse_args()

class WANIPDetector:
    def __init__(self) -> None:
        # Using reliable endpoints for IP discovery
        self.ipv4_endpoints = [
            "https://api.ipify.org",
            "https://ifconfig.me/ip",
            "https://ipv4.icanhazip.com"
        ]
        self.ipv6_endpoints = [
            "https://api64.ipify.org",
            "https://ipv6.icanhazip.com"
        ]

    def get_public_ip(self, ip_version: int = 4) -> str | None:
        endpoints = self.ipv4_endpoints if ip_version == 4 else self.ipv6_endpoints
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=5)
                response.raise_for_status()
                ip = response.text.strip()
                if ip:
                    logger.info(f"Detected public IPv{ip_version} {ip} via {endpoint}")
                    return ip
            except requests.RequestException as e:
                logger.warning(f"Failed to detect IPv{ip_version} via {endpoint}: {e}")

        logger.warning(f"All redundant IPv{ip_version} endpoints failed.")
        return None

class CloudflareClient:
    def __init__(self, api_token: str, zone_id: str) -> None:
        self.api_token = api_token
        self.zone_id = zone_id
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

    def get_record(self, domain: str, record_type: str = "A") -> dict | None:
        url = f"{self.base_url}/zones/{self.zone_id}/dns_records?name={domain}&type={record_type}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("result"):
                return data["result"][0]
            return None
        except requests.RequestException as e:
            logger.error(f"Error fetching Cloudflare record for {domain}: {e}")
            return None

    def update_record(self, record_id: str, domain: str, new_ip: str, record_type: str = "A") -> bool:
        url = f"{self.base_url}/zones/{self.zone_id}/dns_records/{record_id}"
        payload = {
            "type": record_type,
            "name": domain,
            "content": new_ip,
            "ttl": 120,
            "proxied": False
        }
        try:
            response = requests.patch(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                logger.info(f"Successfully updated {domain} to {new_ip} on Cloudflare")
                return True
            else:
                logger.error(f"Cloudflare update failed: {data.get('errors')}")
                return False
        except requests.RequestException as e:
            logger.error(f"Error updating Cloudflare record for {domain}: {e}")
            return False

class DuckDNSClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def update_record(self, domain: str, new_ip: str, is_ipv6: bool = False) -> bool:
        # domain here can just be the duckdns subdomain
        if domain.endswith(".duckdns.org"):
            domain = domain.replace(".duckdns.org", "")

        ip_param = f"ipv6={new_ip}" if is_ipv6 else f"ip={new_ip}"
        url = f"https://www.duckdns.org/update?domains={domain}&token={self.token}&{ip_param}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            if response.text.strip() == "OK":
                logger.info(f"Successfully updated {domain}.duckdns.org to {new_ip} on DuckDNS")
                return True
            else:
                logger.error(f"DuckDNS update failed. Response: {response.text}")
                return False
        except requests.RequestException as e:
            logger.error(f"Error updating DuckDNS for {domain}: {e}")
            return False

class ResolutionVerifier:
    def __init__(self) -> None:
        self.resolvers = ["1.1.1.1", "8.8.8.8"]

    def verify(self, domain: str, expected_ip: str, record_type: str = "A") -> bool:
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = self.resolvers
        try:
            answers = resolver.resolve(domain, record_type)
            for rdata in answers:
                if rdata.address == expected_ip:
                    logger.info(f"Verified {domain} resolves to {expected_ip}")
                    return True
            logger.warning(f"{domain} resolved but did not match {expected_ip}")
            return False
        except Exception as e:
            logger.warning(f"Failed to verify resolution for {domain}: {e}")
            return False

def sync_loop(args: argparse.Namespace) -> None:
    detector = WANIPDetector()
    last_ipv4 = None
    last_ipv6 = None
    verifier = ResolutionVerifier()

    while True:
        current_ipv4 = detector.get_public_ip(ip_version=4)
        current_ipv6 = detector.get_public_ip(ip_version=6)

        if not current_ipv4 and not current_ipv6:
            logger.error("Could not determine public IPv4 or IPv6. Retrying later.")
        else:
            # Update Prometheus
            if current_ipv4:
                homelab_ddns_current_ip.labels(ip=current_ipv4).set(1)
            if current_ipv6:
                homelab_ddns_current_ip.labels(ip=current_ipv6).set(1)

            ip_changed = False

            if current_ipv4 and current_ipv4 != last_ipv4:
                if last_ipv4 is not None:
                    logger.info(f"IPv4 change detected: {last_ipv4} -> {current_ipv4}")
                    homelab_ddns_ip_changed_total.inc()
                else:
                    logger.info(f"Initial IPv4 detection: {current_ipv4}")
                last_ipv4 = current_ipv4
                ip_changed = True

            if current_ipv6 and current_ipv6 != last_ipv6:
                if last_ipv6 is not None:
                    logger.info(f"IPv6 change detected: {last_ipv6} -> {current_ipv6}")
                    homelab_ddns_ip_changed_total.inc()
                else:
                    logger.info(f"Initial IPv6 detection: {current_ipv6}")
                last_ipv6 = current_ipv6
                ip_changed = True

            if args.dry_run:
                if ip_changed:
                    logger.info("Dry run enabled. Skipping DNS updates.")
            elif args.domain:
                domain = args.domain
                success = False

                # Process updates
                cf_token = os.environ.get("CLOUDFLARE_API_TOKEN")
                duckdns_token = os.environ.get("DUCKDNS_TOKEN")

                if cf_token and args.zone_id:
                    cf_client = CloudflareClient(cf_token, args.zone_id)

                    if current_ipv4:
                        record_a = cf_client.get_record(domain, record_type="A")
                        if record_a:
                            if record_a.get("content") == current_ipv4:
                                logger.info(f"Cloudflare A record for {domain} already matches {current_ipv4}")
                                success = True
                            else:
                                success = cf_client.update_record(record_a.get("id"), domain, current_ipv4, record_type="A")
                        else:
                            logger.warning(f"Could not find existing Cloudflare A record for {domain}")

                    if current_ipv6:
                        record_aaaa = cf_client.get_record(domain, record_type="AAAA")
                        if record_aaaa:
                            if record_aaaa.get("content") == current_ipv6:
                                logger.info(f"Cloudflare AAAA record for {domain} already matches {current_ipv6}")
                                success = True
                            else:
                                success = cf_client.update_record(record_aaaa.get("id"), domain, current_ipv6, record_type="AAAA")
                        else:
                            logger.warning(f"Could not find existing Cloudflare AAAA record for {domain}")

                if duckdns_token and domain.endswith(".duckdns.org"):
                    duck_client = DuckDNSClient(duckdns_token)
                    if current_ipv4:
                        success = duck_client.update_record(domain, current_ipv4, is_ipv6=False) or success
                    if current_ipv6:
                        success = duck_client.update_record(domain, current_ipv6, is_ipv6=True) or success

                if success:
                    # We might recount success per loop iteration if it's already matching,
                    # but only if ip_changed is True we should log the true event.
                    # To align with behavior:
                    if ip_changed:
                        homelab_ddns_sync_success.inc()

                    # Verify propagation
                    prop_v4_success = not current_ipv4 or verifier.verify(domain, current_ipv4, record_type="A")
                    prop_v6_success = not current_ipv6 or verifier.verify(domain, current_ipv6, record_type="AAAA")

                    if prop_v4_success and prop_v6_success:
                        homelab_ddns_propagation_verified.set(1)
                    else:
                        homelab_ddns_propagation_verified.set(0)
                else:
                    # No updates were successful or needed, verify anyway
                    if current_ipv4 or current_ipv6:
                        prop_v4_success = not current_ipv4 or verifier.verify(domain, current_ipv4, record_type="A")
                        prop_v6_success = not current_ipv6 or verifier.verify(domain, current_ipv6, record_type="AAAA")
                        if prop_v4_success and prop_v6_success:
                            homelab_ddns_propagation_verified.set(1)
                        else:
                            homelab_ddns_propagation_verified.set(0)

        if args.check_now:
            break

        # Sleep for 5 minutes before checking again
        time.sleep(300)

def main():
    args = get_args()

    if args.json:
        # Reconfigure logger for JSON
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                log_record = {
                    "time": self.formatTime(record, self.datefmt),
                    "level": record.levelname,
                    "message": record.getMessage()
                }
                return json.dumps(log_record)

        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        json_handler = logging.StreamHandler()
        json_handler.setFormatter(JsonFormatter())
        logging.root.addHandler(json_handler)

    if not args.check_now:
        # Start Prometheus exporter only if we're running as a daemon
        start_http_server(9121)
        logger.info("Prometheus metrics exporter started on port 9121")

    sync_loop(args)

if __name__ == "__main__":
    main()
