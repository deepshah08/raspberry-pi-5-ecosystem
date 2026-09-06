FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx

COPY gateway.py .

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8000"]
