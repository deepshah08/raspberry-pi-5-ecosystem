import argparse
import sys
import json
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set, Tuple, Optional, Dict, Any

class Crawler:
    def __init__(self, base_urls: List[str], depth: int, max_concurrency: int, dry_run: bool):
        self.base_urls = base_urls
        self.max_depth = depth
        self.max_concurrency = max_concurrency
        self.dry_run = dry_run

        self.visited: Set[str] = set()
        self.results: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.session = requests.Session()

    def _is_internal(self, url: str, base_url: str) -> bool:
        return urlparse(url).netloc == urlparse(base_url).netloc

    def fetch_url(self, url: str, method: str = "GET") -> Tuple[Optional[requests.Response], float, Optional[str]]:
        start_time = time.time()
        try:
            if method == "HEAD":
                response = self.session.head(url, timeout=5, allow_redirects=True)
            else:
                response = self.session.get(url, timeout=5)

            latency = (time.time() - start_time) * 1000
            return response, latency, None
        except requests.exceptions.HTTPError as e:
            latency = (time.time() - start_time) * 1000
            return getattr(e, 'response', None), latency, None
        except requests.exceptions.RequestException as e:
            latency = (time.time() - start_time) * 1000
            if hasattr(e, 'response') and e.response is not None:
                return e.response, latency, None
            return None, latency, str(e)
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return None, latency, str(e)

    def extract_links(self, html: str, base_url: str) -> Set[str]:
        soup = BeautifulSoup(html, "html.parser")
        links = set()

        for tag in soup.find_all(['a', 'link']):
            href = tag.get('href')
            if href:
                links.add(urljoin(base_url, href))

        for tag in soup.find_all(['script', 'img', 'source']):
            src = tag.get('src')
            if src:
                links.add(urljoin(base_url, src))

        return links

    def process_url(self, url: str, current_depth: int, is_asset: bool = False) -> List[Tuple[str, int, bool]]:
        if url in self.visited:
            return []

        self.visited.add(url)

        method = "HEAD" if is_asset else "GET"
        response, latency, error = self.fetch_url(url, method)

        result = {
            "url": url,
            "latency_ms": round(latency, 2),
            "status_code": response.status_code if response is not None else None,
            "error": error,
            "is_asset": is_asset,
            "depth": current_depth
        }

        is_error = False

        if response is not None and response.status_code >= 400:
            result["error"] = f"HTTP {response.status_code}"
            is_error = True
        elif error:
            is_error = True

        if latency > 1000:
            result["slow"] = True

        if is_error or result.get("slow"):
            self.errors.append(result)

        self.results.append(result)

        next_urls: List[Tuple[str, int, bool]] = []
        # If it's a structural error (4xx/5xx or exception), we probably shouldn't or can't extract links.
        # But if it's just slow, we can still extract links if the response is valid HTML.
        if not is_error and not is_asset and current_depth < self.max_depth and response and 'text/html' in response.headers.get('Content-Type', ''):
            links = self.extract_links(response.text, url)
            for link in links:
                if link.startswith('http'):
                    is_internal = any(self._is_internal(link, base) for base in self.base_urls)
                    if is_internal:
                        # Heuristic to guess if it's an asset based on extension or tag origin
                        asset_exts = ('.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.woff', '.woff2', '.ttf', '.eot')
                        is_link_asset = link.lower().endswith(asset_exts)
                        next_urls.append((link, current_depth + 1, is_link_asset))

        return next_urls

    def run(self) -> Dict[str, Any]:
        queue = [(url, 0, False) for url in self.base_urls]

        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            while queue:
                futures = {executor.submit(self.process_url, url, depth, is_asset): url for url, depth, is_asset in queue}
                queue = []
                for future in as_completed(futures):
                    next_urls = future.result()
                    for next_url in next_urls:
                        if next_url[0] not in self.visited:
                            queue.append(next_url)

        return {
            "total_scanned": len(self.results),
            "errors": self.errors,
            "results": self.results
        }

def main():
    parser = argparse.ArgumentParser(description="Homelab Synthetic HTTP 4xx/5xx Broken Link & Asset Crawler")
    parser.add_argument("--crawl-now", action="store_true", help="Start crawling immediately")
    parser.add_argument("--base-urls", type=str, help="Comma-separated list of base URLs to crawl")
    parser.add_argument("--depth", type=int, default=2, help="Maximum crawl depth (default: 2)")
    parser.add_argument("--max-concurrency", type=int, default=3, help="Maximum concurrent requests (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without emitting alerts")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    if args.crawl_now:
        if not args.base_urls:
            print("Error: --base-urls must be provided with --crawl-now", file=sys.stderr)
            sys.exit(1)

        base_urls = [url.strip() for url in args.base_urls.split(",")]
        crawler = Crawler(
            base_urls=base_urls,
            depth=args.depth,
            max_concurrency=args.max_concurrency,
            dry_run=args.dry_run
        )
        report = crawler.run()

        if not crawler.dry_run:
            # Emitting alerts would normally happen here (e.g., sending to Slack, PagerDuty, etc.)
            pass

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"Crawl completed. Total scanned: {report['total_scanned']}")
            if crawler.dry_run:
                print("[DRY RUN] No alerts were emitted.")

            if report['errors']:
                print("\nErrors found:")
                for err in report['errors']:
                    print(f"- {err['url']} (Status: {err['status_code']}, Error: {err['error']}, Latency: {err['latency_ms']}ms)")
            else:
                print("No errors found.")

if __name__ == "__main__":
    main()
