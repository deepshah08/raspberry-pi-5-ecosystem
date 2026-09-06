import pytest
from qdrant_client.http.models import Distance, UpdateStatus
import sys
import os

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from vector_client import OmniSearchClient

@pytest.fixture
def memory_client():
    client = OmniSearchClient(memory=True)
    yield client

def test_init_collection(memory_client):
    collection_name = "test_collection"
    memory_client.init_collection(collection_name=collection_name, vector_size=512)

    # Verify collection exists
    collections = memory_client.client.get_collections().collections
    assert any(c.name == collection_name for c in collections)

def test_batch_upsert_valid(memory_client):
    collection_name = "test_upsert"
    memory_client.init_collection(collection_name=collection_name, vector_size=3)

    points = [
        {
            "id": 1,
            "vector": [1.0, 0.0, 0.0],
            "payload": {
                "file_path": "/test/1.jpg",
                "timestamp_sec": 10.0,
                "item_type": "photo",
                "title": "Test 1",
                "tags": ["test"]
            }
        }
    ]

    res = memory_client.batch_upsert(collection_name, points)
    assert res.status == UpdateStatus.COMPLETED

def test_batch_upsert_invalid_schema(memory_client):
    collection_name = "test_upsert_invalid"
    memory_client.init_collection(collection_name=collection_name, vector_size=3)

    points = [
        {
            "id": 1,
            "vector": [1.0, 0.0, 0.0],
            "payload": {
                "file_path": "/test/1.jpg",
                # missing timestamp_sec, item_type, title, tags
            }
        }
    ]

    with pytest.raises(ValueError, match="Missing required payload key"):
        memory_client.batch_upsert(collection_name, points)

def test_search_top_k(memory_client):
    collection_name = "test_search"
    memory_client.init_collection(collection_name=collection_name, vector_size=3)

    points = [
        {
            "id": 1,
            "vector": [1.0, 0.0, 0.0],
            "payload": {
                "file_path": "/test/1.jpg",
                "timestamp_sec": 10.0,
                "item_type": "photo",
                "title": "Test 1",
                "tags": ["test"]
            }
        },
        {
            "id": 2,
            "vector": [0.0, 1.0, 0.0],
            "payload": {
                "file_path": "/test/2.jpg",
                "timestamp_sec": 20.0,
                "item_type": "photo",
                "title": "Test 2",
                "tags": ["test"]
            }
        }
    ]
    memory_client.batch_upsert(collection_name, points)

    # Search for vector closest to [1.0, 0.0, 0.0]
    results = memory_client.search(collection_name, query_vector=[1.0, 0.0, 0.0], top_k=1, threshold=0.5)

    assert len(results) == 1
    assert results[0].id == 1

def test_search_threshold(memory_client):
    collection_name = "test_search_threshold"
    memory_client.init_collection(collection_name=collection_name, vector_size=3)

    points = [
        {
            "id": 1,
            "vector": [1.0, 0.0, 0.0],
            "payload": {
                "file_path": "/test/1.jpg",
                "timestamp_sec": 10.0,
                "item_type": "photo",
                "title": "Test 1",
                "tags": ["test"]
            }
        }
    ]
    memory_client.batch_upsert(collection_name, points)

    # Search with very high threshold, shouldn't match anything close to orthogonal
    results = memory_client.search(collection_name, query_vector=[0.0, 1.0, 0.0], top_k=1, threshold=0.9)
    assert len(results) == 0
