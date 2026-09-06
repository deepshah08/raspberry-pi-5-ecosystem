import argparse
import json
import logging
import time
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Optional, Any

import requests
import yaml
from prometheus_client import Gauge, start_http_server

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_DOCKER_ENDPOINTS: List[str] = [
    "http://192.168.1.80:2375",
    "http://192.168.1.92:2375"
]

def discover_services(endpoints: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Query Docker endpoints for running containers and extract their metadata and mapped ports.
    """
    if endpoints is None:
        endpoints = DEFAULT_DOCKER_ENDPOINTS

    services = []

    for endpoint in endpoints:
        try:
            url = f"{endpoint.rstrip('/')}/containers/json"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            containers = response.json()

            for container in containers:
                names = container.get("Names", [])
                name = names[0].lstrip("/") if names else "unknown"
                image = container.get("Image", "unknown")
                state = container.get("State", "unknown")

                # Extract first public port mapped
                url_endpoint = None
                ports = container.get("Ports", [])
                for port in ports:
                    if "PublicPort" in port:
                        host_ip = port.get("IP", "0.0.0.0")
                        # If bound to all interfaces, assume the endpoint's hostname/IP
                        if host_ip == "0.0.0.0":
                            # Parse out IP from endpoint
                            ip = endpoint.split("://")[-1].split(":")[0]
                        else:
                            ip = host_ip
                        url_endpoint = f"http://{ip}:{port['PublicPort']}"
                        break

                services.append({
                    "name": name,
                    "image": image,
                    "state": state,
                    "url": url_endpoint,
                    "node": endpoint
                })
        except requests.RequestException as e:
            logger.warning(f"Failed to query Docker API at {endpoint}: {e}")

    return services


def probe_single_health(service: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ping a single service endpoint to determine its health.
    """
    url = service.get("url")
    if not url:
        service["healthy"] = False
        return service

    try:
        response = requests.get(url, timeout=5)
        service["healthy"] = (200 <= response.status_code < 400)
    except requests.RequestException:
        service["healthy"] = False
    return service

def probe_health(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Concurrently ping discovered endpoints to update their health status.
    """
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(probe_single_health, services))
    return results


def generate_config(services: List[Dict[str, Any]], output_dir: str = ".") -> None:
    """
    Generate services.yaml and widgets.yaml for Homepage dashboard.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Generate services.yaml
    # Homepage expects a list of categories containing services
    services_dict = {"Discovered Services": []}

    for service in services:
        if not service.get("url"):
            continue

        svc_entry = {
            service["name"]: {
                "icon": "docker",
                "href": service["url"],
                "description": f"Image: {service['image']}",
                "ping": service["url"]
            }
        }
        services_dict["Discovered Services"].append(svc_entry)

    services_yaml = [services_dict]

    with open(out_path / "services.yaml", "w") as f:
        yaml.dump(services_yaml, f, default_flow_style=False, sort_keys=False)

    # Generate bookmarks.yaml
    bookmarks_yaml = {
        "bookmarks": [
            {
                "search": {
                    "provider": "duckduckgo",
                    "target": "_blank"
                }
            }
        ]
    }

    with open(out_path / "bookmarks.yaml", "w") as f:
        yaml.dump(bookmarks_yaml, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Generated services.yaml and bookmarks.yaml in {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Homepage Service Discovery & Dashboard Sentry")
    parser.add_argument("--scan-now", action="store_true", help="Run a single discovery scan immediately")
    parser.add_argument("--generate-config", action="store_true", help="Generate services.yaml and widgets.yaml")
    parser.add_argument("--verify-tiles", action="store_true", help="Probe service health and flag unreachable tiles")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing files or exposing metrics")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    return parser.parse_args()

# Prometheus metrics
homelab_homepage_services_total = Gauge(
    'homelab_homepage_services_total',
    'Total number of discovered services'
)
homelab_homepage_healthy_services_ratio = Gauge(
    'homelab_homepage_healthy_services_ratio',
    'Ratio of healthy services to total services'
)


def run_cycle(args: argparse.Namespace) -> None:
    """
    Run one full discovery and health check cycle.
    """
    logger.info("Running discovery scan...")
    services = discover_services()
    logger.info(f"Discovered {len(services)} services.")

    if args.verify_tiles:
        logger.info("Verifying tiles...")
        services = probe_health(services)
        healthy_count = sum(1 for s in services if s.get("healthy"))

        dead_tiles = [s["name"] for s in services if not s.get("healthy")]
        if dead_tiles:
            logger.warning(f"Found {len(dead_tiles)} unreachable tiles: {', '.join(dead_tiles)}")
    else:
        healthy_count = len(services)

    if not args.dry_run:
        homelab_homepage_services_total.set(len(services))
        if len(services) > 0:
            homelab_homepage_healthy_services_ratio.set(healthy_count / len(services))
        else:
            homelab_homepage_healthy_services_ratio.set(1.0)

    if args.generate_config and not args.dry_run:
        generate_config(services)

    if args.json:
        print(json.dumps(services, indent=2))


def main() -> None:
    args = parse_args()
    logger.info("Starting Homepage Sentry...")

    if not args.dry_run and not args.scan_now:
        logger.info("Starting Prometheus metrics server on port 9127")
        start_http_server(9127)

    if args.scan_now or args.dry_run or args.json:
        run_cycle(args)
    else:
        # Defaults for daemon mode if no flags are passed but we want to run continuously
        if not args.generate_config and not args.verify_tiles:
            args.generate_config = True
            args.verify_tiles = True

        # Loop forever
        while True:
            run_cycle(args)
            time.sleep(60)

if __name__ == "__main__":
    main()
