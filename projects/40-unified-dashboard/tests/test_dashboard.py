import pytest
from fastapi.testclient import TestClient
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from app import app
from unittest.mock import patch, MagicMock, AsyncMock

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "Unified Dashboard" in response.text
    assert "id=\"search-input\"" in response.text

def test_static_files():
    response_css = client.get("/static/style.css")
    assert response_css.status_code == 200
    assert "background-color" in response_css.text

    response_js = client.get("/static/app.js")
    assert response_js.status_code == 200
    assert "initSearch" in response_js.text

def test_proxy_search_mock(mocker):
    # Mock httpx.AsyncClient.get to simulate external API call failure, thus hitting the fallback
    mock_get = mocker.patch("httpx.AsyncClient.get")
    mock_get.side_effect = Exception("Mocked error")

    response = client.get("/api/search?q=test")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert data["results"][0]["title"] == "Result for test"

def test_proxy_search_success(mocker):
    # Mock successful external API call
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": [{"title": "Real Result"}]}

    # We must patch AsyncClient.__aenter__ to return a mock client with our mocked get
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    mock_async_client = mocker.patch("httpx.AsyncClient")
    mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)

    response = client.get("/api/search?q=test")
    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["title"] == "Real Result"

def test_proxy_briefing_mock(mocker):
    mock_get = mocker.patch("httpx.AsyncClient.get")
    mock_get.side_effect = Exception("Mocked error")

    response = client.get("/api/briefing")
    assert response.status_code == 200
    data = response.json()
    assert "audio_url" in data
    assert data["title"] == "Latest Morning Briefing (Mock)"

def test_proxy_status_mock(mocker):
    mock_get = mocker.patch("httpx.AsyncClient.get")
    mock_get.side_effect = Exception("Mocked error")

    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
