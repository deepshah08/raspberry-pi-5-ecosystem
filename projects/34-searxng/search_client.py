import requests
from typing import Dict, Any, List, Optional
import json

class SearXNGClient:
    """Client for interacting with a local SearXNG meta-search gateway."""

    def __init__(self, base_url: str = "http://localhost:8888"):
        self.base_url = base_url
        self.search_url = f"{self.base_url}/search"

    def search(
        self,
        query: str,
        categories: Optional[List[str]] = None,
        engines: Optional[List[str]] = None,
        language: str = "en",
        pageno: int = 1,
        time_range: Optional[str] = None,
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        Execute a search query against SearXNG and return the JSON response.
        """
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "pageno": pageno
        }

        if categories:
            params["categories"] = ",".join(categories)
        if engines:
            params["engines"] = ",".join(engines)
        if time_range:
            params["time_range"] = time_range

        try:
            response = requests.get(self.search_url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise TimeoutError(f"Search request timed out after {timeout} seconds.")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Search request failed: {e}")

    def search_as_markdown(self, query: str, **kwargs) -> str:
        """
        Execute a search query and format the results as markdown.
        """
        results_json = self.search(query, **kwargs)
        return self._format_as_markdown(results_json)

    def _format_as_markdown(self, results_json: Dict[str, Any]) -> str:
        """
        Format SearXNG JSON results into a clean markdown string suitable for LLMs.
        """
        if not results_json.get("results"):
            return "No results found."

        markdown_lines = []
        for i, result in enumerate(results_json.get("results", [])):
            title = result.get("title", "No Title")
            url = result.get("url", "#")
            content = result.get("content", "")
            if not content:
                content = result.get("snippet", "No snippet available.")

            markdown_lines.append(f"### {i+1}. [{title}]({url})")
            if content:
                # Remove newlines in snippets to keep markdown clean
                clean_content = content.replace('\n', ' ').strip()
                markdown_lines.append(f"{clean_content}")
            markdown_lines.append("") # Empty line for spacing

        return "\n".join(markdown_lines).strip()
