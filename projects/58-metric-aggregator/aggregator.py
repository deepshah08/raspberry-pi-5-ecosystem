import argparse
import json
import logging
import time
import requests
import yaml
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

EXPORTER_REGISTRY = [
    {
        "job_name": "node_exporter",
        "targets": ["192.168.1.80:9100", "192.168.1.92:9100"]
    },
    {
        "job_name": "smart_sentinel",
        "targets": ["192.168.1.80:9106"]
    },
    {
        "job_name": "llm_gateway",
        "targets": ["192.168.1.80:8000", "192.168.1.92:8000"]
    },
    {
        "job_name": "event_bus",
        "targets": ["192.168.1.92:8088"]
    },
    {
        "job_name": "uptime_kuma",
        "targets": ["192.168.1.80:3001"]
    }
]

def probe_target(target: str) -> bool:
    """Probes /metrics and falls back to /health if needed."""
    for path in ["/metrics", "/health"]:
        url = f"http://{target}{path}"
        try:
            response = requests.get(url, timeout=2.0)
            if response.status_code == 200:
                logger.info(f"Target {target} is healthy at {path}")
                return True
        except requests.RequestException:
            continue
    logger.warning(f"Target {target} is unreachable or unhealthy.")
    return False

def discover_targets():
    active_configs = []
    for job in EXPORTER_REGISTRY:
        active_targets = []
        for target in job["targets"]:
            if probe_target(target):
                active_targets.append(target)

        if active_targets:
            active_configs.append({
                "job_name": job["job_name"],
                "targets": active_targets
            })
    return active_configs

def generate_yaml_config(active_configs, output_path):
    scrape_configs = []
    for config in active_configs:
        scrape_configs.append({
            "job_name": config["job_name"],
            "static_configs": [{"targets": config["targets"]}]
        })

    prom_config = {
        "global": {"scrape_interval": "15s"},
        "scrape_configs": scrape_configs
    }

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(prom_config, f, default_flow_style=False)
    logger.info(f"Generated YAML config at {output_path}")

def generate_json_config(active_configs, output_path):
    # file_sd_configs format expects a list of target groups
    sd_configs = []
    for config in active_configs:
        sd_configs.append({
            "targets": config["targets"],
            "labels": {"job": config["job_name"]}
        })

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(sd_configs, f, indent=2)
    logger.info(f"Generated JSON config at {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Multi-Host Prometheus Exporter Aggregator & Dynamic Discovery")
    parser.add_argument("--output", required=True, help="Path to output config file")
    parser.add_argument("--format", choices=["yaml", "json"], required=True, help="Output format (yaml for prometheus.yml, json for file_sd_configs)")
    parser.add_argument("--dry-run", action="store_true", help="Print configs without writing to file")
    parser.add_argument("--interval", type=int, default=0, help="Run as daemon checking every N seconds")

    args = parser.parse_args()

    def run_cycle():
        logger.info("Starting target discovery...")
        active_configs = discover_targets()

        if args.dry_run:
            logger.info("Dry run mode: Configs discovered:")
            print(json.dumps(active_configs, indent=2))
            return

        if args.format == "yaml":
            generate_yaml_config(active_configs, args.output)
        elif args.format == "json":
            generate_json_config(active_configs, args.output)

    if args.interval > 0:
        logger.info(f"Running as daemon, checking every {args.interval} seconds.")
        while True:
            run_cycle()
            time.sleep(args.interval)
    else:
        run_cycle()

if __name__ == "__main__":
    main()
