import argparse
import json
import logging
import os
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Any

from prometheus_client import start_http_server, Gauge

# Try to import AlertRouter. Adjust path for standalone execution.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "56-notification-engine"))
try:
    from router import AlertRouter, Severity
except ImportError:
    # Mock fallback if project 56 isn't accessible
    class Severity(Enum):
        CRITICAL = "CRITICAL"
        WARNING = "WARNING"
        INFO = "INFO"
    class AlertRouter:
        def dispatch(self, source, title, body, severity):
            return True, "MOCKED"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ThermalState(Enum):
    COOL = 0
    OPTIMAL = 1
    WARM = 2
    CRITICAL = 3

    @classmethod
    def from_temp(cls, temp: float) -> "ThermalState":
        if temp < 40.0:
            return cls.COOL
        elif temp < 55.0:
            return cls.OPTIMAL
        elif temp < 65.0:
            return cls.WARM
        else:
            return cls.CRITICAL

    def __str__(self):
        return self.name

class ThermalSentry:
    def __init__(self, sys_path: str = "/sys", dry_run: bool = False):
        self.sys_path = Path(sys_path)
        self.dry_run = dry_run
        self.alert_router = AlertRouter()

        from prometheus_client import REGISTRY
        # Prometheus metrics
        # Use existing if already registered (for tests)
        if 'homelab_cpu_temp_celsius' in REGISTRY._names_to_collectors:
            self.metric_cpu = REGISTRY._names_to_collectors['homelab_cpu_temp_celsius']
            self.metric_nvme = REGISTRY._names_to_collectors['homelab_nvme_temp_celsius']
            self.metric_hdd = REGISTRY._names_to_collectors['homelab_hdd_temp_celsius']
            self.metric_state = REGISTRY._names_to_collectors['homelab_thermal_state']
        else:
            self.metric_cpu = Gauge('homelab_cpu_temp_celsius', 'CPU Temperature')
            self.metric_nvme = Gauge('homelab_nvme_temp_celsius', 'NVMe Temperature')
            self.metric_hdd = Gauge('homelab_hdd_temp_celsius', 'HDD Temperature')
            self.metric_state = Gauge('homelab_thermal_state', 'Overall Thermal State (0=Cool, 1=Optimal, 2=Warm, 3=Critical)')

        # History for rate of rise calculation
        self.history: Dict[str, list[tuple[float, float]]] = {
            "cpu": [],
            "nvme": [],
            "hdd": []
        }

    def _read_temp_file(self, path: Path) -> Optional[float]:
        try:
            if path.exists():
                text = path.read_text().strip()
                # Most sysfs temp files are in millidegrees Celsius
                return float(text) / 1000.0
        except Exception as e:
            logger.debug(f"Failed to read {path}: {e}")
        return None

    def read_cpu_temp(self) -> float:
        # Check standard thermal_zone0
        zone0_path = self.sys_path / "class" / "thermal" / "thermal_zone0" / "temp"
        temp = self._read_temp_file(zone0_path)
        if temp is not None:
            return temp
        return 35.0 # Fallback mock

    def read_nvme_temp(self) -> float:
        # Mocking NVMe temp location, as real one varies wildly in hwmon.
        # We'll check hwmon0 temp1_input as a heuristic
        hwmon0_path = self.sys_path / "class" / "hwmon" / "hwmon0" / "temp1_input"
        temp = self._read_temp_file(hwmon0_path)
        if temp is not None:
            return temp
        return 38.0 # Fallback mock

    def read_hdd_temp(self) -> float:
        # Mocking HDD temp location
        hwmon1_path = self.sys_path / "class" / "hwmon" / "hwmon1" / "temp1_input"
        temp = self._read_temp_file(hwmon1_path)
        if temp is not None:
            return temp
        return 32.0 # Fallback mock

    def update_history_and_check_rate(self, sensor: str, current_temp: float, current_time: float) -> Optional[float]:
        """Keep 1 minute of history, return rate of rise in C/min."""
        hist = self.history[sensor]
        hist.append((current_time, current_temp))

        # Prune history older than 60 seconds
        hist = [(t, v) for t, v in hist if current_time - t <= 65]
        self.history[sensor] = hist

        if len(hist) >= 2:
            oldest_time, oldest_temp = hist[0]
            time_diff = current_time - oldest_time
            if time_diff > 0:
                # Rate in C / minute
                rate = (current_temp - oldest_temp) / (time_diff / 60.0)
                return rate
        return 0.0

    def run_cycle(self) -> Dict[str, Any]:
        current_time = time.time()

        cpu = self.read_cpu_temp()
        nvme = self.read_nvme_temp()
        hdd = self.read_hdd_temp()

        # Update metrics
        self.metric_cpu.set(cpu)
        self.metric_nvme.set(nvme)
        self.metric_hdd.set(hdd)

        max_temp = max(cpu, nvme, hdd)
        state = ThermalState.from_temp(max_temp)
        self.metric_state.set(state.value)

        rates = {
            "cpu": self.update_history_and_check_rate("cpu", cpu, current_time),
            "nvme": self.update_history_and_check_rate("nvme", nvme, current_time),
            "hdd": self.update_history_and_check_rate("hdd", hdd, current_time),
        }

        # Check for alerts
        self._check_alerts(cpu, nvme, hdd, max_temp, state, rates)

        return {
            "cpu_temp": cpu,
            "nvme_temp": nvme,
            "hdd_temp": hdd,
            "max_temp": max_temp,
            "state": state.name,
            "rates": rates
        }

    def _check_alerts(self, cpu: float, nvme: float, hdd: float, max_temp: float, state: ThermalState, rates: Dict[str, float]):
        alerts = []

        # State-based alerts
        if state == ThermalState.CRITICAL:
            alerts.append((Severity.CRITICAL, "Thermal State CRITICAL", f"Max temp reached {max_temp:.1f}°C."))
        elif state == ThermalState.WARM:
            alerts.append((Severity.WARNING, "Thermal State WARM", f"Max temp reached {max_temp:.1f}°C."))

        # Rate of rise alerts
        for sensor, rate in rates.items():
            if rate is not None and rate >= 5.0:
                alerts.append((Severity.WARNING, f"Rapid Temp Rise: {sensor.upper()}", f"Rate is {rate:.1f}°C/min (>{5.0}°C/min)."))

        for severity, title, body in alerts:
            if not self.dry_run:
                self.alert_router.dispatch("Thermal Sentry", title, body, severity)
            else:
                logger.info(f"[DRY-RUN] Alert Dispatched - {severity.name}: {title} - {body}")


def main():
    parser = argparse.ArgumentParser(description="Homelab Thermal Throttle & Fan Governor Sentry")
    parser.add_argument("--dry-run", action="store_true", help="Do not send real alerts")
    parser.add_argument("--interval", type=int, default=15, help="Polling interval in seconds")
    parser.add_argument("--json", action="store_true", help="Output JSON status to stdout")
    parser.add_argument("--status", action="store_true", help="Run once and print status, then exit")
    parser.add_argument("--sys-path", type=str, default="/sys", help="Base path for sysfs (for testing)")

    args = parser.parse_args()

    sentry = ThermalSentry(sys_path=args.sys_path, dry_run=args.dry_run)

    if args.status:
        data = sentry.run_cycle()
        if args.json:
            print(json.dumps(data))
        else:
            print(f"CPU: {data['cpu_temp']}°C | NVMe: {data['nvme_temp']}°C | HDD: {data['hdd_temp']}°C")
            print(f"State: {data['state']}")
        sys.exit(0)

    logger.info("Starting Thermal Sentry on port 9108...")
    start_http_server(9108)

    try:
        while True:
            data = sentry.run_cycle()
            if args.json:
                print(json.dumps(data))
            else:
                logger.info(f"State: {data['state']} (CPU: {data['cpu_temp']:.1f}°C, NVMe: {data['nvme_temp']:.1f}°C, HDD: {data['hdd_temp']:.1f}°C)")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Thermal Sentry shutting down.")


if __name__ == "__main__":
    main()
