import argparse
import sys
import requests
from typing import Dict, Any, List

class QBittorrentClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()

    def get_preferences(self) -> Dict[str, Any]:
        response = self.session.get(f"{self.base_url}/api/v2/app/preferences")
        response.raise_for_status()
        return response.json()

    def set_preferences(self, prefs: Dict[str, Any]) -> None:
        response = self.session.post(f"{self.base_url}/api/v2/app/setPreferences", data={'json': json.dumps(prefs)})
        response.raise_for_status()

    def get_torrents(self) -> List[Dict[str, Any]]:
        response = self.session.get(f"{self.base_url}/api/v2/torrents/info")
        response.raise_for_status()
        return response.json()
        
    def pause_torrents(self, hashes: List[str]) -> None:
        if not hashes:
            return
        response = self.session.post(f"{self.base_url}/api/v2/torrents/pause", data={'hashes': '|'.join(hashes)})
        response.raise_for_status()

import json

class ConfigurationAuditor:
    def __init__(self, client: QBittorrentClient, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def audit_and_enforce(self) -> List[str]:
        prefs = self.client.get_preferences()
        updates: Dict[str, Any] = {}
        actions_taken = []

        # 0: TCP and uTP, 1: TCP, 2: uTP
        if prefs.get("bittorrent_protocol") != 1:
            updates["bittorrent_protocol"] = 1
            actions_taken.append("Enforced TCP-only transport (disabled uTP)")

        # GlobalMaxRatio = 1.0, GlobalMaxRatioAction = 0 (pause)
        if prefs.get("max_ratio") != 1.0:
            updates["max_ratio"] = 1.0
            actions_taken.append("Enforced GlobalMaxRatio to 1.0")

        if prefs.get("max_ratio_act") != 0:
            updates["max_ratio_act"] = 0
            actions_taken.append("Enforced GlobalMaxRatioAction to Pause")

        # Check connection limits - cap them safely
        if prefs.get("max_active_downloads") != 10:
            updates["max_active_downloads"] = 10
            actions_taken.append("Enforced Max Active Downloads to 10")
            
        if prefs.get("max_active_uploads") != 10:
            updates["max_active_uploads"] = 10
            actions_taken.append("Enforced Max Active Uploads to 10")
            
        if prefs.get("max_active_torrents") != 20:
            updates["max_active_torrents"] = 20
            actions_taken.append("Enforced Max Active Torrents to 20")

        if updates and not self.dry_run:
            self.client.set_preferences(updates)
        elif updates and self.dry_run:
            actions_taken = [f"[DRY-RUN] {action}" for action in actions_taken]

        return actions_taken

class RatioEnforcer:
    def __init__(self, client: QBittorrentClient, target_ratio: float = 1.0, dry_run: bool = False):
        self.client = client
        self.target_ratio = target_ratio
        self.dry_run = dry_run

    def enforce(self) -> List[str]:
        torrents = self.client.get_torrents()
        to_pause = []
        actions_taken = []

        for torrent in torrents:
            state = torrent.get("state", "")
            if state in ["pausedUP", "pausedDL"]:
                continue
            
            ratio = torrent.get("ratio", 0.0)
            if ratio >= self.target_ratio:
                to_pause.append(torrent["hash"])
                name = torrent.get("name", "Unknown")
                action_str = f"Paused torrent '{name}' (Ratio: {ratio:.2f} >= {self.target_ratio})"
                if self.dry_run:
                    action_str = f"[DRY-RUN] {action_str}"
                actions_taken.append(action_str)
        
        if to_pause and not self.dry_run:
            self.client.pause_torrents(to_pause)
            
        return actions_taken

class SpindownHelper:
    def __init__(self, client: QBittorrentClient):
        self.client = client

    def check_spindown_readiness(self) -> List[str]:
        torrents = self.client.get_torrents()
        active_torrents = [t for t in torrents if t.get("state") not in ["pausedUP", "pausedDL"]]
        
        actions_taken = []
        if not active_torrents:
            actions_taken.append("Zero active torrents. Drives are eligible for spindown.")
            
        return actions_taken

def parse_args(args=None):
    parser = argparse.ArgumentParser(description="qBittorrent Conntrack & Ratio Enforcer Watchdog")
    parser.add_argument("--check-now", action="store_true", help="Run a check immediately")
    parser.add_argument("--api-url", type=str, default="http://localhost:8080", help="qBittorrent Web API URL")
    parser.add_argument("--target-ratio", type=float, default=1.0, help="Target ratio to enforce")
    parser.add_argument("--dry-run", action="store_true", help="Run without making any changes")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    return parser.parse_args(args)

import time

def run_once(args):
    client = QBittorrentClient(args.api_url)
    auditor = ConfigurationAuditor(client, dry_run=args.dry_run)
    enforcer = RatioEnforcer(client, target_ratio=args.target_ratio, dry_run=args.dry_run)
    spindown = SpindownHelper(client)
    
    actions = []
    try:
        actions.extend(auditor.audit_and_enforce())
        actions.extend(enforcer.enforce())
        actions.extend(spindown.check_spindown_readiness())
        
        if args.json:
            print(json.dumps({"actions": actions}))
        else:
            for action in actions:
                print(action)
            if not actions:
                print("No actions taken.")
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}")

def main():
    args = parse_args()
    
    if args.check_now:
        run_once(args)
    else:
        print(f"Starting daemon mode, polling every 60 seconds...")
        while True:
            run_once(args)
            time.sleep(60)

if __name__ == "__main__":
    main()
