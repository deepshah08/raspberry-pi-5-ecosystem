import argparse
import json
import logging
import sys
import time
from typing import Dict, List, Any, Optional

import requests
from prometheus_client import start_http_server, Gauge

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Prometheus metrics
ENTITIES_TOTAL = Gauge('homelab_hass_entities_total', 'Total number of entities')
ENTITIES_UNAVAILABLE = Gauge('homelab_hass_entities_unavailable', 'Number of unavailable or unknown entities')
LOW_BATTERY_TOTAL = Gauge('homelab_hass_low_battery_total', 'Number of sensors with battery < 20%')

class HassSentinel:
    def __init__(self, hass_url: str, token: str, dry_run: bool = False, json_output: bool = False):
        self.hass_url = hass_url.rstrip('/')
        self.token = token
        self.dry_run = dry_run
        self.json_output = json_output
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str) -> Optional[requests.Response]:
        url = f"{self.hass_url}{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to Home Assistant at {url}: {e}")
            return None

    def get_states(self) -> List[Dict[str, Any]]:
        response = self._get("/api/states")
        if response:
            return response.json()
        return []

    def get_error_log(self) -> str:
        response = self._get("/api/error_log")
        if response:
            return response.text
        return ""

    def audit_entities(self, states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        unavailable = []
        for state in states:
            if state.get("state") in ["unavailable", "unknown"]:
                unavailable.append(state)
        return unavailable

    def audit_batteries(self, states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        low_battery = []
        for state in states:
            attributes = state.get("attributes", {})
            device_class = attributes.get("device_class")
            battery_level = None

            if "battery" in state.get("entity_id", "") or device_class == "battery":
                try:
                    battery_level = float(state.get("state"))
                except (ValueError, TypeError):
                    pass
            
            if battery_level is None and "battery_level" in attributes:
                try:
                    battery_level = float(attributes["battery_level"])
                except (ValueError, TypeError):
                    pass

            if battery_level is not None and battery_level < 20.0:
                low_battery.append(state)
        
        return low_battery

    def parse_error_log(self, log_text: str) -> List[str]:
        lines = log_text.splitlines()
        automation_errors = []
        error_counts = {}
        
        for line in lines:
            lower_line = line.lower()
            if "automation" in lower_line and ("error" in lower_line or "exception" in lower_line or "fail" in lower_line):
                error_counts[line] = error_counts.get(line, 0) + 1
                
        for line, count in error_counts.items():
            if count > 1:
                automation_errors.append(f"Repeated ({count} times): {line}")
                
        return automation_errors

    def run_audit(self):
        states = self.get_states()
        
        ENTITIES_TOTAL.set(len(states))
        
        unavailable_entities = self.audit_entities(states)
        ENTITIES_UNAVAILABLE.set(len(unavailable_entities))
        
        low_battery_entities = self.audit_batteries(states)
        LOW_BATTERY_TOTAL.set(len(low_battery_entities))
        
        error_log = self.get_error_log()
        automation_loops = self.parse_error_log(error_log)
        
        results = {
            "total_entities": len(states),
            "unavailable_entities": [e.get("entity_id") for e in unavailable_entities],
            "low_battery_entities": [e.get("entity_id") for e in low_battery_entities],
            "automation_loops": automation_loops
        }
        
        if self.json_output:
            print(json.dumps(results, indent=2))
        else:
            logger.info(f"Audit Complete. Total Entities: {results['total_entities']}")
            logger.info(f"Unavailable Entities ({len(unavailable_entities)}): {', '.join(results['unavailable_entities'])}")
            logger.info(f"Low Battery Entities ({len(low_battery_entities)}): {', '.join(results['low_battery_entities'])}")
            if automation_loops:
                logger.warning(f"Automation Loops Detected: {len(automation_loops)}")
                for loop in automation_loops:
                    logger.warning(f"  {loop}")
        
        return results

def main():
    parser = argparse.ArgumentParser(description="Homelab Home Assistant Entity & Sensor Invariant Sentinel")
    parser.add_argument("--hass-url", required=True, help="Home Assistant URL (e.g., http://localhost:8123)")
    parser.add_argument("--token", required=True, help="Long-lived access token for Home Assistant")
    parser.add_argument("--audit-now", action="store_true", help="Run a single audit and exit")
    parser.add_argument("--dry-run", action="store_true", help="Run without side effects (useful for testing)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    
    args = parser.parse_args()
    
    sentinel = HassSentinel(
        hass_url=args.hass_url,
        token=args.token,
        dry_run=args.dry_run,
        json_output=args.json
    )
    
    if args.audit_now:
        sentinel.run_audit()
        sys.exit(0)
        return
        
    logger.info("Starting Prometheus metrics server on port 9131")
    start_http_server(9131)
    
    try:
        while True:
            sentinel.run_audit()
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Sentinel shutting down")
        sys.exit(0)

if __name__ == "__main__":
    main()
