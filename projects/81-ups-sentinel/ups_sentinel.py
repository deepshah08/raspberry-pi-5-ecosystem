import argparse
import logging
import socket
import sys
import json
import time
import subprocess
from typing import Dict, Any, Optional
from prometheus_client import start_http_server, Gauge, Enum, Info

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prometheus Metrics
prom_charge = Gauge('homelab_ups_battery_charge_percent', 'UPS battery charge percentage')
prom_runtime = Gauge('homelab_ups_runtime_seconds', 'UPS remaining runtime in seconds')
prom_load = Gauge('homelab_ups_load_percent', 'UPS load percentage')
prom_status = Gauge('homelab_ups_status', 'UPS status (1=OL, 2=OB, 3=LB, 0=Unknown)')
prom_status_info = Info('homelab_ups_status_text', 'UPS status string')

class NUTClient:
    def __init__(self, host: str, port: int = 3493):
        self.host = host
        self.port = port
        self.ups_name = self._get_ups_name()

    def _get_ups_name(self) -> Optional[str]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((self.host, self.port))
                s.sendall(b"LIST UPS\n")
                data = s.recv(1024).decode('utf-8')
                lines = data.split('\n')
                for line in lines:
                    if line.startswith('UPS '):
                        parts = line.split(' ')
                        if len(parts) >= 2:
                            return parts[1]
                return None
        except Exception as e:
            logger.error(f"Failed to get UPS name from {self.host}:{self.port}: {e}")
            return None

    def query_variable(self, variable: str) -> Optional[str]:
        if not self.ups_name:
            self.ups_name = self._get_ups_name()
            if not self.ups_name:
                return None

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((self.host, self.port))
                cmd = f"GET VAR {self.ups_name} {variable}\n"
                s.sendall(cmd.encode('utf-8'))
                data = s.recv(1024).decode('utf-8')
                if data.startswith(f"VAR {self.ups_name} {variable}"):
                    start_quote = data.find('"')
                    end_quote = data.rfind('"')
                    if start_quote != -1 and end_quote != -1 and start_quote != end_quote:
                        return data[start_quote+1:end_quote]
                return None
        except Exception as e:
            logger.error(f"Failed to query {variable}: {e}")
            return None

    def get_metrics(self) -> Dict[str, Any]:
        charge = self.query_variable("battery.charge")
        runtime = self.query_variable("battery.runtime")
        status = self.query_variable("ups.status")
        load = self.query_variable("ups.load")

        metrics = {}
        if charge is not None:
            try:
                metrics['battery.charge'] = float(charge)
            except ValueError:
                pass

        if runtime is not None:
            try:
                metrics['battery.runtime'] = float(runtime)
            except ValueError:
                pass

        if load is not None:
            try:
                metrics['ups.load'] = float(load)
            except ValueError:
                pass

        if status is not None:
            metrics['ups.status'] = status.strip()

        return metrics

class ShutdownOrchestrator:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def execute_command(self, node_ip: str, cmd: str, description: str):
        full_cmd = f"ssh root@{node_ip} '{cmd}'"
        logger.info(f"[{'DRY-RUN' if self.dry_run else 'EXEC'}] {description}: {full_cmd}")
        if not self.dry_run:
            try:
                subprocess.run(full_cmd, shell=True, check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to execute {description} on {node_ip}: {e}")

    def emit_alert(self, message: str):
        # Sends alert to Alert Router (Project 56)
        logger.warning(f"ALERT ROUTER MSG: {message}")
        if not self.dry_run:
            pass # Implement alert router sending here if needed

    def perform_shutdown(self):
        logger.critical("Initiating graceful multi-node shutdown sequence...")
        self.emit_alert("CRITICAL: Battery exhausted or low. Initiating shutdown sequence.")

        # 1. Suspend containers on NAS
        self.execute_command("192.168.1.80", "docker stop $(docker ps -q)", "Suspend Docker containers on NAS")

        # 2. Unmount mechanical HDD on NAS
        self.execute_command("192.168.1.80", "umount /volume1", "Unmount mechanical HDD /volume1 on NAS")

        # 3. Shutdown Raspberry Pi 5
        self.execute_command("192.168.1.92", "shutdown -h now", "Shutdown Raspberry Pi 5")

        # 4. Shutdown NAS
        self.execute_command("192.168.1.80", "shutdown -h now", "Shutdown UGREEN NAS")

class PowerStateMachine:
    def __init__(self, orchestrator: ShutdownOrchestrator):
        self.orchestrator = orchestrator
        self.last_state = 'ONLINE'
        self.shutdown_triggered = False

    def evaluate(self, metrics: Dict[str, Any]):
        if self.shutdown_triggered:
            return

        status = metrics.get('ups.status', '')
        charge = metrics.get('battery.charge', 100.0)
        runtime = metrics.get('battery.runtime', 3600.0)

        current_state = 'ONLINE'
        if 'OB' in status:
            current_state = 'ON_BATTERY'
        if 'LB' in status or charge < 25.0 or runtime < 600.0:
            current_state = 'LOW_BATTERY'

        if current_state != self.last_state:
            logger.info(f"Power state transitioned from {self.last_state} to {current_state}")
            if current_state == 'ON_BATTERY':
                self.orchestrator.emit_alert("WARNING: Utility power failed. UPS on battery.")

            self.last_state = current_state

        if current_state == 'LOW_BATTERY':
            logger.critical(f"LOW BATTERY DETECTED (Charge: {charge}%, Runtime: {runtime}s, Status: {status})")
            self.orchestrator.perform_shutdown()
            self.shutdown_triggered = True


def update_prometheus_metrics(metrics: Dict[str, Any]):
    if 'battery.charge' in metrics:
        prom_charge.set(metrics['battery.charge'])
    if 'battery.runtime' in metrics:
        prom_runtime.set(metrics['battery.runtime'])
    if 'ups.load' in metrics:
        prom_load.set(metrics['ups.load'])

    if 'ups.status' in metrics:
        status_str = metrics['ups.status']
        prom_status_info.info({'status': status_str})
        status_val = 0
        if 'OL' in status_str:
            status_val = 1
        elif 'LB' in status_str:
            status_val = 3
        elif 'OB' in status_str:
            status_val = 2
        prom_status.set(status_val)


def parse_args():
    parser = argparse.ArgumentParser(description="Homelab Automated Power Outage & UPS Battery Sentinel")
    parser.add_argument('--check-now', action='store_true', help="Run a single check and exit")
    parser.add_argument('--host', type=str, default='127.0.0.1', help="NUT server host IP")
    parser.add_argument('--port', type=int, default=3493, help="NUT server port")
    parser.add_argument('--dry-run', action='store_true', help="Do not execute shutdown commands")
    parser.add_argument('--json', action='store_true', help="Output metrics in JSON format")
    return parser.parse_args()

def main():
    args = parse_args()
    logger.info(f"Starting UPS Sentinel (host={args.host}, port={args.port}, dry_run={args.dry_run})")

    start_http_server(9113)
    logger.info("Prometheus metrics exporter started on port 9113")

    client = NUTClient(args.host, args.port)
    orchestrator = ShutdownOrchestrator(args.dry_run)
    state_machine = PowerStateMachine(orchestrator)

    while True:
        metrics = client.get_metrics()

        if args.json:
            print(json.dumps(metrics))
        else:
            logger.info(f"Metrics: {metrics}")

        update_prometheus_metrics(metrics)
        state_machine.evaluate(metrics)

        if args.check_now:
            break

        time.sleep(15)

if __name__ == '__main__':
    main()
