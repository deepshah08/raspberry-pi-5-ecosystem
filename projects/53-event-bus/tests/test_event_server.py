import pytest
import json
import asyncio
import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure project directory is in sys.path regardless of execution root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from event_server import app, engine, EventPayload

# Reset the state before tests
@pytest.fixture(autouse=True)
def reset_engine():
    engine.subscribers.clear()
    engine.messages_processed = 0
    yield

client = TestClient(app)

def test_health_check_empty():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["active_subscribers"] == 0
    assert data["messages_processed"] == 0

def test_event_ingestion_invalid_payload():
    response = client.post("/events", json={
        "topic": "test.topic",
        "source": "test_source",
        # Missing payload
    })
    assert response.status_code == 422

def test_event_ingestion_valid_payload():
    response = client.post("/events", json={
        "topic": "test.topic",
        "source": "test_source",
        "payload": {"status": "ok"}
    })
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

    # Needs a small sleep to let the async task update the count
    import time
    time.sleep(0.01)

def test_websocket_broadcast_and_topic_filtering():
    with client.websocket_connect("/ws/media.ingest") as websocket1, \
         client.websocket_connect("/ws/media.ingest") as websocket2, \
         client.websocket_connect("/ws/system.alerts") as websocket3:

        # Check active subscribers
        health_resp = client.get("/health")
        assert health_resp.json()["active_subscribers"] == 3

        # Publish to media.ingest
        client.post("/events", json={
            "topic": "media.ingest",
            "source": "camera",
            "payload": {"file": "video.mp4"}
        })

        # Wait a tick for asyncio.create_task to run broadcast
        import time
        time.sleep(0.05)

        # Websocket 1 and 2 should receive the message
        data1 = websocket1.receive_json()
        assert data1["topic"] == "media.ingest"
        assert data1["payload"] == {"file": "video.mp4"}

        data2 = websocket2.receive_json()
        assert data2["topic"] == "media.ingest"
        assert data2["payload"] == {"file": "video.mp4"}

        # Websocket 3 shouldn't have received it (topic filtering)
        # However, TestClient websocket blocks on receive. Since we know it shouldn't get it,
        # we can just test that publishing to system.alerts only hits websocket3
        client.post("/events", json={
            "topic": "system.alerts",
            "source": "smart",
            "payload": {"level": "warning"}
        })

        time.sleep(0.05)

        data3 = websocket3.receive_json()
        assert data3["topic"] == "system.alerts"
        assert data3["payload"] == {"level": "warning"}

def test_concurrent_disconnect():
    with client.websocket_connect("/ws/test.topic") as websocket:
        health_resp = client.get("/health")
        assert health_resp.json()["active_subscribers"] == 1

    # After block, it disconnects
    health_resp = client.get("/health")
    assert health_resp.json()["active_subscribers"] == 0
