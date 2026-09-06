import argparse
import sys
import json
import requests
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional

class LibraryAuditor:
    def __init__(self, abs_url: Optional[str], dry_run: bool = False):
        self.abs_url = abs_url.rstrip("/") if abs_url else None
        self.dry_run = dry_run

    def fetch_libraries(self) -> List[Dict[str, Any]]:
        if not self.abs_url:
            return []
        url = f"{self.abs_url}/api/libraries"
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get("libraries", [])

    def fetch_library_items(self, library_id: str) -> List[Dict[str, Any]]:
        if not self.abs_url:
            return []
        url = f"{self.abs_url}/api/libraries/{library_id}/items"
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get("results", [])

    def audit_audiobookshelf(self) -> List[Dict[str, Any]]:
        issues = []
        if not self.abs_url:
            return issues

        try:
            libraries = self.fetch_libraries()
        except requests.RequestException as e:
            issues.append({"type": "api_error", "message": str(e), "source": "audiobookshelf"})
            return issues

        for library in libraries:
            library_id = library.get("id")
            if not library_id:
                continue

            try:
                items = self.fetch_library_items(library_id)
            except requests.RequestException as e:
                issues.append({"type": "api_error", "message": f"Failed fetching items for library {library_id}: {str(e)}", "source": "audiobookshelf"})
                continue

            for item in items:
                item_id = item.get("id")
                media = item.get("media", {})
                metadata = media.get("metadata", {})

                missing = []

                # Check for missing cover
                if not media.get("coverPath") and not media.get("hasCover"):
                    missing.append("cover")

                # Check for author
                authors = metadata.get("authors", [])
                author_name = metadata.get("authorName")
                if not authors and not author_name:
                    missing.append("author")

                # Check for ISBN
                if not metadata.get("isbn"):
                    missing.append("isbn")

                if missing:
                    issues.append({
                        "type": "missing_metadata",
                        "source": "audiobookshelf",
                        "item_id": item_id,
                        "title": metadata.get("title", "Unknown Title"),
                        "missing_fields": missing,
                        "remediation": f"Fetch {', '.join(missing)} from open APIs and trigger rescan."
                    })

        return issues


class OPDSValidator:
    def __init__(self, calibre_url: Optional[str]):
        self.calibre_url = calibre_url

    def validate_feed(self) -> List[Dict[str, Any]]:
        issues = []
        if not self.calibre_url:
            return issues

        try:
            response = requests.get(self.calibre_url)
            response.raise_for_status()
            content = response.text

            # Check XML Syntax
            try:
                root = ET.fromstring(content)
                # Check if it looks like an OPDS/Atom feed
                if not root.tag.endswith('}feed') and root.tag != 'feed':
                    issues.append({
                        "type": "opds_validation_error",
                        "source": "calibre",
                        "message": "Root element is not 'feed'. Invalid OPDS structure.",
                    })
            except ET.ParseError as e:
                issues.append({
                    "type": "opds_validation_error",
                    "source": "calibre",
                    "message": f"XML parsing failed: {str(e)}",
                })
        except requests.RequestException as e:
             issues.append({"type": "api_error", "message": str(e), "source": "calibre"})

        return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated Audiobookshelf / Calibre Ebook Metadata & OPDS Sentry")
    parser.add_argument("--audit-now", action="store_true", help="Perform an immediate audit")
    parser.add_argument("--abs-url", type=str, help="Audiobookshelf URL")
    parser.add_argument("--calibre-url", type=str, help="Calibre-Web OPDS URL")
    parser.add_argument("--dry-run", action="store_true", help="Run without applying changes or sending modifications")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.audit_now:
        all_issues = []

        if args.abs_url:
            auditor = LibraryAuditor(abs_url=args.abs_url, dry_run=args.dry_run)
            abs_issues = auditor.audit_audiobookshelf()
            all_issues.extend(abs_issues)

        if args.calibre_url:
            validator = OPDSValidator(calibre_url=args.calibre_url)
            calibre_issues = validator.validate_feed()
            all_issues.extend(calibre_issues)

        if args.json:
            print(json.dumps(all_issues, indent=2))
        else:
            for issue in all_issues:
                print(f"[{issue.get('source', 'unknown').upper()}] {issue.get('type')}: {issue.get('title', issue.get('message', ''))}")
                if 'missing_fields' in issue:
                    print(f"  Missing: {', '.join(issue['missing_fields'])}")
                    print(f"  Remediation: {issue['remediation']}")

if __name__ == "__main__":
    main()
