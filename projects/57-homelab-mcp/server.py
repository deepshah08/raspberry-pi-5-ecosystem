import asyncio
import logging
import httpx
from typing import Optional, Dict, Any, List
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("homelab-mcp")

# MCP Server definition
server = FastMCP("homelab-mcp")

# HTTP Client wrapper with timeout and error handling
class HomelabClient:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=self.timeout)

    async def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            # If the response is json, try to parse it, otherwise return text
            try:
                return response.json()
            except ValueError:
                return {"status": "success", "data": response.text}
        except httpx.TimeoutException:
            logger.error(f"Timeout querying {url}")
            return {"error": "timeout", "message": f"Timeout querying {url}"}
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error querying {url}: {e.response.status_code}")
            return {"error": "http_error", "status_code": e.response.status_code, "message": str(e)}
        except Exception as e:
            logger.error(f"Error querying {url}: {str(e)}")
            return {"error": "request_failed", "message": str(e)}

    async def post(self, url: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            response = await self.client.post(url, json=json)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"status": "success", "data": response.text}
        except httpx.TimeoutException:
            logger.error(f"Timeout querying {url}")
            return {"error": "timeout", "message": f"Timeout querying {url}"}
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error querying {url}: {e.response.status_code}")
            return {"error": "http_error", "status_code": e.response.status_code, "message": str(e)}
        except Exception as e:
            logger.error(f"Error querying {url}: {str(e)}")
            return {"error": "request_failed", "message": str(e)}

homelab_client = HomelabClient(timeout=5.0)


@server.tool()
async def homelab_status(target: str = "all") -> Dict[str, Any]:
    """
    Queries cluster health, node RAM/CPU usage, and temperatures across NAS (192.168.1.80) and Pi 5 (192.168.1.92).

    Args:
        target: Target node to query ("nas", "pi", or "all"). Defaults to "all".
    """
    results = {}

    if target in ["nas", "all"]:
        # Mocking the actual endpoint since one isn't definitively provided, but utilizing the client wrapper
        # In a real scenario, this might hit a node-exporter or custom labctl api
        nas_res = await homelab_client.get("http://192.168.1.80:9100/metrics")
        # Fallback to mock data if it fails, ensuring the tool always returns structural data
        if "error" in nas_res:
            results["nas"] = {"status": "unreachable", "error": nas_res}
        else:
            results["nas"] = {"status": "ok", "mock_metrics": "available"}

    if target in ["pi", "all"]:
        pi_res = await homelab_client.get("http://192.168.1.92:9100/metrics")
        if "error" in pi_res:
            results["pi"] = {"status": "unreachable", "error": pi_res}
        else:
            results["pi"] = {"status": "ok", "mock_metrics": "available"}

    return results


@server.tool()
async def omnisearch_query(query: str, limit: int = 5) -> Dict[str, Any]:
    """
    Queries semantic multimodal search engine on port 8008 for indexed media and receipts.

    Args:
        query: The search string to query.
        limit: Max results to return.
    """
    url = "http://192.168.1.80:8008/search"
    # Assuming the omnisearch API takes a query parameter. Adjust according to standard search API conventions.
    res = await homelab_client.get(url, params={"q": query, "limit": limit})
    return res


@server.tool()
async def smart_drive_status() -> Dict[str, Any]:
    """
    Queries S.M.A.R.T. Sentinel on port 9106 for NVMe TBW wear and HDD standby states (zero wakeups).
    """
    url = "http://192.168.1.80:9106/metrics"
    res = await homelab_client.get(url)
    return res


@server.tool()
async def cluster_services() -> Dict[str, Any]:
    """
    Lists active docker containers, endpoints, and health status from orchestrator.
    """
    url = "http://192.168.1.80:8000/api/cluster/status"
    res = await homelab_client.get(url)
    return res


@server.tool()
async def trigger_backup(dry_run: bool = True) -> Dict[str, Any]:
    """
    Dry-run or on-demand trigger for SMR backup orchestrator.
    Requires dry-run parameter (default True) as safety measure.

    Args:
        dry_run: Whether to perform a dry-run (safe) or actual backup. Defaults to True.
    """
    url = "http://192.168.1.80:8000/api/backup/trigger"
    res = await homelab_client.post(url, json={"dry_run": dry_run})
    return res


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Homelab MCP Server")
    parser.add_argument("--transport", type=str, choices=["stdio", "sse"], default="stdio", help="Transport type (stdio or sse)")
    parser.add_argument("--port", type=int, default=8090, help="Port for SSE transport")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host for SSE transport")

    args = parser.parse_args()

    if args.transport == "sse":
        logger.info(f"Starting SSE transport on {args.host}:{args.port}")
        # Need to run async, mcp server has run_sse_async but standard library asyncio provides run
        asyncio.run(server.run_sse_async(host=args.host, port=args.port))
    else:
        logger.info("Starting stdio transport")
        asyncio.run(server.run_stdio_async())

if __name__ == "__main__":
    main()
