import pytest
from fastapi.testclient import TestClient
import httpx
from gateway import app, state, MAX_CONCURRENCY, semaphore
import asyncio
import json

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    state.active_inference_count = 0
    state.queue_depth = 0

    import gateway
    gateway.semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

def test_health_ok(mocker):
    mock_resp = mocker.Mock()
    mock_resp.status_code = 200

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__.return_value.get.return_value = mock_resp

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ollama_status"] == "ok"
    assert "ollama_latency_seconds" in data
    assert data["queue_depth"] == 0
    assert data["active_inference_count"] == 0

def test_health_degraded(mocker):
    mock_resp = mocker.Mock()
    mock_resp.status_code = 500

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__.return_value.get.return_value = mock_resp

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["ollama_status"] == "error"

def test_list_models(mocker):
    mock_resp = mocker.Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "llama3:latest"},
            {"name": "mistral:latest"}
        ]
    }

    mock_client = mocker.AsyncMock()
    mock_client.__aenter__.return_value.get.return_value = mock_resp

    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) == 2
    assert data["data"][0]["id"] == "llama3:latest"
    assert data["data"][0]["object"] == "model"

@pytest.mark.asyncio
async def test_chat_completions_non_streaming(mocker):
    from gateway import app
    from httpx import AsyncClient
    import gateway

    mock_resp = mocker.Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "llama3",
        "created_at": "2023-08-04T19:22:45.499127Z",
        "message": {
            "role": "assistant",
            "content": "The sky is blue because of Rayleigh scattering."
        },
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 20
    }

    mock_client = mocker.AsyncMock()
    mock_client.build_request.return_value = mocker.Mock()
    mock_client.send.return_value = mock_resp
    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    response = client.post("/v1/chat/completions", json={
        "model": "llama3",
        "messages": [{"role": "user", "content": "Why is the sky blue?"}],
        "stream": False
    })

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "llama3"
    assert data["choices"][0]["message"]["content"] == "The sky is blue because of Rayleigh scattering."
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"]["total_tokens"] == 30

@pytest.mark.asyncio
async def test_chat_completions_streaming(mocker):
    from gateway import app
    from httpx import AsyncClient

    mock_chunks = [
        b'{"model":"llama3","created_at":"2023-11-09T11:20:00Z","message":{"role":"assistant","content":"Hello"},"done":false}',
        b'{"model":"llama3","created_at":"2023-11-09T11:20:01Z","message":{"role":"assistant","content":" world"},"done":true}'
    ]

    class MockStreamResponse:
        def __init__(self):
            self.status_code = 200

        async def aiter_lines(self):
            for chunk in mock_chunks:
                yield chunk

        async def aread(self):
            return b""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_stream(*args, **kwargs):
        yield MockStreamResponse()

    mock_client = mocker.AsyncMock()
    mock_client.build_request.return_value = mocker.Mock()
    mock_client.stream = mock_stream
    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    response = client.post("/v1/chat/completions", json={
        "model": "llama3",
        "messages": [{"role": "user", "content": "Say hello world"}],
        "stream": True
    })

    assert response.status_code == 200
    text = response.text
    assert "data: " in text
    assert "Hello" in text
    assert " world" in text
    assert "[DONE]" in text

@pytest.mark.asyncio
async def test_chat_completions_cancelled_queue(mocker):
    from gateway import app, state
    import gateway
    import asyncio

    # We acquire the semaphore so the request must wait in queue
    await gateway.semaphore.acquire()

    # Run the request as a task
    async def make_request():
        from httpx import ASGITransport, AsyncClient
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post("/v1/chat/completions", json={
                "model": "llama3",
                "messages": [{"role": "user", "content": "Hello"}]
            })

    task = asyncio.create_task(make_request())

    # Wait briefly for it to enter the queue
    await asyncio.sleep(0.1)

    assert state.queue_depth == 1

    # Cancel the request simulating a client disconnect
    task.cancel()

    # Wait for the cancellation to propagate
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Queue depth should be back to 0
    assert state.queue_depth == 0

    # Release the semaphore we artificially acquired
    gateway.semaphore.release()

@pytest.mark.asyncio
async def test_chat_completions_upstream_error(mocker):
    from gateway import app
    from httpx import AsyncClient, RequestError

    mock_client = mocker.AsyncMock()
    mock_client.build_request.return_value = mocker.Mock()
    # Simulate upstream error
    mock_client.send.side_effect = RequestError("Connection refused")
    mocker.patch("httpx.AsyncClient", return_value=mock_client)

    response = client.post("/v1/chat/completions", json={
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hello"}]
    })

    assert response.status_code == 502
    assert "Ollama error" in response.text

    from gateway import state
    assert state.active_inference_count == 0

@pytest.mark.asyncio
async def test_concurrency_queue_full(mocker):
    from gateway import app
    from httpx import AsyncClient
    import gateway

    # Force the queue to be full
    gateway.state.queue_depth = gateway.MAX_QUEUE_DEPTH

    response = client.post("/v1/chat/completions", json={
        "model": "llama3",
        "messages": [{"role": "user", "content": "Hello"}]
    })

    assert response.status_code == 503
    assert "Gateway overloaded" in response.text
