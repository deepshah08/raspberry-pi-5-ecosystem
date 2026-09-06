import argparse
import json
import logging
import time
import requests
import re
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from prometheus_client import start_http_server, Counter, Gauge

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prometheus Metrics
homelab_syncthing_conflicts_total = Counter('homelab_syncthing_conflicts_total', 'Total number of sync conflicts detected')
homelab_syncthing_devices_connected = Gauge('homelab_syncthing_devices_connected', 'Number of devices currently connected')
homelab_syncthing_sync_completion_ratio = Gauge('homelab_syncthing_sync_completion_ratio', 'Sync completion ratio (0.0 to 1.0)', ['folder'])

class SyncthingClient:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip('/')
        self.headers = {'X-API-Key': api_key}
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        url = f"{self.api_url}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error accessing Syncthing API at {url}: {e}")
            return {}

    def get_system_status(self) -> Dict[str, Any]:
        return self._get('/rest/system/status')

    def get_system_connections(self) -> Dict[str, Any]:
        return self._get('/rest/system/connections')

    def get_db_completion(self, device_id: str, folder_id: str) -> Dict[str, Any]:
        return self._get('/rest/db/completion', params={'device': device_id, 'folder': folder_id})

    def get_db_ignores(self, folder_id: str) -> Dict[str, Any]:
        return self._get('/rest/db/ignores', params={'folder': folder_id})

    def get_config(self) -> Dict[str, Any]:
        return self._get('/rest/config')

    def get_db_browse(self, folder_id: str, prefix: str = "", levels: int = 0) -> List[Dict[str, Any]]:
        # Using db/browse to search for files without scanning disk recursively
        # levels=0 by default traverses the entire tree? Wait, according to syncthing API, levels=0 means recursive
        # For our case, we can fetch all and filter by .sync-conflict
        try:
            res = self._get('/rest/db/browse', params={'folder': folder_id, 'prefix': prefix, 'levels': levels})
            return res
        except Exception:
            return {}


class SyncthingWatchdog:
    def __init__(self, api_url: str, api_key: str, dry_run: bool = False):
        self.client = SyncthingClient(api_url, api_key)
        self.dry_run = dry_run
        self.known_conflicts = set()
        self.device_disconnect_time = {}
        self.stuck_sync_time = {}

    def _traverse_browse_tree(self, tree: List[Dict], conflicts: List[Dict], path_prefix: str = ""):
        for item in tree:
            name = item.get('name', '')
            current_path = f"{path_prefix}/{name}".strip('/')

            # Check if it's a conflict file
            match = re.search(r'\.sync-conflict-\d{8}-\d{6}-([A-Z0-9]+)\.', name)
            if not match:
                # also try without extension or different format
                match = re.search(r'\.sync-conflict-\d{8}-\d{6}-([A-Z0-9]+)', name)
            if match:
                device_id = match.group(1)
            else:
                # Basic check if it just contains sync-conflict
                if re.search(r'\.sync-conflict-', name):
                    device_id = "UNKNOWN"
                else:
                    device_id = None

            if device_id is not None:
                conflicts.append({
                    'file': current_path,
                    'size': item.get('size', 0),
                    'timestamp': item.get('modTime', ''),
                    'conflicting_device': device_id
                })

            # Traverse children
            if 'children' in item and isinstance(item['children'], list):
                self._traverse_browse_tree(item['children'], conflicts, current_path)

    def check_conflicts(self) -> List[Dict]:
        conflicts = []
        config = self.client.get_config()
        if not config or 'folders' not in config:
            return conflicts

        for folder in config['folders']:
            folder_id = folder['id']
            browse_res = self.client.get_db_browse(folder_id)
            if browse_res and isinstance(browse_res, list):
                self._traverse_browse_tree(browse_res, conflicts)
            elif browse_res and isinstance(browse_res, dict):
                # if root is a dict, wrap it in a list
                if 'name' not in browse_res:
                    # Sometimes the API returns a dict of children or similar.
                    # Actually, syncthing /rest/db/browse returns a tree where the root represents the folder
                    # Let's handle different structures robustly.
                    pass
                self._traverse_browse_tree([browse_res] if 'name' in browse_res else browse_res.get('children', []), conflicts)

        return conflicts

    def run_check(self) -> Dict[str, Any]:
        # 1. Connections
        connections_data = self.client.get_system_connections()
        connections = connections_data.get('connections', {})
        connected_devices = [device_id for device_id, conn in connections.items() if conn.get('connected', False)]
        connected_count = len(connected_devices)

        homelab_syncthing_devices_connected.set(connected_count)

        # 2. Conflicts
        current_conflicts = self.check_conflicts()
        new_conflicts = []
        for conflict in current_conflicts:
            file_path = conflict['file']
            if file_path not in self.known_conflicts:
                self.known_conflicts.add(file_path)
                new_conflicts.append(conflict)

        if not self.dry_run and len(new_conflicts) > 0:
            homelab_syncthing_conflicts_total.inc(len(new_conflicts))

        # Device Disconnection Logic
        current_time = datetime.now(timezone.utc).timestamp()

        # We need to get all known devices to check for disconnections
        config = self.client.get_config()
        all_devices = config.get('devices', []) if config else []

        for dev in all_devices:
            dev_id = dev.get('deviceID')
            if dev_id not in connected_devices:
                # Device is disconnected
                if dev_id not in self.device_disconnect_time:
                    self.device_disconnect_time[dev_id] = current_time
                else:
                    duration = current_time - self.device_disconnect_time[dev_id]
                    if duration > 3600: # >1 hour
                        logger.warning(f"Device {dev_id} has been disconnected for over 1 hour.")
            else:
                # Device is connected, clear any disconnect time
                if dev_id in self.device_disconnect_time:
                    del self.device_disconnect_time[dev_id]

        # 3. Completion & Stuck Sync Logic
        # We need to get completions for connected devices for each folder
        folders = config.get('folders', []) if config else []
        for folder in folders:
            folder_id = folder.get('id')
            devices = folder.get('devices', [])
            total_ratio = 0
            dev_count = 0
            for dev in devices:
                dev_id = dev.get('deviceID')
                if dev_id in connected_devices:
                    comp_data = self.client.get_db_completion(dev_id, folder_id)
                    if comp_data:
                        # completion metric usually has completion percentage
                        ratio = comp_data.get('completion', 0.0) / 100.0
                        total_ratio += ratio
                        dev_count += 1

                        # Stuck sync detection
                        sync_key = f"{dev_id}-{folder_id}"
                        if ratio < 1.0:
                            if sync_key not in self.stuck_sync_time:
                                self.stuck_sync_time[sync_key] = current_time
                            else:
                                duration = current_time - self.stuck_sync_time[sync_key]
                                if duration > 1800: # >30m
                                    logger.warning(f"Sync for folder '{folder_id}' on device '{dev_id}' is stuck at {ratio*100:.2f}% for over 30 minutes.")
                        else:
                            if sync_key in self.stuck_sync_time:
                                del self.stuck_sync_time[sync_key]

            if dev_count > 0:
                avg_ratio = total_ratio / dev_count
                if not self.dry_run:
                    homelab_syncthing_sync_completion_ratio.labels(folder=folder_id).set(avg_ratio)


        result = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'conflicts': current_conflicts, # return all conflicts for JSON output
            'new_conflicts': new_conflicts,
            'connected_devices': connected_count,
        }
        return result


def main():
    parser = argparse.ArgumentParser(description="Syncthing Watchdog")
    parser.add_argument('--check-now', action='store_true', help="Run once and exit")
    parser.add_argument('--api-url', type=str, default="http://127.0.0.1:8384", help="Syncthing API URL")
    parser.add_argument('--api-key', type=str, required=True, help="Syncthing API Key")
    parser.add_argument('--dry-run', action='store_true', help="Dry run mode")
    parser.add_argument('--json', action='store_true', help="Output in JSON format")

    args = parser.parse_args()

    watchdog = SyncthingWatchdog(api_url=args.api_url, api_key=args.api_key, dry_run=args.dry_run)

    if args.check_now:
        result = watchdog.run_check()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            logger.info(f"Check complete: {result}")
    else:
        # Start Prometheus exporter
        start_http_server(9122)
        logger.info("Started Prometheus metrics server on port 9122")

        while True:
            try:
                result = watchdog.run_check()
                if args.json:
                    print(json.dumps(result))
            except Exception as e:
                logger.error(f"Error during check: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
