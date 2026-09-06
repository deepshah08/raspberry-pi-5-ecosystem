FROM python:3.11-slim

WORKDIR /app

RUN pip install fastapi uvicorn httpx pydantic qdrant-client

COPY . /app

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
