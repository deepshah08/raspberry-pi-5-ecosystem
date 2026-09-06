import argparse
import socket
import time
import json
import logging
import yaml
import requests
import subprocess
from typing import List, Dict, Any, Tuple
from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
RPI5_IP = "192.168.1.92"
UGREEN_NAS_IP = "192.168.1.80"
COMMON_PORTS = [80, 443, 8080, 5432, 9090, 9115] # A representative set

class ServiceDiscoverySurveyor:
    """Discovers active web services and ports across homelab nodes."""
    def __init__(self, nodes: List[str] = None, ports: List[int] = None):
        self.nodes = nodes if nodes is not None else [RPI5_IP, UGREEN_NAS_IP]
        self.ports = ports if ports is not None else COMMON_PORTS

    def check_port(self, host: str, port: int, timeout: float = 0.5) -> bool:
        """Checks if a TCP port is open."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            return result == 0

    def discover(self) -> List[Dict[str, Any]]:
        """Scans nodes and returns a list of discovered services."""
        discovered = []
        for node in self.nodes:
            logger.info(f"Scanning node: {node}")
            # Add ICMP probe for each node
            discovered.append({
                "target": node,
                "module": "icmp",
                "node": node,
                "port": 0
            })
            logger.info(f"Discovered {node} (icmp)")
            
            for port in self.ports:
                if self.check_port(node, port):
                    module = "http_2xx" if port in [80, 443, 8080, 9090] else "tcp_connect"
                    target = f"http://{node}:{port}" if module == "http_2xx" else f"{node}:{port}"
                    if port == 443:
                        target = f"https://{node}:{port}"
                    discovered.append({
                        "target": target,
                        "module": module,
                        "node": node,
                        "port": port
                    })
                    logger.info(f"Discovered {target} ({module})")
        return discovered


class TargetConfigSynthesizer:
    """Emits Prometheus blackbox_targets.yml with proper module configs."""
    @staticmethod
    def synthesize(discovered_services: List[Dict[str, Any]], output_path: str = None) -> List[Dict[str, Any]]:
        """Groups targets by module and generates the Prometheus file_sd config."""
        grouped_targets = {}
        for service in discovered_services:
            module = service["module"]
            target = service["target"]
            if module not in grouped_targets:
                grouped_targets[module] = []
            grouped_targets[module].append(target)

        config = []
        for module, targets in grouped_targets.items():
            config.append({
                "targets": targets,
                "labels": {
                    "module": module
                }
            })

        if output_path:
            try:
                with open(output_path, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
                logger.info(f"Synthesized config written to {output_path}")
            except Exception as e:
                logger.error(f"Failed to write config to {output_path}: {e}")

        return config


class ProbeEvaluator:
    """Executes synthetic reachability probes and validates response latencies."""
    
    @staticmethod
    def evaluate(discovered_services: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Runs basic tests on discovered targets and returns stats."""
        total_probes = len(discovered_services)
        healthy_probes = 0
        latencies = []
        
        for service in discovered_services:
            target = service["target"]
            module = service["module"]
            success = False
            start_time = time.time()
            
            try:
                if module == "http_2xx":
                    # For HTTPS, verify=True ensures TLS certificate validity is checked
                    verify = True if target.startswith("https") else False
                    response = requests.get(target, timeout=2, verify=verify)
                    success = response.status_code >= 200 and response.status_code < 400
                elif module == "tcp_connect":
                    node = service["node"]
                    port = service["port"]
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.settimeout(2)
                        result = sock.connect_ex((node, port))
                        success = result == 0
                elif module == "icmp":
                    # Simple ping check
                    result = subprocess.run(
                        ['ping', '-c', '1', '-W', '1', target],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    success = result.returncode == 0
                
                latency = time.time() - start_time
                if success:
                    healthy_probes += 1
                    latencies.append(latency)
                    logger.debug(f"Probe successful for {target} (latency: {latency:.4f}s)")
                else:
                    logger.warning(f"Probe failed for {target}")
            except requests.exceptions.SSLError as e:
                logger.warning(f"TLS Validation failed for {target}: {e}")
            except Exception as e:
                logger.warning(f"Probe exception for {target}: {e}")
                
        healthy_ratio = healthy_probes / total_probes if total_probes > 0 else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        
        return {
            "total_targets": total_probes,
            "healthy_probes": healthy_probes,
            "healthy_ratio": healthy_ratio,
            "avg_latency": avg_latency
        }


class PrometheusExporter:
    """Exposes port 9134 (homelab_blackbox_targets_total, homelab_blackbox_probes_healthy_ratio)."""
    
    def __init__(self, port: int = 9134):
        self.port = port
        self.targets_total = Gauge('homelab_blackbox_targets_total', 'Total number of discovered targets')
        self.healthy_ratio = Gauge('homelab_blackbox_probes_healthy_ratio', 'Ratio of healthy probes')
        self.avg_latency = Gauge('homelab_blackbox_probes_avg_latency_seconds', 'Average latency of healthy probes')
        
    def start(self):
        """Starts the HTTP server for Prometheus metrics."""
        start_http_server(self.port)
        logger.info(f"Started Prometheus exporter on port {self.port}")
        
    def update_metrics(self, stats: Dict[str, Any]):
        """Updates the exported metrics."""
        self.targets_total.set(stats["total_targets"])
        self.healthy_ratio.set(stats["healthy_ratio"])
        if "avg_latency" in stats:
            self.avg_latency.set(stats["avg_latency"])


def main():
    parser = argparse.ArgumentParser(description="Homelab Synthetic Blackbox Probe Coordinator")
    parser.add_argument("--scan-now", action="store_true", help="Run a single scan immediately")
    parser.add_argument("--output-config", type=str, help="Path to output blackbox_targets.yml")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files or export metrics, just print to stdout")
    parser.add_argument("--json", action="store_true", help="Output discovered services as JSON")
    
    args = parser.parse_args()
    
    if args.dry_run or args.json:
        # Don't start exporter if dry run or just json output
        exporter = None
    else:
        exporter = PrometheusExporter()
        try:
            exporter.start()
        except OSError as e:
            logger.error(f"Could not start Prometheus exporter: {e}")
            exporter = None
            
    while True:
        logger.info("Starting service discovery survey...")
        surveyor = ServiceDiscoverySurveyor()
        discovered = surveyor.discover()
        
        if args.json:
            print(json.dumps(discovered, indent=2))
        elif args.dry_run:
            logger.info(f"Discovered: {discovered}")
            
        config = TargetConfigSynthesizer.synthesize(
            discovered, 
            output_path=None if args.dry_run else args.output_config
        )
        
        logger.info("Evaluating reachability...")
        stats = ProbeEvaluator.evaluate(discovered)
        logger.info(f"Evaluation stats: {stats}")
        
        if exporter and not args.dry_run:
            exporter.update_metrics(stats)
            
        if args.scan_now or args.dry_run or args.json:
            break
            
        logger.info("Sleeping for 60 seconds...")
        time.sleep(60)

if __name__ == '__main__':
    main()
