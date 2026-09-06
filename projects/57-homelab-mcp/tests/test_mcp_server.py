import sys
from pathlib import Path
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

# Ensure standalone test execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import server, homelab_status, omnisearch_query, smart_drive_status, cluster_services, trigger_backup

@pytest.fixture
def mock_httpx():
    with patch("server.homelab_client.client") as mock_client:
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        yield mock_client

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=None, response=self)

@pytest.mark.asyncio
async def test_tool_registration():
    tools = [t.name for t in server._tool_manager.list_tools()]
    assert "homelab_status" in tools
    assert "omnisearch_query" in tools
    assert "smart_drive_status" in tools
    assert "cluster_services" in tools
    assert "trigger_backup" in tools

@pytest.mark.asyncio
async def test_homelab_status_success(mock_httpx):
    mock_response = MockResponse({"cpu": 10})
    mock_httpx.get.return_value = mock_response

    res = await homelab_status(target="all")
    assert res["nas"]["status"] == "ok"
    assert res["pi"]["status"] == "ok"
    assert mock_httpx.get.call_count == 2

@pytest.mark.asyncio
async def test_omnisearch_query_success(mock_httpx):
    mock_response = MockResponse({"results": ["receipt1.jpg"]})
    mock_httpx.get.return_value = mock_response

    res = await omnisearch_query(query="test", limit=5)
    mock_httpx.get.assert_called_with("http://192.168.1.80:8008/search", params={"q": "test", "limit": 5})
    assert res == {"results": ["receipt1.jpg"]}

@pytest.mark.asyncio
async def test_smart_drive_status_success(mock_httpx):
    mock_response = MockResponse({"tbw": 100})
    mock_httpx.get.return_value = mock_response

    res = await smart_drive_status()
    mock_httpx.get.assert_called_with("http://192.168.1.80:9106/metrics", params=None)
    assert res == {"tbw": 100}

@pytest.mark.asyncio
async def test_cluster_services_success(mock_httpx):
    mock_response = MockResponse({"services": []})
    mock_httpx.get.return_value = mock_response

    res = await cluster_services()
    mock_httpx.get.assert_called_with("http://192.168.1.80:8000/api/cluster/status", params=None)
    assert res == {"services": []}

@pytest.mark.asyncio
async def test_trigger_backup_success(mock_httpx):
    mock_response = MockResponse({"status": "triggered"})
    mock_httpx.post.return_value = mock_response

    # Verify dry_run default is True
    res = await trigger_backup()
    mock_httpx.post.assert_called_with("http://192.168.1.80:8000/api/backup/trigger", json={"dry_run": True})
    assert res == {"status": "triggered"}

    res2 = await trigger_backup(dry_run=False)
    mock_httpx.post.assert_called_with("http://192.168.1.80:8000/api/backup/trigger", json={"dry_run": False})

@pytest.mark.asyncio
async def test_homelab_status_timeout(mock_httpx):
    import httpx
    mock_httpx.get.side_effect = httpx.TimeoutException("Timeout")

    res = await homelab_status(target="nas")
    assert res["nas"]["status"] == "unreachable"
    assert res["nas"]["error"]["error"] == "timeout"

@pytest.mark.asyncio
async def test_homelab_status_http_error(mock_httpx):
    mock_response = MockResponse({"error": "not found"}, status_code=404)
    # We patch get to return it, and HTTPStatusError will be raised in homelab_client when get is called and raise_for_status is invoked.
    # Actually mock_httpx represents httpx.AsyncClient. So let's make it raise an exception or mock the response
    import httpx
    request = httpx.Request("GET", "http://test")

    # We use a mocked HTTPStatusError since httpx requires request and response args
    # But since we mock homelab_client.client which is httpx.AsyncClient, we need to mock raise_for_status via homelab_client's implementation
    # wait, homelab_client.client.get returns a response, and then homelab_client calls response.raise_for_status()
    # Let's mock response raise_for_status to raise

    mock_response_obj = MockResponse({"error": "not found"}, status_code=404)
    mock_httpx.get.return_value = mock_response_obj

    res = await homelab_status(target="nas")
    assert res["nas"]["status"] == "unreachable"
    assert res["nas"]["error"]["error"] == "http_error"
    assert res["nas"]["error"]["status_code"] == 404

@pytest.mark.asyncio
async def test_omnisearch_query_general_exception(mock_httpx):
    mock_httpx.get.side_effect = Exception("Unknown Error")

    res = await omnisearch_query(query="test", limit=5)
    assert res["error"] == "request_failed"
    assert "Unknown Error" in res["message"]
