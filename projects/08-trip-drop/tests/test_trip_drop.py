import pytest
import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from server import app

@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client

def test_health_and_peers(client):
    res = client.get('/health')
    assert res.status_code == 200
    assert res.json()['status'] == 'ok'
    
    res = client.get('/peers')
    assert res.status_code == 200
    assert 'peers' in res.json()

def test_upload(client):
    res = client.post('/upload/sample.txt', content=b'TripDrop sample payload')
    assert res.status_code == 200
    assert res.json()['status'] == 'success'
    if os.path.exists('uploads/sample.txt'):
        os.remove('uploads/sample.txt')
