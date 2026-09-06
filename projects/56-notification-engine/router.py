import argparse
import hashlib
import json
import logging
import os
import time
from enum import Enum
from typing import Dict, Optional, Tuple

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Severity(Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class AlertRouter:
    def __init__(self, cooldown_seconds: int = 1800):
        self.cooldown_seconds = cooldown_seconds
        self._alert_history: Dict[str, float] = {}
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        self.ntfy_topic_url = os.environ.get("NTFY_TOPIC_URL")

    def _generate_fingerprint(self, source: str, title: str) -> str:
        """Generate a hash fingerprint for an alert."""
        data = f"{source}:{title}"
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def _is_duplicate(self, fingerprint: str) -> bool:
        """Check if an alert with this fingerprint was sent within the cooldown window."""
        current_time = time.time()
        if fingerprint in self._alert_history:
            last_seen = self._alert_history[fingerprint]
            if current_time - last_seen < self.cooldown_seconds:
                return True
        return False

    def _update_history(self, fingerprint: str):
        self._alert_history[fingerprint] = time.time()

    def _send_telegram(self, title: str, body: str, severity: Severity) -> bool:
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram credentials not configured, skipping Telegram dispatch.")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"

        prefix = "🚨" if severity == Severity.CRITICAL else "⚠️"
        text = f"{prefix} *{severity.value}*: {title}\n\n{body}"

        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Successfully dispatched to Telegram.")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to dispatch to Telegram: {e}")
            return False

    def _send_ntfy(self, title: str, body: str, severity: Severity) -> bool:
        if not self.ntfy_topic_url:
            logger.warning("NTFY topic URL not configured, skipping NTFY dispatch.")
            return False

        headers = {
            "Title": f"[{severity.value}] {title}",
            "Priority": "high" if severity == Severity.CRITICAL else "default",
            "Tags": "rotating_light" if severity == Severity.CRITICAL else "warning"
        }

        try:
            response = requests.post(self.ntfy_topic_url, data=body.encode('utf-8'), headers=headers, timeout=10)
            response.raise_for_status()
            logger.info("Successfully dispatched to NTFY.")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to dispatch to NTFY: {e}")
            return False

    def dispatch(self, source: str, title: str, body: str, severity: Severity = Severity.INFO) -> Tuple[bool, str]:
        """Dispatch an alert based on severity and deduplication rules."""
        fingerprint = self._generate_fingerprint(source, title)

        if self._is_duplicate(fingerprint):
            msg = f"Alert '{title}' from '{source}' suppressed (cooldown window)."
            logger.info(msg)
            return False, "SUPPRESSED"

        logger.info(f"Dispatching alert: {title} (Severity: {severity.value})")

        dispatched_any = False

        if severity == Severity.CRITICAL:
            telegram_success = self._send_telegram(title, body, severity)
            ntfy_success = self._send_ntfy(title, body, severity)
            dispatched_any = telegram_success or ntfy_success
        elif severity == Severity.WARNING:
            dispatched_any = self._send_telegram(title, body, severity)
        elif severity == Severity.INFO:
            # For INFO, we would normally queue to WebSocket bus here.
            logger.info(f"INFO alert queued to local bus: {title}")
            dispatched_any = True

        if dispatched_any or severity == Severity.INFO:
            self._update_history(fingerprint)
            return True, "DISPATCHED"

        return False, "FAILED"


def main():
    parser = argparse.ArgumentParser(description="Multi-Channel Alert Router & Rate-Limiting Notification Engine")
    parser.add_argument("--send-test", action="store_true", help="Send a test notification")
    parser.add_argument("--severity", choices=[s.value for s in Severity], default="INFO", help="Alert severity")
    parser.add_argument("--title", type=str, help="Alert title", default="Test Alert")
    parser.add_argument("--body", type=str, help="Alert body text", default="This is a test alert from the notification engine.")
    parser.add_argument("--source", type=str, help="Alert source", default="CLI")

    args = parser.parse_args()

    if args.send_test:
        router = AlertRouter()
        severity = Severity(args.severity)
        success, status = router.dispatch(
            source=args.source,
            title=args.title,
            body=args.body,
            severity=severity
        )
        print(f"Dispatch status: {status}")


if __name__ == "__main__":
    main()
