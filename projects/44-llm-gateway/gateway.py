import os
import time
import asyncio
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import json

app = FastAPI(title="Local LLM API Gateway & Resource Throttler")

OLLAMA_BACKEND_URL = os.getenv("OLLAMA_BACKEND_URL", "http://192.168.1.92:11434")
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "1"))
MAX_QUEUE_DEPTH = int(os.getenv("MAX_QUEUE_DEPTH", "5"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))

class GatewayState:
    active_inference_count = 0
    queue_depth = 0

state = GatewayState()

# Initialize dynamically on startup for event loop stability
semaphore = None

@app.on_event("startup")
async def startup_event():
    global semaphore
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

@app.get("/health")
async def health():
    start_time = time.time()
    ollama_latency = None
    ollama_status = "unreachable"

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{OLLAMA_BACKEND_URL}/")
            ollama_status = "ok" if resp.status_code == 200 else "error"
            ollama_latency = time.time() - start_time
    except Exception:
        pass

    return {
        "status": "ok" if ollama_status == "ok" else "degraded",
        "queue_depth": state.queue_depth,
        "active_inference_count": state.active_inference_count,
        "ollama_latency_seconds": ollama_latency,
        "ollama_status": ollama_status
    }

@app.get("/v1/models")
async def list_models():
    """Returns list of available local models."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BACKEND_URL}/api/tags")

            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Upstream Ollama error")

            data = resp.json()

            # Map Ollama format to OpenAI format
            models = []
            for model in data.get("models", []):
                models.append({
                    "id": model["name"],
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "ollama"
                })

            return {
                "object": "list",
                "data": models
            }

    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Error connecting to Ollama backend: {str(e)}")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible endpoint streaming tokens from Ollama/backend."""
    if state.queue_depth >= MAX_QUEUE_DEPTH:
        raise HTTPException(status_code=503, detail="Gateway overloaded, too many pending requests.")

    state.queue_depth += 1
    in_queue = True
    semaphore_acquired = False

    try:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        # Wait for the semaphore with a timeout
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=REQUEST_TIMEOUT_SECONDS)
            semaphore_acquired = True
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Gateway timeout")

        # Acquired semaphore successfully
        state.queue_depth -= 1
        in_queue = False
        state.active_inference_count += 1

        # We explicitly pass the responsibility to release the semaphore
        # to the background stream or the response block.
        # But if an exception occurs before we return, we must release it here.
        success = False
        try:
            resp = await process_chat_request(body, request)
            success = True
            return resp
        finally:
            if not success:
                state.active_inference_count -= 1
                semaphore.release()
    finally:
        if in_queue:
            state.queue_depth -= 1

async def process_chat_request(body: dict, request: Request):
    # Translate OpenAI request to Ollama request format
    # The minimum required fields for Ollama chat API
    ollama_request = {
        "model": body.get("model", "llama3"),
        "messages": body.get("messages", []),
        "stream": body.get("stream", False)
    }

    # Pass through other common options if they exist
    options = {}
    if "temperature" in body:
        options["temperature"] = body["temperature"]
    if "top_p" in body:
        options["top_p"] = body["top_p"]
    if "max_tokens" in body:
        options["num_predict"] = body["max_tokens"]

    if options:
        ollama_request["options"] = options

    client = httpx.AsyncClient(timeout=float(REQUEST_TIMEOUT_SECONDS))

    # We always use the chat endpoint for ollama
    req = client.build_request("POST", f"{OLLAMA_BACKEND_URL}/api/chat", json=ollama_request)

    if ollama_request["stream"]:
        async def generate():
            try:
                # Need to use stream for httpx
                async with client.stream("POST", f"{OLLAMA_BACKEND_URL}/api/chat", json=ollama_request) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield f"data: {json.dumps({'error': error_text.decode('utf-8')})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)

                            # Convert Ollama streaming chunk to OpenAI format
                            chunk = {
                                "id": "chatcmpl-gateway",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": ollama_request["model"],
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "role": data.get("message", {}).get("role", "assistant") if "message" in data else None,
                                            "content": data.get("message", {}).get("content", "") if "message" in data else ""
                                        },
                                        "finish_reason": "stop" if data.get("done") else None
                                    }
                                ]
                            }

                            # Filter out None values in delta
                            if chunk["choices"][0]["delta"]["role"] is None:
                                del chunk["choices"][0]["delta"]["role"]

                            yield f"data: {json.dumps(chunk)}\n\n"

                        except json.JSONDecodeError:
                            continue

                    yield "data: [DONE]\n\n"
            finally:
                await client.aclose()
                state.active_inference_count -= 1
                semaphore.release()

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        # Non-streaming response
        try:
            response = await client.send(req)
            await client.aclose()

            if response.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Ollama error: {response.text}")

            data = response.json()

            # Map Ollama response to OpenAI format
            return {
                "id": "chatcmpl-gateway",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": ollama_request["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": data.get("message", {}),
                        "finish_reason": "stop" if data.get("done") else "length"
                    }
                ],
                "usage": {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
                }
            }
        except Exception as e:
            await client.aclose()
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=502, detail=f"Ollama error: {str(e)}")
        finally:
            pass

        # The non-streaming path finished executing successfully, let chat_completions handle release if error,
        # but if we succeed, we must release it here. Wait, actually, let's keep it consistent:
        # If we return normally from process_chat_request, chat_completions sets success=True
        # and doesn't release it! So we MUST release it here if we succeed.
        # If we raise an exception, chat_completions sets success=False and releases it!
        # So we MUST NOT release it here if we raise an exception.
        state.active_inference_count -= 1
        semaphore.release()
