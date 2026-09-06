import argparse
import json
import logging
import re
import socket
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prometheus metrics
METRIC_HEALTHY = Gauge(
    'homelab_proxy_upstreams_healthy',
    'Health status of upstream (1 for healthy, 0 for unhealthy)',
    ['host', 'upstream']
)
METRIC_RTT = Gauge(
    'homelab_proxy_upstream_rtt_seconds',
    'Response latency of upstream in seconds',
    ['host', 'upstream']
)
METRIC_SSL_EXPIRY = Gauge(
    'homelab_proxy_upstream_ssl_expiry_days',
    'Days until SSL certificate expiry',
    ['host', 'upstream']
)

from typing import Optional, List, Dict, Any

class UpstreamAuditor:
    def __init__(self, api_url: Optional[str] = None, config_path: Optional[str] = None, is_json: bool = False):
        self.api_url = api_url
        self.config_path = config_path
        self.is_json = is_json

    def get_routes(self) -> List[Dict[str, str]]:
        routes: List[Dict[str, str]] = []
        if self.api_url:
            try:
                resp = requests.get(self.api_url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                routes.extend(self._parse_data(data))
            except Exception as e:
                logger.error(f"Error fetching API {self.api_url}: {e}")
        elif self.config_path:
            try:
                path = Path(self.config_path)
                if path.exists():
                    with path.open() as f:
                        if self.is_json or path.suffix == '.json':
                            data = json.load(f)
                        else:
                            data = yaml.safe_load(f)
                    routes.extend(self._parse_data(data))
                else:
                    logger.error(f"Config path {self.config_path} not found.")
            except Exception as e:
                logger.error(f"Error reading config {self.config_path}: {e}")
        return routes

    def _parse_data(self, data: Any) -> List[Dict[str, str]]:
        routes: List[Dict[str, str]] = []
        if isinstance(data, list):
            for item in data:
                if 'host' in item and 'upstream' in item:
                    routes.append(item)
        elif isinstance(data, dict):
            # Traefik format
            if 'http' in data:
                routers = data['http'].get('routers', {})
                services = data['http'].get('services', {})
                for r_name, router in routers.items():
                    rule = router.get('rule', '')
                    service_name = router.get('service')
                    host = self._extract_host_traefik(rule)

                    if service_name:
                        service_base = service_name.split('@')[0] if '@' in service_name else service_name
                        svc = services.get(service_name) or services.get(service_base)
                        if svc:
                            servers = svc.get('loadBalancer', {}).get('servers', [])
                            for s in servers:
                                if 'url' in s:
                                    routes.append({'host': host, 'upstream': s['url']})
            # Caddy format
            elif 'apps' in data:
                http_apps = data['apps'].get('http', {})
                servers = http_apps.get('servers', {})
                for s_name, server in servers.items():
                    for route in server.get('routes', []):
                        hosts = []
                        for m in route.get('match', []):
                            if 'host' in m:
                                hosts.extend(m['host'])
                        host = hosts[0] if hosts else "unknown"
                        for handle in route.get('handle', []):
                            if handle.get('handler') == 'reverse_proxy':
                                for upstream in handle.get('upstreams', []):
                                    if 'dial' in upstream:
                                        dial = upstream['dial']
                                        url = f"http://{dial}" if not dial.startswith("http") else dial
                                        routes.append({'host': host, 'upstream': url})
        return routes

    def _extract_host_traefik(self, rule: str) -> str:
        match = re.search(r"Host\(`([^`]+)`\)", rule)
        if match:
            return match.group(1)
        return "unknown"

class HealthProber:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def probe(self, route: Dict[str, str]) -> Optional[Dict[str, Any]]:
        host = route.get('host', 'unknown')
        upstream = route.get('upstream')
        if not upstream:
            return None

        start_time = time.time()
        healthy = 0
        status_code = None
        try:
            resp = requests.get(upstream, timeout=self.timeout, verify=False)
            status_code = resp.status_code
            if status_code < 500:
                healthy = 1
        except Exception as e:
            logger.debug(f"Probe failed for {upstream}: {e}")

        rtt = time.time() - start_time

        ssl_days = None
        parsed = urlparse(upstream)
        if parsed.scheme == 'https':
            port = parsed.port or 443
            ssl_days = self.get_ssl_expiry_days(parsed.hostname, port, self.timeout)

        return {
            'host': host,
            'upstream': upstream,
            'healthy': healthy,
            'rtt': rtt,
            'ssl_days': ssl_days,
            'status_code': status_code
        }

    def get_ssl_expiry_days(self, hostname: str, port: int = 443, timeout: float = 5.0) -> int:
        context = ssl.create_default_context()
        try:
            with socket.create_connection((hostname, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    if not cert:
                        return -1
                    not_after = cert.get('notAfter')
                    if not_after:
                        expiry_date = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                        delta = expiry_date - datetime.utcnow()
                        return max(0, delta.days)
        except Exception as e:
            logger.debug(f"SSL check failed for {hostname}: {e}")
            return -1
        return -1


def main() -> None:
    parser = argparse.ArgumentParser(description="Dynamic Traefik / Caddy Reverse Proxy Upstream Sentry")
    parser.add_argument('--audit-now', action='store_true', help="Audit immediately and exit")
    parser.add_argument('--config-path', type=str, help="Path to config file (YAML/JSON)")
    parser.add_argument('--api-url', type=str, help="API URL to fetch configuration")
    parser.add_argument('--dry-run', action='store_true', help="Dry run mode")
    parser.add_argument('--json', action='store_true', help="Treat config as JSON")
    args = parser.parse_args()

    # Avoid verify=False warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    auditor = UpstreamAuditor(api_url=args.api_url, config_path=args.config_path, is_json=args.json)
    prober = HealthProber()

    if not args.dry_run and not args.audit_now:
        logger.info("Starting Prometheus metrics server on port 9119")
        start_http_server(9119)

    def run_audit():
        routes = auditor.get_routes()
        logger.info(f"Found {len(routes)} routes to audit.")
        for route in routes:
            result = prober.probe(route)
            if result:
                logger.info(f"Audit Result: {result}")
                if not args.dry_run:
                    host = result['host']
                    upstream = result['upstream']
                    METRIC_HEALTHY.labels(host=host, upstream=upstream).set(result['healthy'])
                    METRIC_RTT.labels(host=host, upstream=upstream).set(result['rtt'])
                    if result['ssl_days'] is not None:
                        METRIC_SSL_EXPIRY.labels(host=host, upstream=upstream).set(result['ssl_days'])

    if args.audit_now or args.dry_run:
        run_audit()
        sys.exit(0)

    while True:
        run_audit()
        time.sleep(60)

if __name__ == '__main__':
    main()
