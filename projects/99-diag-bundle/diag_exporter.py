import argparse
import sys
import subprocess
import json
import urllib.request
import urllib.error
from typing import Dict, Any

def get_docker_health() -> Dict[str, Any]:
    try:
        # Get all containers and their statuses
        result = subprocess.run(
            ['docker', 'ps', '-a', '--format', '{{json .}}'],
            capture_output=True, text=True, check=True
        )
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                container = json.loads(line)
                containers.append({
                    "name": container.get("Names"),
                    "state": container.get("State"),
                    "status": container.get("Status")
                })
        return {"status": "ok", "containers": containers}
    except FileNotFoundError:
        return {"status": "error", "message": "Docker not found or not running"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_pihole_health() -> Dict[str, Any]:
    try:
        # Assuming Pi-hole API is available locally or at a specific IP
        req = urllib.request.Request("http://localhost/admin/api.php?summaryRaw")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return {"status": "ok", "metrics": data}
            return {"status": "error", "message": f"HTTP {response.status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_prometheus_health() -> Dict[str, Any]:
    try:
        # Check Prometheus API status
        req = urllib.request.Request("http://localhost:9090/-/healthy")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return {"status": "ok", "message": "Prometheus is healthy"}
            return {"status": "error", "message": f"HTTP {response.status}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_systemd_health() -> Dict[str, Any]:
    services = ["docker", "containerd", "ssh"]
    health = {}
    for svc in services:
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', svc],
                capture_output=True, text=True
            )
            health[svc] = result.stdout.strip()
        except FileNotFoundError:
             health[svc] = "systemctl not found"
        except Exception as e:
             health[svc] = f"error: {str(e)}"
    return {"status": "ok", "services": health}

def get_storage_health() -> Dict[str, Any]:
    disks = ["/dev/sda", "/dev/sdb"] # Example typical homelab disks, could be parsed from lsblk
    health = {}
    for disk in disks:
        try:
            # Query disk state strictly with smartctl -n standby safe mode to avoid waking sleeping mechanical HDDs
            result = subprocess.run(
                ['smartctl', '-n', 'standby', '-a', disk],
                capture_output=True, text=True
            )
            # If disk is in standby, return code is typically 2 and stdout says "Device is in STANDBY mode"
            if result.returncode == 2 or "STANDBY" in result.stdout.upper():
                health[disk] = {"status": "standby"}
            elif result.returncode == 0:
                # Check for SMART health status
                passed = "SMART overall-health self-assessment test result: PASSED" in result.stdout
                health[disk] = {"status": "active", "smart_passed": passed}
            else:
                 health[disk] = {"status": "error", "message": f"Exit code {result.returncode}"}
        except FileNotFoundError:
             health[disk] = {"status": "error", "message": "smartctl not found"}
        except Exception as e:
             health[disk] = {"status": "error", "message": str(e)}
    return {"status": "ok", "disks": health}

def collect_health_metrics() -> Dict[str, Any]:
    return {
        "docker": get_docker_health(),
        "pihole": get_pihole_health(),
        "prometheus": get_prometheus_health(),
        "systemd": get_systemd_health(),
        "storage": get_storage_health()
    }

import os
import tarfile
import time
import hashlib

def package_bundle(metrics: Dict[str, Any], output_dir: str) -> str:
    timestamp = int(time.time())
    bundle_name = f"diag-{timestamp}"
    tar_filename = os.path.join(output_dir, f"{bundle_name}.tar.gz")
    json_filename = os.path.join(output_dir, f"metrics-{timestamp}.json")

    # Write metrics to a temporary json file
    with open(json_filename, "w") as f:
        json.dump(metrics, f, indent=2)

    # Create tar.gz
    with tarfile.open(tar_filename, "w:gz") as tar:
        tar.add(json_filename, arcname=f"{bundle_name}/metrics.json")

    # Generate SHA-256 manifest
    sha256_hash = hashlib.sha256()
    with open(tar_filename, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    manifest_filename = os.path.join(output_dir, f"{bundle_name}.sha256")
    with open(manifest_filename, "w") as f:
        f.write(f"{sha256_hash.hexdigest()}  {bundle_name}.tar.gz\n")

    # Cleanup json file
    os.remove(json_filename)

    return tar_filename

def parse_args():
    parser = argparse.ArgumentParser(description="Homelab Automated Health Check & Diagnostic Bundle Exporter")
    parser.add_argument("--collect-now", action="store_true", help="Run data collection immediately")
    parser.add_argument("--output-dir", type=str, default="/tmp", help="Output directory for the diagnostic bundle")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without modifying anything")
    parser.add_argument("--json", action="store_true", help="Output collection result as JSON to stdout")
    return parser.parse_args()

def main():
    args = parse_args()
    if args.dry_run:
        print("Running in dry-run mode...")
        metrics = collect_health_metrics()
        print(f"Would package metrics to {args.output_dir}/diag-<timestamp>.tar.gz")
        return

    if args.collect_now or args.json:
        metrics = collect_health_metrics()
        if args.json:
            print(json.dumps(metrics, indent=2))
        if args.collect_now:
            if not os.path.exists(args.output_dir):
                os.makedirs(args.output_dir, exist_ok=True)
            tar_path = package_bundle(metrics, args.output_dir)
            print(f"Diagnostic bundle created at: {tar_path}")

if __name__ == "__main__":
    main()
