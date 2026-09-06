# OmniSearch Unified Gateway (API & Dashboard)

This project provides the central gateway for OmniSearch, a natural language media search engine. It features a FastAPI application acting as a central hub between the user, the embedding model, and the Qdrant vector database.

## Architecture

The gateway serves both an HTML front-end and a REST JSON API.

```mermaid
sequenceDiagram
    participant U as User
    participant F as FastAPI Gateway
    participant E as Embedder Service
    participant Q as Qdrant DB

    U->>F: GET /search?q="query text"
    F->>E: Request Text Embedding
    E-->>F: Return Vector (e.g., 512 dimensions)
    F->>Q: Query Points (Cosine Similarity)
    Q-->>F: Return Matched Metadata
    F-->>U: Return JSON Search Results
```

## Setup & Execution

### 1. Start Service

Ensure you have Docker and Docker Compose installed.

```bash
cd projects/32-omnisearch-api
docker-compose up -d
```

The service will bind to port `8008`.

### 2. Access the Dashboard

Open your browser and navigate to `http://localhost:8008/` to access the lightweight single-page HTML interface with an instant search bar.

### 3. API Endpoints

- `GET /search?q={query}&limit={limit}&threshold={threshold}`: Natural language query endpoint.
- `GET /health`: Health probe reporting status of Qdrant connection and embedder service.

## Testing

Run tests using pytest:

```bash
pytest projects/32-omnisearch-api/tests/test_server.py
```
