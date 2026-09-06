import os
import sys
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# IMPORTANT: Insert at index 0 and clear any pre-existing generic 'server' modules
# from sys.modules to prevent shadowing from `08-trip-drop/server.py`
import sys
import os

target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if target_path not in sys.path:
    sys.path.insert(0, target_path)

if 'server' in sys.modules:
    del sys.modules['server']

import importlib.util

spec = importlib.util.spec_from_file_location("omnisearch_server", os.path.join(os.path.dirname(__file__), "..", "server.py"))
omnisearch_server = importlib.util.module_from_spec(spec)
sys.modules["omnisearch_server"] = omnisearch_server
spec.loader.exec_module(omnisearch_server)

app = omnisearch_server.app
client = TestClient(app)

class MockPoint:
    def __init__(self, score, payload):
        self.score = score
        self.payload = payload

@pytest.fixture
def mock_qdrant_client():
    with patch.object(omnisearch_server, "get_qdrant_client", create=True) as mock:
        mock_client = MagicMock()
        mock.return_value = mock_client
        yield mock_client

@pytest.fixture
def mock_get_text_embedding():
    with patch.object(omnisearch_server, "get_text_embedding", create=True) as mock:
        mock.return_value = [0.2] * 512
        yield mock

def test_search_endpoint(mock_qdrant_client, mock_get_text_embedding):
    mock_qdrant_client.search.return_value = [
        MockPoint(
            score=0.95,
            payload={
                "file_path": "/media/test1.jpg",
                "title": "Test Image 1",
                "preview_url": "http://localhost/test1.jpg"
            }
        ),
        MockPoint(
            score=0.85,
            payload={
                "file_path": "/media/test2.jpg",
                "title": "Test Image 2",
                "preview_url": "http://localhost/test2.jpg"
            }
        )
    ]

    response = client.get("/search?q=test query&limit=5&threshold=0.8")

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 2

    assert data["results"][0]["file_path"] == "/media/test1.jpg"
    assert data["results"][0]["title"] == "Test Image 1"
    assert data["results"][0]["score"] == 0.95

    mock_get_text_embedding.assert_called_once_with("test query")
    mock_qdrant_client.search.assert_called_once()

def test_health_endpoint(mock_qdrant_client, mock_get_text_embedding):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["qdrant"] == "ok"
    assert data["embedder"] == "ok"

def test_search_missing_query():
    response = client.get("/search")
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert data["detail"][0]["loc"] == ["query", "q"]
    assert data["detail"][0]["msg"] == "Field required"
