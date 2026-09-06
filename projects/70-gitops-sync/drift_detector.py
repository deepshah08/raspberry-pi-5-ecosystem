import argparse
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

try:
    import docker
except ImportError:
    docker = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("drift-detector")


class ComposeParser:
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)

    def parse(self) -> Dict[str, Any]:
        """Parses docker-compose.yml files in the repo root to extract service definitions."""
        expected_state = {}
        for compose_file in self.repo_root.rglob("docker-compose.yml"):
            try:
                with open(compose_file, "r") as f:
                    compose_data = yaml.safe_load(f)
                    if not compose_data or "services" not in compose_data:
                        continue
                    
                    for service_name, service_config in compose_data["services"].items():
                        expected_state[service_name] = {
                            "image": service_config.get("image"),
                            "ports": self._parse_ports(service_config.get("ports", [])),
                            "volumes": self._parse_volumes(service_config.get("volumes", [])),
                            "environment": self._parse_environment(service_config.get("environment", {})),
                        }
            except Exception as e:
                logger.warning(f"Failed to parse {compose_file}: {e}")
                
        return expected_state

    def _parse_ports(self, ports: List[Any]) -> List[str]:
        # Simplify to string representation for comparison
        parsed = []
        for p in ports:
            if isinstance(p, dict):
                published = p.get("published")
                target = p.get("target")
                if published and target:
                    parsed.append(f"{published}:{target}")
            else:
                parsed.append(str(p))
        return sorted(parsed)

    def _parse_volumes(self, volumes: List[Any]) -> List[str]:
        parsed = []
        for v in volumes:
            if isinstance(v, dict):
                source = v.get("source")
                target = v.get("target")
                if source and target:
                    parsed.append(f"{source}:{target}")
            else:
                # Basic string format handling
                parts = str(v).split(':')
                if len(parts) >= 2:
                     parsed.append(f"{parts[0]}:{parts[1]}")
                else:
                    parsed.append(str(v))
        return sorted(parsed)

    def _parse_environment(self, env: Any) -> Dict[str, str]:
        if isinstance(env, dict):
            return {k: str(v) for k, v in env.items() if v is not None}
        elif isinstance(env, list):
            parsed = {}
            for e in env:
                if "=" in e:
                    k, v = e.split("=", 1)
                    parsed[k] = v
                else:
                    parsed[e] = ""
            return parsed
        return {}


class RuntimeInspector:
    def __init__(self, mock_client=None):
        if mock_client:
             self.client = mock_client
        elif docker:
            try:
                self.client = docker.from_env()
            except Exception as e:
                logger.error(f"Failed to initialize Docker client: {e}")
                self.client = None
        else:
             self.client = None
             logger.warning("Docker module not found and no mock client provided.")

    def get_running_state(self) -> Dict[str, Any]:
        """Fetches runtime states of containers via the Docker SDK."""
        if not self.client:
             return {}
        
        actual_state = {}
        try:
            containers = self.client.containers.list()
            for container in containers:
                # Docker Compose sets 'com.docker.compose.service' label
                service_name = container.labels.get("com.docker.compose.service", container.name)
                
                # Image
                image = container.image.tags[0] if container.image.tags else container.attrs['Config']['Image']
                
                # Ports
                ports = []
                port_bindings = container.attrs.get("HostConfig", {}).get("PortBindings", {})
                for container_port, host_bindings in port_bindings.items():
                    if host_bindings:
                        for binding in host_bindings:
                            host_port = binding.get("HostPort")
                            if host_port:
                                # Clean up container_port, usually like "80/tcp"
                                cp = container_port.split('/')[0]
                                ports.append(f"{host_port}:{cp}")
                ports = sorted(ports)

                # Volumes
                volumes = []
                mounts = container.attrs.get("Mounts", [])
                for mount in mounts:
                    source = mount.get("Source")
                    destination = mount.get("Destination")
                    if source and destination:
                         volumes.append(f"{source}:{destination}")
                volumes = sorted(volumes)
                
                # Environment
                env_dict = {}
                env_list = container.attrs.get("Config", {}).get("Env", [])
                for e in env_list:
                    if "=" in e:
                        k, v = e.split("=", 1)
                        env_dict[k] = v
                    else:
                        env_dict[e] = ""

                actual_state[service_name] = {
                    "image": image,
                    "ports": ports,
                    "volumes": volumes,
                    "environment": env_dict
                }
        except Exception as e:
            logger.error(f"Error fetching container state: {e}")
            
        return actual_state


class DriftComparator:
    def __init__(self, expected: Dict[str, Any], actual: Dict[str, Any]):
        self.expected = expected
        self.actual = actual

    def compare(self) -> List[Dict[str, Any]]:
        drift_reports = []

        for service, exp_config in self.expected.items():
            if service not in self.actual:
                drift_reports.append({
                    "service": service,
                    "drift_type": "missing_service",
                    "expected": "running",
                    "actual": "missing"
                })
                continue
                
            act_config = self.actual[service]
            
            # Check Image
            if exp_config["image"] and exp_config["image"] != act_config["image"]:
                 # Sometimes actual image includes sha256, simplified check
                 if not act_config["image"].startswith(exp_config["image"]):
                    drift_reports.append({
                        "service": service,
                        "drift_type": "image_mismatch",
                        "expected": exp_config["image"],
                        "actual": act_config["image"]
                    })
                    
            # Check Ports
            if exp_config["ports"] != act_config["ports"]:
                 drift_reports.append({
                        "service": service,
                        "drift_type": "port_mismatch",
                        "expected": exp_config["ports"],
                        "actual": act_config["ports"]
                 })
                 
            # Check Volumes
            # Runtime paths might be absolute while compose paths might be relative.
            # A strict check is hard without resolving, so we do a simple difference check.
            exp_volumes = set(exp_config["volumes"])
            act_volumes = set(act_config["volumes"])
            
            # Since relative paths get resolved to absolute, we check for presence of destination
            # This is a simplified volume drift check for demonstration.
            exp_dests = {v.split(':')[1] if ':' in v else v for v in exp_volumes}
            act_dests = {v.split(':')[1] if ':' in v else v for v in act_volumes}
            
            if exp_dests != act_dests:
                  drift_reports.append({
                        "service": service,
                        "drift_type": "volume_mismatch",
                        "expected": list(exp_dests),
                        "actual": list(act_dests)
                 })
                 
            # Note: Checking environment drift can be noisy due to docker injected envs
            # For this MVP, we only check if expected envs are modified/missing
            env_drift = False
            for k, v in exp_config["environment"].items():
                 # Handle variable interpolation roughly or skip if not literal
                 if not str(v).startswith('$'): 
                     if act_config["environment"].get(k) != v:
                         env_drift = True
                         break
            if env_drift:
                 drift_reports.append({
                        "service": service,
                        "drift_type": "env_mismatch",
                        "expected": "Declared environment match",
                        "actual": "Runtime environment differs"
                 })

        return drift_reports


class ReportGenerator:
    def __init__(self, drift_reports: List[Dict[str, Any]]):
        self.drift_reports = drift_reports
        
    def to_json(self) -> str:
        return json.dumps(self.drift_reports, indent=2)
        
    def to_markdown(self) -> str:
        if not self.drift_reports:
             return "✅ **No Drift Detected.** All runtime states match declared configurations."
             
        md = "⚠️ **Configuration Drift Detected!**\n\n"
        for report in self.drift_reports:
             md += f"- **Service:** `{report['service']}`\n"
             md += f"  - **Type:** {report['drift_type']}\n"
             md += f"  - **Expected:** `{report['expected']}`\n"
             md += f"  - **Actual:** `{report['actual']}`\n\n"
        return md


def main():
    parser = argparse.ArgumentParser(description="Homelab Unified Config Drift Detector & GitOps Sync Sentry")
    parser.add_argument("--check-now", action="store_true", help="Run drift detection immediately.")
    parser.add_argument("--repo-root", type=str, default=".", help="Path to the root of the Git repository.")
    parser.add_argument("--json", action="store_true", help="Output report in JSON format.")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending alerts (stdout only).")
    args = parser.parse_args()

    if not args.check_now:
        logger.info("Service started. Waiting for --check-now trigger. (Daemon mode not implemented in MVP).")
        return

    logger.info(f"Scanning repository root: {args.repo_root}")
    
    compose_parser = ComposeParser(args.repo_root)
    expected_state = compose_parser.parse()
    
    logger.info("Inspecting runtime state...")
    inspector = RuntimeInspector()
    actual_state = inspector.get_running_state()
    
    logger.info("Comparing states...")
    comparator = DriftComparator(expected_state, actual_state)
    drift_reports = comparator.compare()
    
    generator = ReportGenerator(drift_reports)
    
    if args.json:
        print(generator.to_json())
    else:
        print(generator.to_markdown())

if __name__ == "__main__":
    main()
