import argparse
import sys
import logging
import time
import os
import requests
from typing import Dict, List, Optional, Any

class AudiobookshelfClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def get_listening_sessions(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/users/listening-sessions"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json().get("sessions", [])
        except requests.RequestException as e:
            logging.error(f"ABS API Error (get_listening_sessions): {e}")
            return []

    def get_playback_timestamps(self, item_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/items/{item_id}/play"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"ABS API Error (get_playback_timestamps): {e}")
            return {}

    def get_completion_status(self, item_id: str) -> bool:
        url = f"{self.base_url}/api/items/{item_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("mediaProgress", {}).get("isFinished", False)
        except requests.RequestException as e:
            logging.error(f"ABS API Error (get_completion_status): {e}")
            return False

    def sync_progress(self, item_id: str, progress: float, is_finished: bool):
        url = f"{self.base_url}/api/me/progress/{item_id}"
        payload = {
            "progress": progress,
            "isFinished": is_finished
        }
        try:
            response = requests.patch(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            logging.info(f"Successfully synced progress to ABS for item {item_id}")
        except requests.RequestException as e:
            logging.error(f"ABS API Error (sync_progress): {e}")


class ProgressHarmonizer:
    def __init__(self, abs_client: AudiobookshelfClient, plex_client: "PlexClient"):
        self.abs_client = abs_client
        self.plex_client = plex_client
        self.dry_run = False
        self.force_direction = None

    def fuzzy_match_title(self, title1: str, title2: str) -> bool:
        # A simple naive matching; normally would use difflib or fuzzywuzzy
        # Since difflib was rejected in the plan review, we use simple lowercase containment
        t1 = title1.lower().strip()
        t2 = title2.lower().strip()
        return t1 == t2 or t1 in t2 or t2 in t1

    def resolve_conflict(self, abs_progress: Dict[str, Any], plex_progress: Dict[str, Any]) -> str:
        if self.force_direction:
            return self.force_direction

        # Determine based on recently updated timestamp
        abs_updated = abs_progress.get("updatedAt", 0)
        plex_updated = plex_progress.get("updatedAt", 0)

        if abs_updated >= plex_updated:
            return "abs-to-plex"
        else:
            return "plex-to-abs"

    def sync(self):
        logging.info("Starting synchronization run...")
        if self.dry_run:
            logging.info("Dry run enabled, no changes will be made.")

        abs_sessions = self.abs_client.get_listening_sessions()
        plex_sessions = self.plex_client.get_sessions()

        if not abs_sessions and not plex_sessions:
            logging.error("Failed to fetch sessions or no sessions available.")
            return

        for abs_session in abs_sessions:
            abs_item_id = abs_session.get("id")
            if not abs_item_id:
                continue

            # Fetch detailed playback and completion data for ABS
            abs_timestamps = self.abs_client.get_playback_timestamps(abs_item_id)
            abs_progress = abs_timestamps.get("progress", abs_session.get("progress", 0))
            abs_updated_at = abs_timestamps.get("updatedAt", abs_session.get("updatedAt", 0))
            is_finished = self.abs_client.get_completion_status(abs_item_id)

            # Compile comprehensive ABS progress dict for conflict resolution
            abs_progress_data = {
                "id": abs_item_id,
                "title": abs_session.get("title", ""),
                "progress": abs_progress,
                "updatedAt": abs_updated_at,
                "isFinished": is_finished
            }

            for plex_session in plex_sessions:
                plex_rating_key = plex_session.get("ratingKey")
                if not plex_rating_key:
                    continue

                # Fetch detailed metadata for Plex
                plex_metadata = self.plex_client.get_library_metadata(plex_rating_key)
                plex_view_offset = plex_metadata.get("viewOffset", plex_session.get("viewOffset", 0))
                plex_updated_at = plex_metadata.get("updatedAt", plex_session.get("updatedAt", 0))

                plex_progress_data = {
                    "ratingKey": plex_rating_key,
                    "title": plex_session.get("title", ""),
                    "viewOffset": plex_view_offset,
                    "updatedAt": plex_updated_at
                }

                if self.fuzzy_match_title(abs_progress_data["title"], plex_progress_data["title"]):
                    logging.info(f"Matched '{abs_progress_data['title']}' with '{plex_progress_data['title']}'")
                    direction = self.resolve_conflict(abs_progress_data, plex_progress_data)

                    if direction == "abs-to-plex":
                        logging.info(f"Syncing {abs_progress_data['title']} progress {abs_progress_data['progress']} to Plex")
                        if not self.dry_run:
                            self.plex_client.sync_progress(plex_rating_key, int(abs_progress_data['progress']), "playing")
                    else:
                        logging.info(f"Syncing {plex_progress_data['title']} progress {plex_progress_data['viewOffset']} to ABS")
                        if not self.dry_run:
                            # Use False for isFinished if we are updating from Plex and it's active
                            self.abs_client.sync_progress(abs_item_id, float(plex_progress_data['viewOffset']), False)

class PlexClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self.headers = {"X-Plex-Token": self.token, "Accept": "application/json"}

    def get_sessions(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/status/sessions"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("MediaContainer", {}).get("Metadata", [])
        except requests.RequestException as e:
            logging.error(f"Plex API Error (get_sessions): {e}")
            return []

    def get_library_metadata(self, rating_key: str) -> Dict[str, Any]:
        url = f"{self.base_url}/library/metadata/{rating_key}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("MediaContainer", {}).get("Metadata", [{}])[0]
        except requests.RequestException as e:
            logging.error(f"Plex API Error (get_library_metadata): {e}")
            return {}

    def sync_progress(self, rating_key: str, view_offset: int, state: str):
        url = f"{self.base_url}/:/timeline"
        params = {
            "ratingKey": rating_key,
            "key": f"/library/metadata/{rating_key}",
            "state": state,
            "time": view_offset,
            "X-Plex-Token": self.token
        }
        try:
            response = requests.post(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            logging.info(f"Successfully synced progress to Plex for item {rating_key}")
        except requests.RequestException as e:
            logging.error(f"Plex API Error (sync_progress): {e}")


def parse_args():
    parser = argparse.ArgumentParser(description="Audiobookshelf to Plex Media Matcher & Progress Sync")
    parser.add_argument("--dry-run", action="store_true", help="Run without making any changes")
    parser.add_argument("--sync-interval", type=int, default=300, help="Sync interval in seconds")
    parser.add_argument("--force-direction", choices=["abs-to-plex", "plex-to-abs"], help="Force sync direction")
    return parser.parse_args()

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args()
    logging.info(f"Starting ABS-Plex Sync Daemon with args: {args}")

    abs_url = os.environ.get("ABS_URL", "http://localhost:13378")
    abs_token = os.environ.get("ABS_TOKEN", "mock_abs_token")
    plex_url = os.environ.get("PLEX_URL", "http://localhost:32400")
    plex_token = os.environ.get("PLEX_TOKEN", "mock_plex_token")

    sync_interval = int(os.environ.get("SYNC_INTERVAL", args.sync_interval))

    abs_client = AudiobookshelfClient(abs_url, abs_token)
    plex_client = PlexClient(plex_url, plex_token)

    harmonizer = ProgressHarmonizer(abs_client, plex_client)
    harmonizer.dry_run = args.dry_run
    harmonizer.force_direction = args.force_direction

    while True:
        harmonizer.sync()
        if args.dry_run or sync_interval <= 0:
            break
        logging.info(f"Sleeping for {sync_interval} seconds...")
        time.sleep(sync_interval)

if __name__ == "__main__":
    main()
