import argparse
import sys
import json
import logging
import datetime
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Set
from prometheus_client import start_http_server, Counter, Gauge

# Prometheus Metrics
homelab_silences_active_total = Gauge(
    'homelab_silences_active_total',
    'Number of active silences created by the silencer'
)
homelab_alert_storm_detected = Counter(
    'homelab_alert_storm_detected',
    'Number of alert storms detected and processed'
)
homelab_deduplicated_alerts_total = Counter(
    'homelab_deduplicated_alerts_total',
    'Number of downstream symptom alerts suppressed'
)

class MaintenanceSilenceCoordinator:
    def __init__(self, alertmanager_url: str, dry_run: bool = False):
        self.am_url = alertmanager_url
        self.dry_run = dry_run

    def is_in_maintenance_window(self, current_time: Optional[datetime.datetime] = None) -> bool:
        if current_time is None:
            current_time = datetime.datetime.now()
        t = current_time.time()
        start = datetime.time(13, 0)
        end = datetime.time(16, 0)
        return start <= t < end

    def get_active_maintenance_silences(self) -> List[Dict[str, Any]]:
        url = f"{self.am_url}/api/v2/silences?filter=createdBy%3D%22alert_silencer%22"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    # Return only active silences
                    return [s for s in data if s.get('status', {}).get('state') == 'active']
                return []
        except urllib.error.URLError as e:
            logging.error(f"Failed to fetch silences: {e}")
            return []

    def create_silence(self, current_time: Optional[datetime.datetime] = None) -> Optional[str]:
        if current_time is None:
            current_time = datetime.datetime.now().astimezone() # Get local time with timezone info

        # Ensure current_time has tzinfo, if naive, assume local
        if current_time.tzinfo is None:
            current_time = current_time.astimezone()

        now_utc = current_time.astimezone(datetime.timezone.utc)

        end_local = datetime.datetime.combine(current_time.date(), datetime.time(16, 0), tzinfo=current_time.tzinfo)
        end_utc = end_local.astimezone(datetime.timezone.utc)

        if (end_utc - now_utc).total_seconds() <= 0:
            return None

        payload = {
            "matchers": [
                {
                    "name": "alertname",
                    "value": ".*",
                    "isRegex": True
                }
            ],
            "startsAt": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endsAt": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "createdBy": "alert_silencer",
            "comment": "Scheduled maintenance window (13:00-16:00)"
        }

        if self.dry_run:
            logging.info(f"DRY RUN: Would create silence with payload {payload}")
            return "dry-run-silence-id"

        url = f"{self.am_url}/api/v2/silences"
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req) as response:
                if response.status in (200, 201):
                    res_data = json.loads(response.read().decode('utf-8'))
                    silence_id = res_data.get('silenceID')
                    logging.info(f"Created silence {silence_id}")

                    return silence_id
        except urllib.error.URLError as e:
            logging.error(f"Failed to create silence: {e}")
        return None

    def get_all_active_silences(self) -> List[Dict[str, Any]]:
        url = f"{self.am_url}/api/v2/silences"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    return [s for s in data if s.get('status', {}).get('state') == 'active' and s.get('createdBy') in ('alert_silencer', 'storm_deduplicator')]
                return []
        except urllib.error.URLError as e:
            logging.error(f"Failed to fetch all silences: {e}")
            return []

    def manage_window(self):
        # Update gauge
        all_silences = self.get_all_active_silences()
        homelab_silences_active_total.set(len(all_silences))

        if self.is_in_maintenance_window():
            active_silences = self.get_active_maintenance_silences()
            if not active_silences:
                logging.info("In maintenance window, but no active silence found. Creating one.")
                self.create_silence()
            else:
                logging.info(f"Maintenance window active. Found {len(active_silences)} active silence(s).")


class StormDeduplicator:
    def __init__(self, alertmanager_url: str, dry_run: bool = False):
        self.am_url = alertmanager_url
        self.dry_run = dry_run

        # Root cause mapped to downstream alertnames it suppresses
        self.root_cause_rules = {
            "HostReboot": ["NodeUnreachable", "ServiceDown"],
            "UPSOnBattery": ["NodeUnreachable", "DiskBackupFailed", "NetworkPartition"]
        }

    def get_alerts(self) -> List[Dict[str, Any]]:
        url = f"{self.am_url}/api/v2/alerts"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    return data
                return []
        except urllib.error.URLError as e:
            logging.error(f"Failed to fetch alerts: {e}")
            return []

    def process_alerts(self):
        alerts = self.get_alerts()
        active_alerts = [a for a in alerts if a.get("status", {}).get("state") == "active"]

        alert_names = [a.get("labels", {}).get("alertname") for a in active_alerts]
        active_root_causes = [name for name in alert_names if name in self.root_cause_rules]

        if active_root_causes:
            homelab_alert_storm_detected.inc()
            logging.info(f"Detected root cause alerts: {active_root_causes}")

            suppress_targets: Set[str] = set()
            for rc in active_root_causes:
                suppress_targets.update(self.root_cause_rules[rc])

            symptom_alerts = [a for a in active_alerts if a.get("labels", {}).get("alertname") in suppress_targets]

            for symptom in symptom_alerts:
                symptom_name = symptom.get("labels", {}).get("alertname")
                logging.info(f"Suppressing symptom alert: {symptom_name}")
                homelab_deduplicated_alerts_total.inc()
                self._silence_symptom(symptom)

    def _silence_symptom(self, alert: Dict[str, Any]):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        end_utc = now_utc + datetime.timedelta(hours=1)

        labels = alert.get("labels", {})
        matchers = [{"name": k, "value": v, "isRegex": False} for k, v in labels.items()]

        payload = {
            "matchers": matchers,
            "startsAt": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endsAt": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "createdBy": "storm_deduplicator",
            "comment": "Suppressed downstream symptom due to root cause alert"
        }

        if self.dry_run:
            logging.info(f"DRY RUN: Would silence symptom alert with payload {payload}")
            return

        url = f"{self.am_url}/api/v2/silences"
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req) as response:
                if response.status in (200, 201):
                    res_data = json.loads(response.read().decode('utf-8'))
                    silence_id = res_data.get('silenceID')
                    logging.info(f"Created silence {silence_id} for symptom alert")

        except urllib.error.URLError as e:
            logging.error(f"Failed to create silence for symptom: {e}")

def parse_args():
    parser = argparse.ArgumentParser(description="Homelab Prometheus Alertmanager Deduplicator & Silencer")
    parser.add_argument('--check-now', action='store_true', help="Run checks immediately once")
    parser.add_argument('--alertmanager-url', type=str, default='http://localhost:9093', help="URL of the Alertmanager API")
    parser.add_argument('--create-window-silence', action='store_true', help="Create silence for maintenance window")
    parser.add_argument('--dry-run', action='store_true', help="Run without making API changes")
    parser.add_argument('--json', action='store_true', help="Output logs/results in JSON format")
    return parser.parse_args()

def main():
    args = parse_args()

    if args.json:
        logging.basicConfig(level=logging.INFO, format='{"level": "%(levelname)s", "message": "%(message)s"}')
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    coordinator = MaintenanceSilenceCoordinator(args.alertmanager_url, args.dry_run)
    deduplicator = StormDeduplicator(args.alertmanager_url, args.dry_run)

    if args.create_window_silence or args.check_now:
        coordinator.manage_window()
        deduplicator.process_alerts()

    if not args.check_now:
        import time
        start_http_server(9123)
        logging.info("Prometheus metrics available on port 9123")
        logging.info("Starting continuous polling loop...")
        try:
            while True:
                coordinator.manage_window()
                deduplicator.process_alerts()
                time.sleep(60)
        except KeyboardInterrupt:
            logging.info("Exiting...")

if __name__ == '__main__':
    main()
