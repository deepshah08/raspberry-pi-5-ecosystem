import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import pytest
import requests_mock
from prometheus_client import REGISTRY
from unittest.mock import MagicMock, patch

from llm_governor import LLMGovernor, main, ProxyHandler

OLLAMA_URL = "http://test-ollama:11434"

@pytest.fixture
def governor():
    return LLMGovernor(ollama_url=OLLAMA_URL, idle_timeout=300, dry_run=False, is_json=True)

def test_model_discovery(governor, requests_mock):
    mock_ps_response = {
        "models": [
            {"name": "llama2", "size": 4000000000}
        ]
    }
    requests_mock.get(f"{OLLAMA_URL}/api/ps", json=mock_ps_response)

    models = governor.get_loaded_models()
    assert len(models) == 1
    assert models[0]["name"] == "llama2"

def test_metrics_initialization(governor, requests_mock):
    mock_ps_response = {
        "models": [
            {"name": "mistral", "size": 8000000000}
        ]
    }
    requests_mock.get(f"{OLLAMA_URL}/api/ps", json=mock_ps_response)

    governor.run_audit()

    loaded_metric = REGISTRY.get_sample_value('homelab_llm_loaded_models')
    assert loaded_metric == 1.0

    memory_metric = REGISTRY.get_sample_value('homelab_llm_memory_bytes', labels={'model_name': 'mistral'})
    assert memory_metric == 8000000000.0

def test_idle_timeout_eviction(governor, requests_mock, monkeypatch):
    # Mock time so we can easily fast forward
    start_time = 1000
    mock_now = start_time
    monkeypatch.setattr(time, "time", lambda: mock_now)

    mock_ps_response = {
        "models": [
            {"name": "llama2", "size": 4000000000}
        ]
    }
    requests_mock.get(f"{OLLAMA_URL}/api/ps", json=mock_ps_response)

    # First audit - should mark model as seen
    governor.run_audit()
    assert governor.model_last_active["llama2"] == start_time

    # Fast forward beyond timeout
    mock_now = start_time + 400

    # Mock the unload call
    unload_mock = requests_mock.post(f"{OLLAMA_URL}/api/generate", json={"status": "success"})

    # Second audit - should trigger unload
    governor.run_audit()

    assert unload_mock.called
    assert unload_mock.last_request.json() == {"model": "llama2", "keep_alive": 0}

def test_concurrency_throttling(governor):
    # Under limit
    assert governor.check_concurrency() is True
    assert governor.current_requests == 1

    # At limit
    assert governor.check_concurrency() is True
    assert governor.current_requests == 2

    # Over limit
    assert governor.check_concurrency() is False
    assert governor.current_requests == 2

    # Release
    governor.release_concurrency()
    assert governor.current_requests == 1
    assert governor.check_concurrency() is True

def test_cli_flags(monkeypatch, requests_mock):
    mock_ps_response = {"models": []}
    requests_mock.get("http://localhost:11434/api/ps", json=mock_ps_response)

    # Test --audit-now
    monkeypatch.setattr(sys, "argv", ["llm_governor.py", "--audit-now", "--idle-timeout", "100"])

    # Should run successfully without starting loop
    main()

def test_proxy_handler_too_many_requests(governor):
    governor.max_concurrency = 0 # force 429

    # Mock request handler
    mock_request = MagicMock()
    mock_request.makefile = MagicMock(return_value=MagicMock())
    mock_client_address = ('127.0.0.1', 12345)
    mock_server = MagicMock()

    # Don't call super().__init__ in the test, just test do_POST logic
    # which is easier than setting up all the BaseHTTPRequestHandler stuff
    with patch('llm_governor.ProxyHandler.__init__', return_value=None):
        handler = ProxyHandler(governor, mock_request, mock_client_address, mock_server)
        handler.governor = governor

        # Mock the underlying HTTP components that do_POST uses to write the response
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        handler.do_POST()

        handler.send_response.assert_called_with(429)
