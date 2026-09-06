import argparse
import json
import logging
import sys
from typing import Any, Dict, List

import requests

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class MediaAuditor:
    """Audits Radarr and Sonarr APIs for problematic media."""
    def __init__(self, radarr_url: str = None, sonarr_url: str = None, radarr_key: str = "", sonarr_key: str = ""):
        self.radarr_url = radarr_url
        self.sonarr_url = sonarr_url
        self.radarr_key = radarr_key
        self.sonarr_key = sonarr_key

    def _get(self, url: str, params: dict = None) -> List[Dict[str, Any]]:
        if not params:
            params = {}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching from {url}: {e}")
            return []

    def audit_radarr(self) -> List[Dict[str, Any]]:
        issues = []
        if not self.radarr_url:
            return issues

        url = f"{self.radarr_url.rstrip('/')}/api/v3/movie"
        movies = self._get(url, {"apikey": self.radarr_key})

        for movie in movies:
            has_file = movie.get("hasFile", False)
            monitored = movie.get("monitored", False)
            tmdb_id = movie.get("tmdbId", 0)

            movie_issues = []
            if not has_file:
                movie_issues.append("missing_file")
            if not monitored:
                movie_issues.append("unmonitored")
            if not tmdb_id:
                movie_issues.append("missing_tmdb_id")

            issues.append({
                "id": movie.get("id"),
                "title": movie.get("title"),
                "type": "movie",
                "issues": movie_issues,
                "radarr_data": movie
            })

        return issues

    def audit_sonarr(self) -> List[Dict[str, Any]]:
        issues = []
        if not self.sonarr_url:
            return issues

        url = f"{self.sonarr_url.rstrip('/')}/api/v3/series"
        series_list = self._get(url, {"apikey": self.sonarr_key})

        for series in series_list:
            monitored = series.get("monitored", False)
            tvdb_id = series.get("tvdbId", 0)

            # Simple check at series level. For full episode missing check we'd need episode endpoint,
            # but usually statistics.episodeFileCount < statistics.episodeCount implies missing files.
            stats = series.get("statistics", {})
            episode_count = stats.get("episodeCount", 0)
            episode_file_count = stats.get("episodeFileCount", 0)
            has_missing_files = episode_file_count < episode_count

            series_issues = []
            if has_missing_files:
                series_issues.append("missing_file")
            if not monitored:
                series_issues.append("unmonitored")
            if not tvdb_id:
                series_issues.append("missing_tvdb_id")

            issues.append({
                "id": series.get("id"),
                "title": series.get("title"),
                "type": "series",
                "issues": series_issues,
                "sonarr_data": series
            })

        return issues

class PlexReconciler:
    """Reconciles Arr library with Plex to find unindexed media."""
    def __init__(self, plex_url: str = None, plex_token: str = ""):
        self.plex_url = plex_url
        self.plex_token = plex_token

    def _get(self, url: str, params: dict = None) -> Any:
        if not params:
            params = {}
        headers = {"Accept": "application/json"}
        if self.plex_token:
            headers["X-Plex-Token"] = self.plex_token

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching from {url}: {e}")
            return {}

    def get_plex_items(self) -> List[Dict[str, Any]]:
        if not self.plex_url:
            return []

        # This is a simplified fetch assuming sections endpoint exists and gets all items.
        # In a real scenario we'd query /library/sections, then /library/sections/X/all
        sections_url = f"{self.plex_url.rstrip('/')}/library/sections"
        sections_data = self._get(sections_url)
        directories = sections_data.get("MediaContainer", {}).get("Directory", [])

        all_items = []
        for directory in directories:
            section_id = directory.get("key")
            items_url = f"{self.plex_url.rstrip('/')}/library/sections/{section_id}/all"
            items_data = self._get(items_url)
            metadata = items_data.get("MediaContainer", {}).get("Metadata", [])
            all_items.extend(metadata)

        return all_items

    def reconcile(self, arr_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # This function identifies Arr items that exist but are NOT in Plex (unindexed)
        # We try to match by title as a simplistic approach, or by ID if Guid contains it.
        if not self.plex_url:
            return []

        plex_items = self.get_plex_items()
        plex_titles = {item.get("title", "").lower() for item in plex_items}

        unindexed = []
        for item in arr_items:
            # We only care about items that actually have files.
            # If they don't have files, they obviously won't be in Plex.
            issues = item.get("issues", [])
            if "missing_file" in issues:
                continue

            title = item.get("title", "").lower()
            if title and title not in plex_titles:
                unindexed.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "type": item.get("type"),
                    "issue": "unindexed_in_plex"
                })
        return unindexed

class HealingPlanner:
    """Generates non-destructive remediation tasks."""
    def generate_plan(self, audit_issues: List[Dict[str, Any]], unindexed_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tasks = []

        for issue in audit_issues:
            issues_list = issue.get("issues", [])
            item_id = issue.get("id")
            item_type = issue.get("type")

            if "missing_tmdb_id" in issues_list or "missing_tvdb_id" in issues_list:
                tasks.append({
                    "action": "refresh_metadata",
                    "type": item_type,
                    "id": item_id,
                    "reason": "missing_metadata_id"
                })

            if "missing_file" in issues_list and "unmonitored" not in issues_list:
                tasks.append({
                    "action": "trigger_search",
                    "type": item_type,
                    "id": item_id,
                    "reason": "missing_file"
                })

        for issue in unindexed_issues:
            tasks.append({
                "action": "rescan_item",
                "type": "plex",
                "id": issue.get("id"), # Arr ID in this context for reference
                "title": issue.get("title"),
                "reason": "unindexed"
            })

        return tasks

def main():
    parser = argparse.ArgumentParser(description="Automated Plex/Arr Stack Media Metadata Healer")
    parser.add_argument("--audit-now", action="store_true", help="Perform audit immediately")
    parser.add_argument("--radarr-url", type=str, help="Radarr API URL")
    parser.add_argument("--sonarr-url", type=str, help="Sonarr API URL")
    parser.add_argument("--plex-url", type=str, help="Plex API URL")
    parser.add_argument("--radarr-key", type=str, default="", help="Radarr API Key")
    parser.add_argument("--sonarr-key", type=str, default="", help="Sonarr API Key")
    parser.add_argument("--plex-token", type=str, default="", help="Plex Token")
    parser.add_argument("--dry-run", action="store_true", help="Do not execute any healing tasks, just print them")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    if not args.audit_now:
        parser.print_help()
        sys.exit(0)

    auditor = MediaAuditor(
        radarr_url=args.radarr_url,
        sonarr_url=args.sonarr_url,
        radarr_key=args.radarr_key,
        sonarr_key=args.sonarr_key
    )

    radarr_items = auditor.audit_radarr()
    sonarr_items = auditor.audit_sonarr()
    all_items = radarr_items + sonarr_items

    all_audit_issues = [item for item in all_items if item.get("issues")]

    reconciler = PlexReconciler(plex_url=args.plex_url, plex_token=args.plex_token)
    unindexed_issues = reconciler.reconcile(all_items)

    planner = HealingPlanner()
    plan = planner.generate_plan(all_audit_issues, unindexed_issues)

    result = {
        "audit_issues": all_audit_issues,
        "unindexed_issues": unindexed_issues,
        "healing_plan": plan
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("--- Audit Issues ---")
        for i in all_audit_issues:
            print(f"[{i['type'].upper()}] {i['title']} - Issues: {', '.join(i['issues'])}")

        print("\n--- Unindexed in Plex ---")
        for i in unindexed_issues:
            print(f"[{i['type'].upper()}] {i['title']}")

        print("\n--- Healing Plan ---")
        for t in plan:
            print(f"Action: {t['action']}, Target Type: {t['type']}, ID: {t['id']}, Reason: {t['reason']}")

    if not args.dry_run:
        # In a real scenario, this would execute the tasks via APIs.
        if plan and not args.json:
            print("\nExecuting tasks (Mocked)...")

if __name__ == "__main__":
    main()
