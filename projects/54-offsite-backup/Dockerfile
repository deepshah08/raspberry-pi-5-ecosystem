FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y rclone sqlite3 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backup_orchestrator.py .
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "backup_orchestrator.py"]
