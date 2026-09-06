import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sys

app = FastAPI(title="OmniSearch Unified Gateway")

# Serve the static HTML page at the root
@app.get("/", response_class=FileResponse)
async def read_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

# We might be running locally (in projects/32-omnisearch-api) or inside docker (where /32-omnisearch-qdrant exists)
if os.path.exists("/32-omnisearch-qdrant"):
    sys.path.append("/32-omnisearch-qdrant")
else:
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "32-omnisearch-qdrant"))

from vector_client import OmniSearchClient

class SearchResult(BaseModel):
    file_path: str
    title: Optional[str] = None
    preview_url: Optional[str] = None
    score: float

class SearchResponse(BaseModel):
    results: List[SearchResult]

def get_text_embedding(text: str) -> List[float]:
    """Stub function to simulate calling an embedder service."""
    # In a real implementation, this would make an HTTP call to the embedder service
    # For now, we return a dummy vector (e.g., 512-dimensional array of 0.1s for testing)
    return [0.1] * 512

# Global Qdrant Client initialization
qdrant_client_instance = None

def get_qdrant_client() -> OmniSearchClient:
    global qdrant_client_instance
    if qdrant_client_instance is None:
        host = os.environ.get("QDRANT_HOST", "localhost")
        port = int(os.environ.get("QDRANT_PORT", "6333"))
        memory_str = os.environ.get("QDRANT_MEMORY", "false")
        use_memory = memory_str.lower() == "true"
        try:
            qdrant_client_instance = OmniSearchClient(host=host, port=port, memory=use_memory, max_retries=3)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to connect to Qdrant: {str(e)}")
    return qdrant_client_instance

@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="Natural language search query"),
    limit: int = Query(10, description="Maximum number of results to return"),
    threshold: float = Query(0.5, description="Minimum confidence score threshold")
):
    # 1. Call Embedder to get text embedding
    try:
        query_vector = get_text_embedding(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedder error: {str(e)}")

    # 2. Query Qdrant
    try:
        client = get_qdrant_client()
        # Assume collection name is "media_frames" as per qdrant readme
        qdrant_results = client.search(
            collection_name="media_frames",
            query_vector=query_vector,
            top_k=limit,
            threshold=threshold
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Qdrant search error: {str(e)}")

    # 3. Format JSON response
    formatted_results = []
    for point in qdrant_results:
        payload = point.payload or {}
        # Ensure file_path exists as it is required in SearchResult
        file_path = payload.get("file_path", "")
        title = payload.get("title", None)
        # Using a dummy preview url if one doesn't exist just for the UI
        preview_url = payload.get("preview_url", None)

        formatted_results.append(
            SearchResult(
                file_path=file_path,
                title=title,
                preview_url=preview_url,
                score=point.score
            )
        )

    return SearchResponse(results=formatted_results)

@app.get("/health")
async def health():
    status = {"status": "ok", "qdrant": "unknown", "embedder": "unknown"}

    # Check Embedder
    try:
        get_text_embedding("health_check")
        status["embedder"] = "ok"
    except Exception as e:
        status["embedder"] = f"error: {str(e)}"
        status["status"] = "degraded"

    # Check Qdrant
    try:
        get_qdrant_client()
        status["qdrant"] = "ok"
    except Exception as e:
        status["qdrant"] = f"error: {str(e)}"
        status["status"] = "degraded"

    if status["status"] == "degraded":
        # we still return 200, but with a degraded status message
        pass

    return status
