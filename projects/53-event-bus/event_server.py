import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Set, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("event-bus")

app = FastAPI(title="Real-Time Homelab Event Bus & Webhook Gateway", version="1.0.0")

class EventPayload(BaseModel):
    topic: str = Field(..., description="The topic to publish the event to")
    source: str = Field(..., description="The source system originating the event")
    payload: Dict[str, Any] = Field(..., description="The event payload data")
    timestamp: Optional[float] = Field(default_factory=time.time, description="Unix timestamp of the event")

class PubSubEngine:
    def __init__(self):
        # Topic to set of WebSocket connections
        self.subscribers: Dict[str, Set[WebSocket]] = {}
        # Simple throughput counter
        self.messages_processed = 0
        # Optional Redis placeholder based on env var
        self.redis_url = os.environ.get("REDIS_URL")
        self.use_redis = bool(self.redis_url)

    async def connect(self, websocket: WebSocket, topic: str):
        await websocket.accept()
        if topic not in self.subscribers:
            self.subscribers[topic] = set()
        self.subscribers[topic].add(websocket)
        logger.info(f"Client connected to topic: {topic}. Total subscribers for topic: {len(self.subscribers[topic])}")

    def disconnect(self, websocket: WebSocket, topic: str):
        if topic in self.subscribers and websocket in self.subscribers[topic]:
            self.subscribers[topic].remove(websocket)
            logger.info(f"Client disconnected from topic: {topic}. Total subscribers for topic: {len(self.subscribers[topic])}")
            if not self.subscribers[topic]:
                del self.subscribers[topic]

    async def broadcast(self, event: EventPayload):
        topic = event.topic
        message = event.model_dump_json()
        self.messages_processed += 1

        # In-memory broadcast
        if topic in self.subscribers:
            dead_sockets = set()
            for ws in self.subscribers[topic]:
                try:
                    await ws.send_text(message)
                except Exception as e:
                    logger.error(f"Error sending message to client on topic {topic}: {e}")
                    dead_sockets.add(ws)

            for ws in dead_sockets:
                self.disconnect(ws, topic)

        # Optional Redis broadcast simulation (fallback to in-memory)
        if self.use_redis:
            logger.debug(f"Broadcasting to Redis topic {topic} is currently a placeholder.")

    def get_total_subscribers(self) -> int:
        return sum(len(subs) for subs in self.subscribers.values())

engine = PubSubEngine()

@app.post("/events", status_code=202)
async def publish_event(event: EventPayload):
    """
    Ingest a structured JSON event and broadcast to WebSocket subscribers.
    """
    # Run broadcast in background
    asyncio.create_task(engine.broadcast(event))
    return {"status": "accepted"}

@app.websocket("/ws/{topic}")
async def websocket_endpoint(websocket: WebSocket, topic: str):
    """
    WebSocket channel streaming real-time events to subscribed clients.
    """
    await engine.connect(websocket, topic)
    try:
        while True:
            # Keep connection alive, though we only broadcast outwardly
            # Await receiving text so it doesn't close immediately.
            data = await websocket.receive_text()
            # If clients send messages, we can just log or ignore
            logger.debug(f"Received message from client on topic {topic}: {data}")
    except WebSocketDisconnect:
        engine.disconnect(websocket, topic)
    except Exception as e:
        logger.error(f"WebSocket error on topic {topic}: {e}")
        engine.disconnect(websocket, topic)

@app.get("/health")
async def health_check():
    """
    Health probe reporting active WebSocket subscriber count and message throughput.
    """
    return {
        "status": "healthy",
        "active_subscribers": engine.get_total_subscribers(),
        "messages_processed": engine.messages_processed,
        "backend": "redis" if engine.use_redis else "in-memory"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("event_server:app", host="0.0.0.0", port=8088, reload=True)
