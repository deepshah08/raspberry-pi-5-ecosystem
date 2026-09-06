import os
import json
import time
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Set, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

INCIDENTS_LOG_PATH = os.environ.get('INCIDENTS_LOG_PATH', '/var/log/slo_watchdog/incidents.jsonl')
JULES_API_URL = os.environ.get('JULES_API_URL', 'http://localhost:8000/api/dispatch')
JULES_API_KEY = os.environ.get('JULES_API_KEY', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

class AutoHealDaemon:
    def __init__(self, log_path: str = INCIDENTS_LOG_PATH):
        self.log_path = log_path
        self.handled_incidents: Set[str] = set()

    def run(self):
        logger.info(f"Starting Auto-Heal Daemon, tailing {self.log_path}")
        self._tail_log()

    def _tail_log(self):
        # Ensure file exists
        if not os.path.exists(self.log_path):
            logger.warning(f"Log file {self.log_path} not found. Waiting...")
            while not os.path.exists(self.log_path):
                time.sleep(5)

        with open(self.log_path, 'r') as f:
            # Seek to end of file to tail only new events
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(1)
                    continue
                self.process_line(line)

    def process_line(self, line: str):
        try:
            line = line.strip()
            if not line:
                return
            incident = json.loads(line)
            self.evaluate_incident(incident)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON: {line}")
        except Exception as e:
            logger.error(f"Error processing line: {e}")

    def evaluate_incident(self, incident: Dict[str, Any]):
        incident_id = incident.get('id')
        if not incident_id:
            logger.warning("Incident missing ID, skipping.")
            return

        if incident_id in self.handled_incidents:
            logger.debug(f"Incident {incident_id} already handled.")
            return

        severity = incident.get('severity')
        status = incident.get('status')
        persistent = incident.get('persistent', False)

        if status == 'resolved':
            return

        # Condition for autonomous remediation:
        # 1. SEV-1 and unresolved
        # 2. SEV-2, persistent, and unresolved
        should_remediate = False
        if severity == 'SEV-1':
            should_remediate = True
        elif severity == 'SEV-2' and persistent:
            should_remediate = True

        if should_remediate:
            logger.info(f"Triggering remediation for incident {incident_id} ({severity})")
            success = self.dispatch_remediation(incident)
            if success:
                self.handled_incidents.add(incident_id)

    def dispatch_remediation(self, incident: Dict[str, Any]) -> bool:
        incident_id = incident.get('id')
        description = incident.get('description', 'Unknown issue')
        component = incident.get('component', 'Unknown component')

        prompt = f"Please fix the following incident affecting {component}: {description}. This is an automated request for remediation."

        payload = {
            "incident_id": incident_id,
            "prompt": prompt,
            "component": component
        }

        jules_success = self._send_jules_request(payload)

        if jules_success:
            message = f"🚨 *Auto-Heal Triggered* 🚨\nIncident ID: `{incident_id}`\nComponent: `{component}`\nDescription: {description}\nStatus: Dispatched Jules Agent Session"
            self._send_telegram_alert(message)
            return True
        else:
            logger.error(f"Failed to dispatch Jules agent for incident {incident_id}")
            return False

    def _send_jules_request(self, payload: Dict[str, Any]) -> bool:
        if not JULES_API_URL:
            logger.warning("JULES_API_URL not configured.")
            return False

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(JULES_API_URL, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        if JULES_API_KEY:
            req.add_header('Authorization', f'Bearer {JULES_API_KEY}')

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in (200, 201, 202):
                    logger.info("Successfully dispatched Jules request.")
                    return True
                else:
                    logger.warning(f"Jules API returned status {response.status}")
                    return False
        except urllib.error.URLError as e:
            logger.error(f"Failed to connect to Jules API: {e}")
            return False

    def _send_telegram_alert(self, message: str) -> bool:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.debug("Telegram credentials not configured. Skipping alert.")
            return False

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    logger.info("Successfully sent Telegram alert.")
                    return True
                return False
        except urllib.error.URLError as e:
            logger.error(f"Failed to connect to Telegram API: {e}")
            return False

if __name__ == "__main__":
    daemon = AutoHealDaemon()
    daemon.run()
