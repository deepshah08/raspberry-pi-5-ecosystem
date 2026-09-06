import argparse
import yaml
import sys
import json
import logging
import subprocess
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config(config_path):
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logging.error(f"Failed to load config from {config_path}: {e}")
        sys.exit(1)

def run_command(cmd, dry_run=False, cwd=None, env=None):
    if dry_run:
        logging.info(f"[DRY RUN] Executing: {' '.join(cmd)}")
        return 0

    try:
        result = subprocess.run(cmd, check=True, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(cmd)}\nError: {e.stderr}")
        return e.returncode
    except Exception as e:
        logging.error(f"Execution error: {e}")
        return 1

def check_health(url, timeout):
    if not url:
        return True # No healthcheck required

    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code in (200, 204):
            return True
        return False
    except Exception:
        return False

def wait_for_tier_health(tier_services, timeout):
    start_time = time.time()
    pending = {name: srv for name, srv in tier_services.items() if srv.get('healthcheck')}

    while pending and (time.time() - start_time) < timeout:
        healthy = []
        for name, srv in pending.items():
            if check_health(srv['healthcheck'], timeout=5):
                healthy.append(name)

        for name in healthy:
            del pending[name]

        if pending:
            time.sleep(2)

    if pending:
        logging.error(f"Healthcheck timeout for services: {', '.join(pending.keys())}")
        return False
    return True

def up(args, config):
    logging.info("Starting 'up' sequence...")
    tiers = config.get('tiers', {})

    tier_keys = sorted(tiers.keys())
    if args.tier:
        if args.tier not in tiers:
            logging.error(f"Tier {args.tier} not found in configuration.")
            sys.exit(1)
        tier_keys = [args.tier]

    for t in tier_keys:
        tier_data = tiers[t]
        logging.info(f"--- Starting Tier {t}: {tier_data.get('name', 'Unknown')} ---")

        services = tier_data.get('services', {})

        # Start all services in the tier
        for srv_name, srv_config in services.items():
            logging.info(f"Starting {srv_name}...")
            host = srv_config.get('host')
            compose_dir = srv_config.get('compose_dir')

            # Use ssh for remote execution or docker directly if local, assume ssh is safer for multi-host
            cmd = ["ssh", host, f"cd {compose_dir} && docker compose up -d"]

            run_command(cmd, dry_run=args.dry_run)

        # Wait for healthchecks
        if not args.dry_run:
            logging.info(f"Waiting for Tier {t} healthchecks (timeout {args.timeout}s)...")
            if not wait_for_tier_health(services, args.timeout):
                logging.error(f"Tier {t} failed to become healthy. Halting 'up' sequence.")
                sys.exit(1)
            logging.info(f"Tier {t} is healthy.")
        else:
            logging.info(f"[DRY RUN] Skipping healthcheck wait for Tier {t}.")

def down(args, config):
    logging.info("Starting 'down' sequence...")
    tiers = config.get('tiers', {})

    tier_keys = sorted(tiers.keys(), reverse=True)
    if args.tier:
        if args.tier not in tiers:
            logging.error(f"Tier {args.tier} not found in configuration.")
            sys.exit(1)
        tier_keys = [args.tier]

    for t in tier_keys:
        tier_data = tiers[t]
        logging.info(f"--- Stopping Tier {t}: {tier_data.get('name', 'Unknown')} ---")

        services = tier_data.get('services', {})

        for srv_name, srv_config in services.items():
            logging.info(f"Stopping {srv_name}...")
            host = srv_config.get('host')
            compose_dir = srv_config.get('compose_dir')
            grace = srv_config.get('grace_period', 10)

            # Sync filesystem before stop
            sync_cmd = ["ssh", host, "sync"]
            run_command(sync_cmd, dry_run=args.dry_run)

            stop_cmd = ["ssh", host, f"cd {compose_dir} && docker compose down -t {grace}"]
            run_command(stop_cmd, dry_run=args.dry_run)

def health(args, config):
    logging.info("Starting health check...")
    tiers = config.get('tiers', {})

    results = {}

    def check_service(name, srv):
        url = srv.get('healthcheck')
        if not url:
            return name, True
        return name, check_health(url, timeout=args.timeout)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}
        for t, tier_data in tiers.items():
            for srv_name, srv_config in tier_data.get('services', {}).items():
                futures[executor.submit(check_service, srv_name, srv_config)] = (t, srv_name)

        for future in as_completed(futures):
            t, srv_name = futures[future]
            if t not in results:
                results[t] = {}
            try:
                _, is_healthy = future.result()
                results[t][srv_name] = is_healthy
            except Exception as e:
                results[t][srv_name] = False

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for t in sorted(results.keys()):
            print(f"Tier {t}:")
            for srv_name, is_healthy in results[t].items():
                status = "HEALTHY" if is_healthy else "UNHEALTHY"
                print(f"  {srv_name}: {status}")

def main():
    parser = argparse.ArgumentParser(description="Multi-Service Cluster Orchestrator")
    parser.add_argument('--config', default='projects/51-cluster-orchestrator/cluster_config.yml', help='Path to cluster configuration file')
    parser.add_argument('--dry-run', action='store_true', help='Simulate operations without executing them')
    parser.add_argument('--timeout', type=int, default=60, help='Timeout for healthchecks (seconds)')

    subparsers = parser.add_subparsers(dest='command', required=True, help='Orchestrator commands')

    # UP command
    up_parser = subparsers.add_parser('up', help='Starts services in strict dependency order')
    up_parser.add_argument('--tier', type=int, choices=[1, 2, 3, 4], help='Target specific tier to bring up')

    # DOWN command
    down_parser = subparsers.add_parser('down', help='Gracefully drains and stops services in reverse order')
    down_parser.add_argument('--tier', type=int, choices=[1, 2, 3, 4], help='Target specific tier to bring down')

    # HEALTH command
    health_parser = subparsers.add_parser('health', help='Parallel status verification across all cluster endpoints')
    health_parser.add_argument('--json', action='store_true', help='Output in JSON format')

    args = parser.parse_args()

    config = load_config(args.config)

    if args.command == 'up':
        up(args, config)
    elif args.command == 'down':
        down(args, config)
    elif args.command == 'health':
        health(args, config)

if __name__ == "__main__":
    main()
